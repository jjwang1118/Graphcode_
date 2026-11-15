"""把 import 敘述接成 `imports` 邊，並把外部套件分類。規格：docs/spec/analyze.md

查找交給目標環境的 Python（probe.py），這裡只決定「查什麼」與「答案代表什麼」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..model import Edge, Node, dir_id, ext_id, file_id
from .definitions import FileFacts, ImportStmt
from .roots import normalize, run_probe
from .scan import ScanResult

# 沒安裝時無從查證「import 名 → 套件名」，只能靠這張常見對照表猜（結果會標 distribution_source）
KNOWN_DISTRIBUTIONS = {
    "cv2": "opencv-python", "yaml": "pyyaml", "PIL": "pillow", "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
    "skimage": "scikit-image", "attr": "attrs", "git": "gitpython", "jwt": "pyjwt",
    "serial": "pyserial", "magic": "python-magic", "OpenSSL": "pyopenssl", "google.protobuf": "protobuf",
    "Crypto": "pycryptodome", "docx": "python-docx", "fitz": "pymupdf", "win32api": "pywin32",
}  # fmt: skip

Key = tuple[str, str, str]  # (查法, 起點目錄, 名字)
Chain = list[dict[str, Any]]


@dataclass
class ImportResult:
    ext_nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    edge_modules: list[str | None] = field(
        default_factory=list
    )  # 與 edges 對齊；絕對 import 的模組名
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    env: dict[str, Any] = field(default_factory=dict)
    missing_dependencies: list[str] = field(default_factory=list)
    checks: dict[str, tuple[str, str | None]] = field(
        default_factory=dict
    )  # 模組名 → (found/missing/skip, 檔案)


@dataclass
class _Plan:
    rel: str
    stmt: ImportStmt
    beyond: bool = False
    mod: Key | None = None  # 模組本身
    sub: Key | None = None  # 模組.名字（名字可能是子模組）
    alt_mod: Key | None = None  # 以「檔案所在資料夾」為起點重查（當成腳本直接執行時）
    alt_sub: Key | None = None
    env_top: Key | None = None  # 最頂層名字只在環境裡查（不含搜尋根）：判斷有沒有蓋掉別人


class _Resolver:
    def __init__(
        self, scan: ScanResult, roots: list[Path], facts: dict[str, FileFacts], declared: set[str]
    ) -> None:
        self.root = scan.root
        self.roots = roots
        self.files = set(scan.files)
        self.dirs = set(scan.dirs)
        self.facts = facts
        self.declared = declared
        self.queries: list[dict[str, Any]] = []
        self._ids: dict[Key, str] = {}
        self.env: dict[str, Any] = {}
        self.env_dirs: set[Path] = set()
        self._reason: str | None = None
        self.result = ImportResult()

    # --- 第一步：決定要查什麼 ---

    def _ask(self, kind: str, base: str, name: str) -> Key:
        key = (kind, base, name)
        if key not in self._ids:
            self._ids[key] = str(len(self._ids))
            paths = {"abs": [str(r) for r in self.roots], "env": []}.get(kind, [base])
            self.queries.append(
                {"id": self._ids[key], "name": name, "paths": paths, "with_env": kind != "rel"}
            )
        return key

    def _script_dir(self, rel: str) -> str | None:
        """這個檔案若可能被直接執行，回傳它所在的資料夾；否則 None。"""
        folder = (self.root / rel).parent
        if folder in self.roots:
            return None
        if self.facts[rel].has_main_guard or not (folder / "__init__.py").is_file():
            return str(folder)
        return None

    def plan(self, rel: str, stmt: ImportStmt) -> _Plan:
        plan = _Plan(rel=rel, stmt=stmt)
        named = stmt.name not in (None, "*")
        if stmt.level == 0:
            assert stmt.module is not None
            plan.mod = self._ask("abs", "", stmt.module)
            plan.env_top = self._ask("env", "", stmt.module.split(".")[0])
            if named:
                plan.sub = self._ask("abs", "", f"{stmt.module}.{stmt.name}")
            folder = self._script_dir(rel)
            if folder:
                plan.alt_mod = self._ask("alt", folder, stmt.module)
                if named:
                    plan.alt_sub = self._ask("alt", folder, f"{stmt.module}.{stmt.name}")
            return plan
        # 相對 import：照路徑往上走，不能走出所屬的搜尋根（那是最頂層套件之外）
        file_path = self.root / rel
        # 檔案不在任何搜尋根之下時（使用者自訂了 roots），以專案根為界
        candidates = [r for r in self.roots if r in file_path.parents] or [self.root]
        containing = max(candidates, key=lambda r: len(r.parts))
        base = file_path.parent
        for _ in range(stmt.level - 1):
            base = base.parent
        if containing not in base.parents:
            plan.beyond = True
            return plan
        if stmt.module:
            plan.mod = self._ask("rel", str(base), stmt.module)
            if named:
                plan.sub = self._ask("rel", str(base), f"{stmt.module}.{stmt.name}")
        elif named:
            plan.sub = self._ask("rel", str(base), str(stmt.name))
        plan.alt_mod = ("base", str(base), "")  # 只借欄位記住起點目錄，不是查詢
        return plan

    # --- 第二步：解讀答案 ---

    def _chain(self, key: Key | None) -> Chain:
        return self.env["results"].get(self._ids[key], []) if key else []

    def _locate(self, element: dict[str, Any]) -> tuple[str, str]:
        """查到的東西在哪：file / dir（在圖裡）、excluded（專案內但被掃描排除）、outside。"""
        origin = element["origin"]
        where = origin or (element["locations"][0] if element["locations"] else None)
        if where is None:
            return ("outside", "")
        resolved = Path(where).resolve()
        try:
            rel = resolved.relative_to(self.root).as_posix()
        except ValueError:
            return ("outside", where)
        if rel in (self.files if origin else self.dirs):
            return ("file" if origin else "dir", rel)
        # 專案資料夾裡的虛擬環境：位置在專案內，但它是環境的一部分，不是專案的程式
        if any(d == resolved or d in resolved.parents for d in self.env_dirs):
            return ("outside", where)
        return ("excluded", rel)

    @staticmethod
    def _node_id(kind: str, rel: str) -> str:
        return file_id(rel) if kind == "file" else dir_id(rel)

    def _package_target(
        self, kind: str, rel: str, name: str | None, sub: Chain, sub_len: int
    ) -> str:
        """`from <套件> import <名字>`：名字是套件自己的屬性，還是子模組。"""
        if name in (None, "*"):
            return self._node_id(kind, rel)
        if kind == "file" and rel.endswith("__init__.py") and name in self.facts[rel].top_names:
            return self._node_id(kind, rel)  # __init__.py 自己綁定的名字優先
        if len(sub) == sub_len:
            sub_kind, sub_rel = self._locate(sub[-1])
            if sub_kind in ("file", "dir"):
                return self._node_id(sub_kind, sub_rel)
        return self._node_id(kind, rel)

    def _local(self, mod: Chain, mod_len: int, sub: Chain, name: str | None) -> str | None:
        if len(mod) != mod_len:
            return None
        kind, rel = self._locate(mod[-1])
        if kind not in ("file", "dir"):
            if kind == "excluded":
                self._reason = "目標在專案內，但被掃描排除"
            return None
        return self._package_target(kind, rel, name, sub, mod_len + 1)

    def _ext(self, top: str, element: dict[str, Any] | None, excluded: bool = False) -> str:
        env = self.env
        installed = element is not None
        distributions = env["packages_distributions"].get(top, []) if installed else []
        origin = (element or {}).get("origin") or ""
        in_stdlib_dir = any(origin.startswith(d) for d in env["stdlib_dirs"]) and not any(
            marker in origin for marker in ("site-packages", "dist-packages")
        )
        declared = any(normalize(d) in self.declared for d in distributions) or (
            not installed and normalize(top) in self.declared
        )
        guessed = False
        if not installed and not declared and KNOWN_DISTRIBUTIONS.get(top) in self.declared:
            declared, guessed, distributions = True, True, [KNOWN_DISTRIBUTIONS[top]]
        if excluded:
            category = "excluded"
        elif top in self.unshadowable or top in env["stdlib_names"] or in_stdlib_dir:
            # 在標準庫名單裡但這個平台查不到的（Linux 上的 winreg）不算已安裝
            category, installed = "stdlib", installed or top in self.unshadowable
        elif installed or declared:
            category = "third_party"
        else:
            category = "unknown"
        node_id = ext_id(top)
        if node_id not in self.result.ext_nodes:
            props: dict[str, Any] = {"category": category, "installed": installed}
            if distributions:
                props["distributions"] = distributions
            if guessed:
                props["distribution_source"] = "known_alias"
            if category in ("third_party", "unknown"):
                props["declared"] = declared
            self.result.ext_nodes[node_id] = Node(node_id, "external_package", top, props)
        return node_id

    def _top_id(self, top: str, element: dict[str, Any]) -> str:
        kind, rel = self._locate(element)
        if kind in ("file", "dir"):
            return self._node_id(kind, rel)
        return self._ext(top, element, excluded=kind == "excluded")  # 確保節點存在

    def _absolute(self, plan: _Plan, props: dict[str, Any]) -> str | None:
        stmt = plan.stmt
        assert stmt.module is not None
        parts = stmt.module.split(".")
        top = parts[0]
        chain, sub = self._chain(plan.mod), self._chain(plan.sub)
        if top in self.unshadowable:
            self.result.checks.setdefault(stmt.module, ("skip", None))
            return self._ext(top, None)
        full = len(chain) == len(parts)
        origin = chain[-1]["origin"] if full else None
        self.result.checks.setdefault(
            stmt.module,
            ("found", origin) if full and origin else ("skip", None) if full else ("missing", None),
        )
        alt, alt_sub = self._chain(plan.alt_mod), self._chain(plan.alt_sub)
        if not chain:
            # 宣告的根之下找不到。若檔案所在資料夾裡有，代表它是被當成腳本執行的同層 import
            target = self._local(alt, len(parts), alt_sub, stmt.name) if alt else None
            if target:
                props["via"] = "script_dir"
                props["entry_sensitive"] = True
                return target
            return self._ext(top, None)
        kind, _ = self._locate(chain[0])
        if alt and self._locate(alt[0]) != self._locate(chain[0]):
            props["entry_sensitive"] = True
            props["alt_target"] = self._top_id(top, alt[0])
        if kind == "outside":
            return self._ext(top, chain[0])
        if kind == "excluded":
            return self._ext(top, chain[0], excluded=True)
        # 拿掉搜尋根、只在環境裡查同一個名字：查得到且是別的位置，才是真的蓋掉了別人
        # （專案自己被安裝在環境裡時，查到的是同一個位置，不算）
        elsewhere = self._chain(plan.env_top)
        if elsewhere and self._locate(elsewhere[0]) != self._locate(chain[0]):
            props["shadows"] = "stdlib" if top in self.env["stdlib_names"] else "third_party"
        return self._local(chain, len(parts), sub, stmt.name)

    def _relative(self, plan: _Plan, props: dict[str, Any]) -> str | None:
        stmt = plan.stmt
        sub = self._chain(plan.sub)
        if stmt.module:
            return self._local(self._chain(plan.mod), len(stmt.module.split(".")), sub, stmt.name)
        # `from . import x`：起點目錄本身就是套件
        assert plan.alt_mod is not None
        base = Path(plan.alt_mod[1]).relative_to(self.root).as_posix()
        init = f"{base}/__init__.py"
        kind, rel = ("file", init) if init in self.files else ("dir", base)
        return self._package_target(kind, rel, stmt.name, sub, 1)

    def resolve(
        self, plans: list[_Plan], extra_paths: list[str], python: str | None
    ) -> ImportResult:
        self.env = run_probe(python, self.queries, extra_paths)
        env, result = self.env, self.result
        self.env_dirs = {Path(p).resolve() for p in env["env_paths"]} - set(self.roots)
        self.unshadowable = set(env["builtin_names"]) | (
            set(env["startup_modules"]) & set(env["stdlib_names"])
        )
        stats = dict.fromkeys(
            ("total", "local", "stdlib", "third_party", "unknown", "excluded", "unresolved",
             "shadowing", "entry_sensitive", "via_script_dir", "guarded", "type_checking"), 0
        )  # fmt: skip
        for plan in plans:
            stmt = plan.stmt
            stats["total"] += 1
            written = "." * stmt.level + (stmt.module or "")
            props: dict[str, Any] = {"line": stmt.line, "module": written, "scope": stmt.scope}
            if stmt.name is not None:
                props["name"] = stmt.name
            for flag in ("type_checking", "guarded"):
                if getattr(stmt, flag):
                    props[flag] = True
                    stats[flag] += 1
            self._reason = None
            if plan.beyond:
                target, reason = None, "相對 import 超出最頂層套件"
            elif stmt.level == 0:
                target, reason = self._absolute(plan, props), "本地套件內找不到這個模組"
            else:
                target, reason = self._relative(plan, props), "相對 import 找不到目標"
            if target is None:
                stats["unresolved"] += 1
                result.unresolved.append(
                    {
                        "file": plan.rel,
                        "line": stmt.line,
                        "module": written,
                        "name": stmt.name,
                        "reason": self._reason or reason,
                    }
                )
                continue
            category = (
                result.ext_nodes[target].properties["category"]
                if target in result.ext_nodes
                else "local"
            )
            stats[category] += 1
            stats["shadowing"] += "shadows" in props
            stats["entry_sensitive"] += "entry_sensitive" in props
            stats["via_script_dir"] += props.get("via") == "script_dir"
            result.edges.append(Edge(file_id(plan.rel), target, "imports", props))
            result.edge_modules.append(stmt.module if stmt.level == 0 else None)
        result.stats = stats
        installed = {normalize(name) for name in env["installed"]}
        result.missing_dependencies = sorted(self.declared - installed)
        result.env = {k: v for k, v in env.items() if k != "results"}
        return result


def resolve_imports(
    scan: ScanResult,
    roots: list[Path],
    facts: dict[str, FileFacts],
    declared: set[str],
    python: str | None = None,
    extra_paths: list[str] | None = None,
) -> ImportResult:
    resolver = _Resolver(scan, roots, facts, declared)
    plans = [resolver.plan(rel, stmt) for rel in sorted(facts) for stmt in facts[rel].imports]
    return resolver.resolve(plans, extra_paths or [], python)
