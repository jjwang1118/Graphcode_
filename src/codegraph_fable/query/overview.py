"""專案概覽與檔案層的依賴。規格：docs/spec/query.md"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .index import Index, owner_file

_USE_EDGES = ("calls", "references", "inherits")


def file_dependencies(index: Index) -> dict[tuple[str, str], dict[str, int]]:
    """檔案 → 檔案的依賴，兩種來源分開數（F7）：import 敘述、實際使用的加總。"""
    found: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"imports": 0, "uses": 0})
    for edge in index.graph.edges:
        if edge.type != "imports" and edge.type not in _USE_EDGES:
            continue
        source, target = owner_file(edge.source), owner_file(edge.target)
        if source is None or target is None or source == target:
            continue
        kind = "imports" if edge.type == "imports" else "uses"
        found[(source, target)][kind] += edge.properties.get("count", 1)
    return dict(found)


def overview(index: Index, top: int = 10) -> dict[str, Any]:
    graph = index.graph
    meta = graph.meta
    python_files = [n for n in graph.nodes if n.type == "file" and n.properties.get("language")]
    packages = Counter(n.id[5:].split("/")[0] if "/" in n.id else "(根目錄)" for n in python_files)
    externals: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        if node.type == "external_package":
            externals[node.properties["category"]].append(node.label)
    dependents: dict[str, set[str]] = defaultdict(set)
    for (source, target), _counts in file_dependencies(index).items():
        dependents[target].add(source)
    most_used = sorted(dependents.items(), key=lambda item: (-len(item[1]), item[0]))[:top]
    uses = meta.get("uses", {})
    return {
        "root": meta.get("root"),
        "search_roots": meta.get("search_roots", []),
        "counts": meta.get("counts", {}),
        "packages": dict(sorted(packages.items(), key=lambda item: (-item[1], item[0]))),
        "externals": {k: sorted(v) for k, v in sorted(externals.items())},
        "entry_points": sorted(
            n.id[5:] for n in python_files if n.properties.get("has_main_guard")
        ),
        "most_used_files": [{"file": f, "dependents": len(d)} for f, d in most_used],
        "completeness": {
            "parse_errors": len(meta.get("parse_errors", [])),
            "unresolved_imports": len(meta.get("unresolved_imports", [])),
            "missing_dependencies": meta.get("missing_dependencies", []),
            "calls": uses.get("calls"),
            "uses_available": uses.get("available", False),
        },
    }
