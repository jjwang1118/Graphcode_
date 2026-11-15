"""用「另一套獨立的方法」算答案，和 codegraph_fable 的答案比對。一次性的驗證腳本，不是產品程式碼。

獨立的方法刻意不用 codegraph_fable 的分析：
- import：自己用 ast 掃、自己把相對 import 換成絕對名字
- 繼承：在專案的環境裡真的 import 所有模組，問 Python `issubclass`
- 直接呼叫者：用 ast 找「呼叫了這個名字」的函式（只適用名字在專案內唯一的函式）
- 循環：用上面那套獨立的 import 圖另外算一次

用法：python check.py <專案根> <專案環境的 python> <設定檔.json>
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from codegraph_fable.analyze import analyze
from codegraph_fable.query import Index, cycles, impact

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}


def python_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.py") if not (set(p.relative_to(root).parts[:-1]) & SKIP_DIRS)
    )


def module_name(root: Path, roots: list[Path], path: Path) -> str | None:
    """檔案對應的模組名（從包含它的最深的搜尋根算起）。"""
    for base in sorted(roots, key=lambda r: -len(r.parts)):
        if base in path.parents:
            parts = list(path.relative_to(base).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            return ".".join(parts)
    return None


def scan_imports(root: Path, roots: list[Path]) -> dict[str, list[dict]]:
    """每個檔案的 import：絕對模組名、from-import 的名字、是否在檔案層、是否只給型別檢查。"""
    found: dict[str, list[dict]] = {}
    for path in python_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        own = module_name(root, roots, path)
        package = own.split(".") if own else []
        if path.name != "__init__.py" and package:
            package = package[:-1]
        items: list[dict] = []

        def visit(node: ast.AST, top: bool, typing_only: bool) -> None:
            for child in ast.iter_child_nodes(node):
                inner_top = top and not isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
                )
                inner_typing = typing_only
                if isinstance(child, ast.If) and ast.unparse(child.test) in (
                    "TYPE_CHECKING",
                    "typing.TYPE_CHECKING",
                ):
                    for stmt in child.body:
                        visit_stmt(stmt, inner_top, True)
                    for stmt in child.orelse:
                        visit_stmt(stmt, inner_top, typing_only)
                    continue
                visit_stmt(child, inner_top, inner_typing)

        def visit_stmt(child: ast.AST, top: bool, typing_only: bool) -> None:
            if isinstance(child, ast.Import):
                for alias in child.names:
                    items.append({"module": alias.name, "names": [], "top": top, "typing": typing_only})
            elif isinstance(child, ast.ImportFrom):
                if child.level:
                    base = package[: len(package) - (child.level - 1)] if child.level - 1 <= len(package) else None
                    if base is None:
                        return
                    module = ".".join([*base, *(child.module.split(".") if child.module else [])])
                else:
                    module = child.module or ""
                names = [a.name for a in child.names]
                items.append({"module": module, "names": names, "top": top, "typing": typing_only})
            else:
                visit(child, top, typing_only)

        visit(tree, True, False)
        found[rel] = items
    return found


def importers_of(imports: dict[str, list[dict]], target: str) -> set[str]:
    """哪些檔案 import 了 target 這個模組（任何形式）。"""
    parent, _, leaf = target.rpartition(".")
    hits = set()
    for rel, items in imports.items():
        for item in items:
            module = item["module"]
            if module == target or module.startswith(target + "."):
                hits.add(rel)
            elif module == parent and leaf in item["names"]:
                hits.add(rel)
    return hits


def top_level_importers(imports: dict[str, list[dict]], package: str) -> set[str]:
    return {
        rel
        for rel, items in imports.items()
        if any(i["module"] == package or i["module"].startswith(package + ".") for i in items)
    }


def independent_cycles(root: Path, roots: list[Path], imports: dict[str, list[dict]], deferred: bool) -> set[frozenset[str]]:
    """用獨立的 import 掃描另外算一次循環（Kosaraju）。"""
    by_module = {module_name(root, roots, p): p.relative_to(root).as_posix() for p in python_files(root)}
    by_module.pop(None, None)
    package_names: dict[str, set[str]] = {}

    def bound_in_init(rel: str) -> set[str]:
        if rel not in package_names:
            names: set[str] = set()
            try:
                tree = ast.parse((root / rel).read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                tree = ast.Module(body=[], type_ignores=[])
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.Assign):
                    names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
                elif isinstance(node, ast.ImportFrom):
                    names |= {a.asname or a.name for a in node.names}
                elif isinstance(node, ast.Import):
                    names |= {a.asname or a.name.split(".")[0] for a in node.names}
            package_names[rel] = names
        return package_names[rel]

    graph: dict[str, set[str]] = defaultdict(set)
    for rel, items in imports.items():
        for item in items:
            if item["typing"] or (not item["top"] and not deferred):
                continue
            module = item["module"]
            targets = set()
            if not item["names"]:
                if module in by_module:
                    targets.add(by_module[module])
            else:
                base = by_module.get(module)
                for name in item["names"]:
                    sub = by_module.get(f"{module}.{name}")
                    # __init__.py 自己綁定的名字優先於同名的子模組
                    if base and base.endswith("__init__.py") and name in bound_in_init(base):
                        targets.add(base)
                    elif sub:
                        targets.add(sub)
                    elif base:
                        targets.add(base)
            graph[rel] |= targets - {rel}
    nodes = set(graph) | {t for ts in graph.values() for t in ts}
    order, seen = [], set()
    for start in sorted(nodes):
        stack = [(start, iter(sorted(graph.get(start, ()))))]
        if start in seen:
            continue
        seen.add(start)
        while stack:
            node, it = stack[-1]
            nxt = next((t for t in it if t not in seen), None)
            if nxt is None:
                order.append(node)
                stack.pop()
            else:
                seen.add(nxt)
                stack.append((nxt, iter(sorted(graph.get(nxt, ())))))
    reverse: dict[str, set[str]] = defaultdict(set)
    for source, targets in graph.items():
        for target in targets:
            reverse[target].add(source)
    groups, assigned = set(), set()
    for start in reversed(order):
        if start in assigned:
            continue
        group, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node in assigned:
                continue
            assigned.add(node)
            group.add(node)
            stack.extend(reverse.get(node, ()))
        if len(group) > 1:
            groups.add(frozenset(group))
    return groups


SUBCLASS_PROBE = r"""
import importlib, json, pkgutil, sys, os, inspect
root, packages, base_module, base_name = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3], sys.argv[4]
failed = []
for package in packages:
    try:
        top = importlib.import_module(package)
    except Exception as error:
        failed.append(f"{package}: {type(error).__name__}")
        continue
    for info in pkgutil.walk_packages(getattr(top, "__path__", []), package + "."):
        try:
            importlib.import_module(info.name)
        except BaseException as error:
            failed.append(f"{info.name}: {type(error).__name__}")
