"""用 Jedi 解析使用點，產生 calls / inherits / overrides / references 邊。

規格：docs/spec/analyze.md（AN-U 規則）。
"""

from __future__ import annotations

import tokenize
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..model import Edge, decl_id, file_id
from .definitions import FileFacts
from .engine import Engine
from .uses import Site, collect_sites

# 引擎回報的實作模組 → 人實際 import 的名字
_MODULE_ALIASES = {"posixpath": "os", "ntpath": "os", "genericpath": "os", "_io": "io"}

REASONS = {
    "dynamic": "被呼叫的是運算結果（下標、另一個呼叫的回傳值等）",
    "param": "參數，型別未知",
    "variable": "變數，型別推不出來",
    "module": "指向模組，不是函式或類別",
    "unindexed": "指向專案內，但不是 class／function 定義",
    "no_call_method": "物件實例，找不到 __call__",
    "unknown": "引擎解不出",
    "property": "屬性存取，接收者型別未知（專案內有同名的 @property）",
}


@dataclass
class UsesResult:
    edges: list[Edge] = field(default_factory=list)
    node_props: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: dict[str, Any] = field(default_factory=dict)
    inherits: dict[str, int] = field(default_factory=dict)
    references: int = 0
    unresolved_property_reads: int = 0
    overrides: int = 0


