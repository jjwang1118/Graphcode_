"""分析入口：專案目錄 → 一張圖。規格：docs/spec/analyze.md"""

from __future__ import annotations

import os
import sys
import tokenize
from collections import Counter
from pathlib import Path
from typing import Any

from ..model import REPO_ID, SCHEMA_VERSION, Edge, Graph, Node, decl_id, dir_id, ext_id, file_id
from .calls import resolve_uses
from .definitions import FileFacts, extract
from .imports import ImportResult, resolve_imports
from .roots import declared_dependencies, default_roots
from .scan import fingerprint, scan


def _read(path: Path) -> FileFacts:
    try:
        with tokenize.open(path) as handle:
            return extract(handle.read())
    except (OSError, SyntaxError, UnicodeDecodeError) as error:
        return FileFacts(parse_error=f"{type(error).__name__}: {error}")


def _parent_id(rel: str) -> str:
    parent = Path(rel).parent.as_posix()
    return REPO_ID if parent == "." else dir_id(parent)


def _engine_check(
    engine: Any, imports: ImportResult
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """F2：用 Jedi 再解一次每個絕對 import 的模組，與 Python 自己的查找結果比對。"""
    verdicts: dict[str, str] = {}
    disagreements = []
    for name, (expectation, origin) in sorted(imports.checks.items()):
        verdict = "unchecked"
        found: list[str] = []
        if expectation != "skip":
            try:
                found = engine.module_paths(name)
            except Exception:
                expectation = "skip"
        python_files = [p for p in found if p.endswith(".py")]
        if expectation == "missing":
            verdict = "disagree" if python_files else "agree"
        elif expectation == "found" and origin and origin.endswith(".py"):
            if os.path.realpath(origin) in {os.path.realpath(p) for p in found}:
                verdict = "agree"
            elif python_files:
                verdict = "disagree"
        verdicts[name] = verdict
        if verdict == "disagree":
            disagreements.append({"module": name, "python": origin, "engine": found})
    for edge, module in zip(imports.edges, imports.edge_modules, strict=True):
        if module and verdicts.get(module) == "disagree":
            edge.properties["engine_check"] = "disagree"
    counts = Counter(verdicts.values())
    summary = {
        "name": "jedi",
        "available": True,
        "version": engine.version,
        "agree": counts["agree"],
        "disagree": counts["disagree"],
        "unchecked": counts["unchecked"],
    }
    return summary, disagreements


def analyze(
    root: str | Path,
    *,
    roots: list[str | Path] | None = None,
    python: str | None = None,
    extra_paths: list[str | Path] | None = None,
    engine_check: bool = True,
    resolve_uses_: bool = True,
) -> Graph:
    """分析一個 Python 專案。

    roots：搜尋根目錄（預設：專案根，加上 `src/`）。
    python：專案環境的 Python 執行檔（預設：執行本工具的 Python）。
    extra_paths：額外的套件安裝目錄，排在環境路徑之後。
    engine_check：是否用 Jedi 核對 import。
    resolve_uses_：是否解析呼叫、繼承、引用（需要 Jedi）。
    """
    scanned = scan(root)
    project = scanned.root
    search_roots = [Path(r).resolve() for r in roots] if roots else default_roots(project)
    python = python or sys.executable
    extras = [str(Path(p).resolve()) for p in (extra_paths or [])]

    graph = Graph()
    graph.nodes.append(Node(REPO_ID, "repo", project.name))
    for rel in scanned.dirs:
        graph.nodes.append(Node(dir_id(rel), "directory", Path(rel).name))
        graph.edges.append(Edge(_parent_id(rel), dir_id(rel), "contains"))

    facts: dict[str, FileFacts] = {rel: _read(project / rel) for rel in scanned.python_files}
    parse_errors = []
    for rel in scanned.files:
        props: dict[str, Any] = {}
        if rel in facts:
            props["language"] = "python"
            if facts[rel].parse_error:
                props["parse_error"] = facts[rel].parse_error
                parse_errors.append({"file": rel, "error": facts[rel].parse_error})
            if facts[rel].has_main_guard:
                props["has_main_guard"] = True
        graph.nodes.append(Node(file_id(rel), "file", Path(rel).name, props))
        graph.edges.append(Edge(_parent_id(rel), file_id(rel), "contains"))

    for rel, file_facts in facts.items():
        ids: dict[str, str] = {}
        for definition in file_facts.definitions:
            node_id = decl_id(definition.kind, rel, definition.qualname)
            ids[definition.qualname] = node_id
            props = {
                "line": definition.line,
                "end_line": definition.end_line,
                **definition.properties,
            }
            graph.nodes.append(Node(node_id, definition.kind, definition.name, props))
            owner = ids[definition.parent] if definition.parent else file_id(rel)
            graph.edges.append(Edge(owner, node_id, "defines"))

    imports = resolve_imports(
        scanned, search_roots, facts, declared_dependencies(project), python, extras
    )
    graph.nodes.extend(imports.ext_nodes.values())
    graph.edges.extend(imports.edges)

    env = imports.env
    engine_meta: dict[str, Any] = {"name": "jedi", "available": False, "error": "已停用"}
    disagreements: list[dict[str, Any]] = []
    uses_meta: dict[str, Any] = {"available": False, "error": "已停用"}
    engine = None
    if engine_check or resolve_uses_:
        try:
            from .engine import Engine

            sys_path = [str(r) for r in search_roots] + env["env_paths"]
            engine = Engine(project, python, sys_path)
        except Exception as error:  # Jedi 不可用不該讓分析失敗
            message = f"{type(error).__name__}: {error}"
            engine_meta = {"name": "jedi", "available": False, "error": message}
            uses_meta = {"available": False, "error": message}
    if engine is not None and engine_check:
        engine_meta, disagreements = _engine_check(engine, imports)
    if engine is not None and resolve_uses_:
        known = {n.id for n in graph.nodes}
        stdlib = set(env["stdlib_names"]) | set(env["builtin_names"])

        def ensure_ext(top: str) -> str:
            # 呼叫或繼承指到一個沒被 import 敘述帶進圖的外部模組（例如 builtins）
            node_id = ext_id(top)
            if node_id not in known:
                category = "stdlib" if top in stdlib else "third_party"
                graph.nodes.append(
                    Node(
                        node_id, "external_package", top, {"category": category, "installed": True}
                    )
                )
                known.add(node_id)
            return node_id

        # 檔案層 import 自外部套件的名字：引擎解不出時（套件沒安裝）的退路
        external = {
            (e.source, e.properties["module"]): e.target
            for e in imports.edges
            if e.target.startswith("ext:")
        }
        bindings: dict[str, dict[str, tuple[str, str]]] = {}
        for rel, file_facts in facts.items():
            for stmt in file_facts.imports:
                target = external.get((file_id(rel), stmt.module or ""))
                if target is None or stmt.level or stmt.scope != "module" or stmt.name == "*":
                    continue
                assert stmt.module is not None
                if stmt.name is None:
                    bound = stmt.asname or stmt.module.split(".")[0]
                    full = stmt.module if stmt.asname else bound
                else:
                    bound, full = stmt.asname or stmt.name, f"{stmt.module}.{stmt.name}"
                bindings.setdefault(rel, {})[bound] = (target, full)

        uses = resolve_uses(project, facts, engine, ensure_ext, bindings)
        graph.edges.extend(uses.edges)
        by_id = {n.id: n for n in graph.nodes}
        for node_id, extra in uses.node_props.items():
            by_id[node_id].properties.update(extra)
        uses_meta = {
            "available": True,
            "calls": uses.calls,
            "inherits": uses.inherits,
            "references": uses.references,
            "overrides": uses.overrides,
        }

    graph.meta = {
        "schema_version": SCHEMA_VERSION,
        "root": str(project),
        "fingerprint": fingerprint(scanned),
        "options": {
            "python": python,
            "roots": [str(r) for r in search_roots] if roots else None,
            "extra_paths": extras,
        },
        "search_roots": [os.path.relpath(r, project) for r in search_roots],
        "python": {"executable": env["executable"], "version": env["version"]},
        "env_paths": env["env_paths"],
        "counts": {
            "nodes": dict(Counter(n.type for n in graph.nodes)),
            "edges": dict(Counter(e.type for e in graph.edges)),
        },
        "imports": imports.stats,
        "unresolved_imports": imports.unresolved,
        "missing_dependencies": imports.missing_dependencies,
        "parse_errors": parse_errors,
        "engine": engine_meta,
        "uses": uses_meta,
        "engine_disagreements": disagreements,
    }
    graph.validate()
    return graph