base = getattr(importlib.import_module(base_module), base_name)
found, queue = {}, list(base.__subclasses__())
while queue:
    cls = queue.pop()
    key = f"{cls.__module__}.{cls.__qualname__}"
    if key in found:
        continue
    try:
        path = os.path.relpath(inspect.getsourcefile(cls), root)
    except Exception:
        path = "?"
    found[key] = {"file": path, "qualname": cls.__qualname__}
    queue.extend(cls.__subclasses__())
print(json.dumps({"subclasses": list(found.values()), "failed": failed, "is_protocol": bool(getattr(base, "_is_protocol", False))}))
"""


def runtime_subclasses(root: Path, python: str, paths: list[str], packages: list[str], module: str, name: str) -> dict:
    completed = subprocess.run(
        [python, "-c", SUBCLASS_PROBE, str(root), json.dumps(packages), module, name],
        cwd=root,
        env={"PYTHONPATH": ":".join(paths), "PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {"error": completed.stderr.strip()[-600:]}
    return json.loads(completed.stdout.strip().splitlines()[-1])


def name_callers(root: Path, function: str) -> set[str]:
    """用名字找直接呼叫者：哪些函式（或檔案層）的程式碼裡呼叫了這個名字。"""
    hits = set()
    for path in python_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        def walk(node: ast.AST, scope: list[str]) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    for decorator in child.decorator_list:
                        check(decorator, [*scope, child.name])
                    walk(child, [*scope, child.name])
                else:
                    check(child, scope)
                    walk(child, scope)

        def check(node: ast.AST, scope: list[str]) -> None:
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
                if called == function:
                    hits.add(f"{rel}::{'.'.join(scope)}" if scope else rel)

        walk(tree, [])
    return hits


def compare(title: str, ours: set[str], truth: set[str]) -> bool:
    same = ours == truth
    print(f"[{'一致' if same else '不一致'}] {title}：我們 {len(ours)}、獨立方法 {len(truth)}")
    for item in sorted(ours - truth):
        print(f"      只有我們有：{item}")
    for item in sorted(truth - ours):
        print(f"      只有獨立方法有：{item}")
    return same


def main() -> None:
    root, python, config = Path(sys.argv[1]).resolve(), sys.argv[2], json.loads(Path(sys.argv[3]).read_text())
    roots = [root / r for r in config["roots"]]
    graph = analyze(root, python=python, engine_check=False)
    index = Index(graph)
    imports = scan_imports(root, roots)
    results = []

    for check in config.get("module_importers", []):
        target_file = f"file:{check['file']}"
        ours = {e.source[5:] for e in graph.edges if e.type == "imports" and e.target == target_file}
        truth = importers_of(imports, check["module"])
        scope = tuple(check.get("under", [""]))
        results.append(
            compare(
                f"誰 import 了 {check['module']}",
                {f for f in ours if f.startswith(scope)},
                {f for f in truth if f.startswith(scope)},
            )
        )

    for check in config.get("package_importers", []):
        ours = {e.source[5:] for e in graph.edges if e.type == "imports" and e.target == f"ext:{check['package']}"}
        truth = top_level_importers(imports, check["package"])
        scope = tuple(check.get("under", [""]))
        node = index.nodes.get(f"ext:{check['package']}")
        print(f"      （{check['package']} 的分類：{node.properties if node else '圖上沒有這個節點'}）")
        results.append(
            compare(
                f"誰 import 了外部套件 {check['package']}",
                {f for f in ours if f.startswith(scope)},
                {f for f in truth if f.startswith(scope)},
            )
        )

    for deferred in (False, True):
        ours = {frozenset(g["files"]) for g in cycles(index, deferred)["components"]}
        truth = independent_cycles(root, roots, imports, deferred)
        scope = tuple(config.get("cycles_under", [""]))
        label = "含函式內的 import" if deferred else "只看檔案層的 import"
        results.append(
            compare(
                f"循環依賴（{label}）",
                {" + ".join(sorted(g)) for g in ours if all(f.startswith(scope) for f in g)},
                {" + ".join(sorted(g)) for g in truth if all(f.startswith(scope) for f in g)},
            )
        )

    for check in config.get("subclasses", []):
        base = f"class:{check['file']}::{check['class']}"
        found, queue = set(), [base]
        while queue:
            current = queue.pop()
            for edge in index.incoming(current, "inherits"):
                if edge.source not in found:
                    found.add(edge.source)
                    queue.append(edge.source)
        scope = tuple(check.get("under", [""]))
        ours = {s.split(":", 1)[1] for s in found if s.split(":", 1)[1].startswith(scope)}
        runtime = runtime_subclasses(
            root, python, [str(r) for r in roots], check["packages"], check["module"], check["class"]
        )
        if "error" in runtime:
            print(f"[無法驗證] {check['class']} 的子類別：執行時取得失敗 — {runtime['error']}")
            results.append(False)
            continue
        truth = {
            f"{c['file']}::{c['qualname'].replace('.<locals>', '')}"
            for c in runtime["subclasses"]
            if c["file"].startswith(scope)
        }
        if runtime["failed"]:
            print(f"      （執行時有 {len(runtime['failed'])} 個模組 import 失敗，不在真值裡：{runtime['failed'][:4]}）")
        print(f"      （{check['class']} 是 Protocol：{runtime['is_protocol']}）")
        results.append(compare(f"{check['class']} 的子類別（直接與間接）", ours, truth))

    for check in config.get("direct_callers", []):
        target = f"function:{check['file']}::{check['function']}"
        level = impact(index, target, max_depth=1)["levels"]
        ours = {e["id"].split(":", 1)[1] for e in (level[0] if level else []) if e["relation"].startswith("calls")}
        truth = name_callers(root, check["function"].split(".")[-1])
        scope = tuple(check.get("under", [""]))
        results.append(
            compare(
                f"直接呼叫 {check['function']} 的函式",
                {f for f in ours if f.startswith(scope)},
                {f for f in truth if f.startswith(scope)},
            )
        )
        full = impact(index, target)
        inside = [e for lv in full["levels"] for e in lv if e["id"].split(":", 1)[1].startswith(scope)]
        print(
            f"      （完整影響範圍：{len(full['levels'])} 層，範圍內 {len(inside)} 個，"
            f"其中確定 {sum(e['certainty'] == 'certain' for e in inside)}；候選 {len(full['candidates'])}）"
        )

    print(f"\n小計：{sum(results)}/{len(results)} 項一致")


if __name__ == "__main__":
    main()