class _Resolver:
    def __init__(
        self,
        root: Path,
        facts: dict[str, FileFacts],
        engine: Engine,
        ensure_ext: Callable[[str], str],
        bindings: dict[str, dict[str, tuple[str, str]]],
    ) -> None:
        self.root = root
        self.facts = facts
        self.engine = engine
        self.ensure_ext = ensure_ext
        self.bindings = bindings  # 檔案 → {檔案層 import 綁定的名字: (外部節點 id, 完整名字)}
        self._rel = ""  # 目前正在處理的檔案
        self.by_position: dict[tuple[str, int, str], tuple[str, str]] = {}
        self.by_name: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self.scope_ids: dict[str, dict[str, str]] = {}
        self.methods: dict[str, dict[str, str]] = {}  # class id → {方法名: function id}
        self.parents: dict[str, list[str]] = {}  # class id → 專案內的 base
        self.candidates: set[str] = set()
        self.properties: set[str] = set()  # 專案內 @property 的名字
        self.property_functions: set[str] = set()  # 它們的節點 id
        for rel, file_facts in facts.items():
            ids = self.scope_ids.setdefault(rel, {})
            for d in file_facts.definitions:
                node_id = decl_id(d.kind, rel, d.qualname)
                ids[d.qualname] = node_id
                self.by_position[(rel, d.line, d.name)] = (node_id, d.kind)
                if d.parent is None:
                    self.by_name.setdefault((rel, d.name), []).append((node_id, d.kind))
                if d.kind == "function" and d.parent and d.parent in ids:
                    owner = ids[d.parent]
                    if owner.startswith("class:"):
                        self.methods.setdefault(owner, {}).setdefault(d.name, node_id)
                self.candidates.add(d.name)
                if d.kind == "function" and any(
                    x.split(".")[-1] in ("property", "cached_property")
                    for x in d.properties.get("decorators", [])
                ):
                    self.properties.add(d.name)
                    self.property_functions.add(node_id)
            self.candidates.update(i.asname for i in file_facts.imports if i.asname)
        self._edges: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        self.result = UsesResult()

    # --- 引擎的答案 → 圖上的節點 ---

    def _map(self, name: Any) -> tuple[str, Any]:
        """回傳 ("node", (id, kind)) / ("ext", (最頂層, 完整名字)) / ("unindexed", None) / ("none", None)。"""
        path = name.module_path
        if path is not None:
            try:
                rel = Path(path).resolve().relative_to(self.root).as_posix()
            except ValueError:
                rel = None
            if rel in self.facts:
                hit = self.by_position.get((rel, name.line, name.name))
                if hit is None:
                    same_name = self.by_name.get((rel, name.name), [])
                    hit = same_name[0] if len(same_name) == 1 else None
                return ("node", hit) if hit else ("unindexed", None)
        full = name.full_name or name.module_name or ""
        top = full.split(".")[0]
        top = _MODULE_ALIASES.get(top, top)
        return ("ext", (top, full)) if top else ("none", None)

    def _find_method(self, class_id: str, method: str) -> str | None:
        """沿專案內的繼承往上找第一個定義了這個方法的 class。"""
        queue, seen = [class_id], set()
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            found = self.methods.get(current, {}).get(method)
            if found:
                return found
            queue.extend(self.parents.get(current, []))
        return None

    def _ancestors(self, class_id: str) -> set[str]:
        found: set[str] = set()
        queue = list(self.parents.get(class_id, []))
        while queue:
            current = queue.pop()
            if current not in found:
                found.add(current)
                queue.extend(self.parents.get(current, []))
        return found

    def _edge(self, source: str, target: str, kind: str, line: int, **extra: Any) -> None:
        key = (source, target, kind, str(extra.get("via", "")), str(extra.get("callee", "")))
        props = self._edges.get(key)
        if props is None:
            props = {"count": 0, "lines": [], **{k: v for k, v in extra.items() if v}}
            if kind in ("calls", "inherits"):
                props.setdefault("evidence", "jedi")
            self._edges[key] = props
        props["count"] += 1
        if line not in props["lines"]:
            props["lines"].append(line)
        if extra.get("ambiguous"):
            props["ambiguous"] = True

    def _unresolved(self, key: str, scope_id: str, site: Site, reason: str) -> None:
        self.result.node_props.setdefault(scope_id, {}).setdefault(key, []).append(
            {"line": site.line, "text": site.text, "reason": reason}
        )

    # --- 三種使用點 ---

    def _definitions(self, script: Any, site: Site) -> tuple[list[Any], str]:
        """被呼叫或被繼承的名字指向哪些 class／function。回傳 (定義, 解不出時的原因代號)。"""
        found, reason = self._lookup(script, site)
        # 引擎偶爾在正確答案之外多回一個不相干的型別（`handle.write` 多出 `typing.Callable`）：
        # 有名字相符的就只留相符的
        written = site.text.split(".")[-1]
        matching = [d for d in found if d.name == written]
        return (matching if matching and len(found) > 1 else found), reason

    def _lookup(self, script: Any, site: Site) -> tuple[list[Any], str]:
        found = self.engine.goto(script, site.line, site.col)
        direct = [d for d in found if d.type in ("function", "class")]
        if direct and len(direct) == len(found):
            return direct, ""
        # 名字指向變數或參數：改問「它的值是什麼」
        inferred = [
            d
            for d in self.engine.infer(script, site.line, site.col)
            if d.type in ("function", "class", "instance")
        ]
        if inferred:
            return inferred, ""
        if direct:
            return direct, ""
        types = {d.type for d in found}
        for kind, reason in (("param", "param"), ("statement", "variable"), ("module", "module")):
            if kind in types:
                return [], reason
        return [], "unknown"

    def _imported(self, site: Site) -> tuple[str, str] | None:
        """引擎解不出時的退路：名字是檔案層 import 自外部套件的（多半是套件沒安裝）。

        只知道「來自哪個套件」，不知道確切的定義，所以邊的 evidence 標 import。
        """
        head, *rest = site.text.split(".")
        bound = self.bindings.get(self._rel, {}).get(head)
        if bound is None:
            return None
        return bound[0], ".".join([bound[1], *rest])

    def _base(self, script: Any, class_id: str, site: Site) -> None:
        stats = self.result.inherits
        stats["bases"] += 1
        names, reason = self._definitions(script, site)
        linked = False
        for name in names:
            kind, value = self._map(name)
            if kind == "node" and value[1] == "class":
                self._edge(class_id, value[0], "inherits", site.line, base=site.text)
                self.parents.setdefault(class_id, []).append(value[0])
                linked = True
            elif kind == "ext":
                self._edge(
                    class_id, self.ensure_ext(value[0]), "inherits", site.line, base=value[1]
                )
                linked = True
        fallback = None if linked or reason != "unknown" else self._imported(site)
        if fallback:
            self._edge(
                class_id, fallback[0], "inherits", site.line, base=fallback[1], evidence="import"
            )
            linked = True
        if linked:
            stats["resolved"] += 1
        else:
            stats["unresolved"] += 1
            self._unresolved("unresolved_bases", class_id, site, REASONS["unknown"])

    def _call(self, script: Any, scope_id: str, site: Site) -> None:
        stats = self.result.calls
        stats["expressions"] += 1
        targets: list[tuple[str, dict[str, Any]]] = []
        reason = "dynamic"
        if site.resolvable:
            names, reason = self._definitions(script, site)
            for name in names:
                kind, value = self._map(name)
                if kind == "ext":
                    targets.append((self.ensure_ext(value[0]), {"callee": value[1]}))
                elif kind == "unindexed":
                    reason = reason or "unindexed"
                elif kind == "node":
                    node_id, node_kind = value
                    if name.type == "instance":
                        method = self._find_method(node_id, "__call__")
                        if method:
                            targets.append((method, {"via": "call_method"}))
                        else:
                            reason = reason or "no_call_method"
                    elif node_kind == "class":
                        targets.append((node_id, {}))
                        constructor = self._find_method(node_id, "__init__")
                        if constructor:
                            targets.append((constructor, {"via": "constructor"}))
                    elif node_kind == "function":
                        targets.append((node_id, {}))
                    else:
                        reason = reason or "unindexed"
        if not targets and site.resolvable and reason == "unknown":
            fallback = self._imported(site)
            if fallback:
                targets.append((fallback[0], {"callee": fallback[1], "evidence": "import"}))
        if not targets:
            reason = reason or "unknown"
            stats["unresolved"] += 1
            stats["reasons"][reason] += 1
            self._unresolved("unresolved_calls", scope_id, site, REASONS[reason])
            return
        stats["resolved"] += 1
        local = [t for t, extra in targets if not t.startswith("ext:") and "via" not in extra]
        stats["local" if any(not t.startswith("ext:") for t, _ in targets) else "external"] += 1
        ambiguous = len(set(local)) > 1 or len({t for t, _ in targets if t.startswith("ext:")}) > 1
        stats["ambiguous"] += ambiguous
        for target, extra in targets:
            if site.decorator:
                extra = {**extra, "decorator": True}
            self._edge(scope_id, target, "calls", site.line, ambiguous=ambiguous, **extra)

    def _reference(self, script: Any, scope_id: str, site: Site) -> None:
        found = self.engine.goto(script, site.line, site.col)
        for name in found:
            kind, value = self._map(name)
            if kind == "node" and value[0] != scope_id:
                self._edge(scope_id, value[0], "references", site.line)
        # 讀 @property 會執行函式。接收者的型別推不出來時連不到它：不能無聲地漏掉
        if not found and "." in site.text and site.text.split(".")[-1] in self.properties:
            self.result.unresolved_property_reads += 1
            self._unresolved("unresolved_calls", scope_id, site, REASONS["property"])

    # --- 主流程 ---

    def run(self) -> UsesResult:
        result = self.result
        result.calls = dict.fromkeys(
            ("expressions", "resolved", "unresolved", "local", "external", "ambiguous"), 0
        )
        result.calls["reasons"] = Counter()
        result.inherits = dict.fromkeys(("bases", "resolved", "unresolved"), 0)
        work = []
        for rel in sorted(self.facts):
            if self.facts[rel].parse_error:
                continue
            path = self.root / rel
            try:
                with tokenize.open(path) as handle:
                    source = handle.read()
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            sites = collect_sites(source, self.facts[rel], self.candidates)
            if sites:
                work.append((rel, self.engine.script(path, source), sites))

        def scope_id(rel: str, site: Site) -> str:
            return self.scope_ids[rel].get(site.scope or "", file_id(rel))

        # 先解繼承：呼叫的解析要靠它找建構子與 __call__
        for rel, script, sites in work:
            self._rel = rel
            for site in sites:
                if site.role == "base":
                    self._base(script, scope_id(rel, site), site)
        for rel, script, sites in work:
            self._rel = rel
            for site in sites:
                if site.role == "call":
                    self._call(script, scope_id(rel, site), site)
                elif site.role == "ref":
                    self._reference(script, scope_id(rel, site), site)
        # 覆寫：子類別的方法 → 最近一個定義了同名方法的祖先
        for class_id, methods in self.methods.items():
            for method, function_id in methods.items():
                for parent in self.parents.get(class_id, []):
                    inherited = self._find_method(parent, method)
                    if inherited:
                        self._edge(function_id, inherited, "overrides", 0)
                        break
        # Protocol（結構型別）：沒有繼承關係，但方法名稱全部對得上的 class 就算實作了它。
        # 呼叫 Protocol 的方法，執行時跑的是這些 class 的同名方法
        protocols = {
            source
            for (source, _target, kind, _via, _callee), props in self._edges.items()
            if kind == "inherits" and str(props.get("base", "")).split(".")[-1] == "Protocol"
        }
        for protocol in protocols:
            wanted = self.methods.get(protocol, {})
            # 只要求「真的方法」都有。Protocol 的 @property 成員可以用一般屬性滿足
            # （類別屬性、dataclass 欄位、__init__ 裡的 self.x），那些我們看不全，不拿來當門檻
            required = [n for n, fid in wanted.items() if fid not in self.property_functions]
            if not required:
                continue
            for class_id in self.methods:
                if class_id in protocols or protocol in self._ancestors(class_id):
                    continue
                matched = [n for n in required if self._find_method(class_id, n)]
                # 實際的程式常常只實作一部分（鴨子型別）：方法全部都有算符合；
                # 至少兩個、且過半，也算，但標 partial
                complete = len(matched) == len(required)
                partial = len(matched) >= 2 and len(matched) * 2 >= len(required)
                if complete or partial:
                    for name, declared in wanted.items():
                        # 實作可能是從祖先繼承來的：連到真正的那個方法
                        own = self._find_method(class_id, name)
                        if own:
                            self._edge(
                                own, declared, "overrides", 0, via="protocol", partial=not complete
                            )
        for (source, target, kind, _via, _callee), props in self._edges.items():
            if kind == "overrides":
                props = {k: props[k] for k in ("via", "partial") if props.get(k)}
            else:
                props["lines"].sort()
            result.edges.append(Edge(source, target, kind, props))
        result.calls["reasons"] = dict(result.calls["reasons"])
        result.references = sum(1 for e in result.edges if e.type == "references")
        result.overrides = sum(1 for e in result.edges if e.type == "overrides")
        return result


def resolve_uses(
    root: Path,
    facts: dict[str, FileFacts],
    engine: Engine,
    ensure_ext: Callable[[str], str],
    bindings: dict[str, dict[str, tuple[str, str]]],
) -> UsesResult:
    return _Resolver(root, facts, engine, ensure_ext, bindings).run()
