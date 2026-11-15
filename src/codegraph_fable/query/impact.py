"""影響範圍：改這個東西，誰會受影響。規格：docs/spec/query.md"""

from __future__ import annotations

import re
from typing import Any

from .index import Index

_USE_EDGES = ("calls", "references", "inherits")
_NO_DISPATCH = {"__init__", "__new__"}  # 建構時指定了確切的類別，不會分派到子類別


def _dependents(index: Index, node_id: str) -> list[dict[str, Any]]:
    """直接依賴 node_id 的節點，每筆帶關係與確定程度。"""
    found = []
    for edge in index.incoming(node_id, *_USE_EDGES):
        props = edge.properties
        uncertain = props.get("ambiguous") or props.get("evidence") == "import"
        relation = edge.type if not props.get("via") else f"{edge.type}:{props['via']}"
        found.append(
            {
                "id": edge.source,
                "relation": relation,
                "certainty": "possible" if uncertain else "certain",
                "lines": props.get("lines", []),
                "through": node_id,
            }
        )
    for edge in index.incoming(node_id, "imports"):
        found.append(
            {
                "id": edge.source,
                "relation": "imports",
                "certainty": "certain",
                "lines": [edge.properties["line"]],
                "through": node_id,
            }
        )
    # 動態分派：呼叫祖先的同名方法的人，執行時可能呼叫到這個覆寫
    node = index.nodes[node_id]
    if node.type == "function" and node.label not in _NO_DISPATCH:
        ancestors, queue = [], [node_id]
        while queue:
            for edge in index.outgoing(queue.pop(), "overrides"):
                if edge.target not in ancestors:
                    ancestors.append(edge.target)
                    queue.append(edge.target)
        for ancestor in ancestors:
            for edge in index.incoming(ancestor, "calls", "references"):
                found.append(
                    {
                        "id": edge.source,
                        "relation": "dispatch",
                        "certainty": "possible",
                        "lines": edge.properties.get("lines", []),
                        "through": ancestor,
                    }
                )
    return found


def _candidates(index: Index, names: set[str], known: set[str]) -> list[dict[str, Any]]:
    """解不出的呼叫裡，寫法提到了目標名字的：可能是呼叫者，無法確認。"""
    if not names:
        return []
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names)) + r")\b")
    found = []
    for node in index.graph.nodes:
        for item in node.properties.get("unresolved_calls", []):
            if pattern.search(item["text"]):
                found.append(
                    {
                        "id": node.id,
                        "line": item["line"],
                        "text": item["text"],
                        "reason": item["reason"],
                        "already_listed": node.id in known,
                    }
                )
    return found


def impact(index: Index, target: str, max_depth: int | None = None) -> dict[str, Any]:
    """改 target 會影響誰，一層一層往外。

    levels[0] 是直接使用者，levels[1] 是使用者的使用者，依此類推。
    certainty：certain（引擎解到確切定義）／possible（多個可能、經動態分派、或上游就不確定）。
    """
    if target not in index.nodes:
        raise KeyError(target)
    scope = [target, *index.descendants(target)]  # 改一個檔案或 class ＝ 改它裡面的全部
    seen: dict[str, str] = dict.fromkeys(scope, "certain")
    levels: list[list[dict[str, Any]]] = []
    frontier = scope
    while frontier and (max_depth is None or len(levels) < max_depth):
        found: dict[str, dict[str, Any]] = {}
        for node_id in frontier:
            for entry in _dependents(index, node_id):
                if entry["id"] in seen:
                    continue
                if seen[node_id] == "possible":
                    entry["certainty"] = "possible"  # 上游不確定，下游也不確定
                current = found.get(entry["id"])
                if current is None or (
                    current["certainty"] == "possible" and entry["certainty"] == "certain"
                ):
                    found[entry["id"]] = entry
        if not found:
            break
        for node_id, entry in found.items():
            seen[node_id] = entry["certainty"]
        levels.append(sorted(found.values(), key=lambda e: e["id"]))
        frontier = list(found)

    names = {
        index.nodes[n].label
        for n in scope
        if index.nodes[n].type in ("function", "class") and index.nodes[n].label not in _NO_DISPATCH
    }
    affected = set(seen) - set(scope)
    candidates = _candidates(index, names, affected)
    uses = index.graph.meta.get("uses", {})
    return {
        "target": target,
        "scope": scope,
        "levels": levels,
        "overridden_by": sorted(e.source for n in scope for e in index.incoming(n, "overrides")),
        "candidates": candidates,
        "completeness": {
            "affected": len(affected),
            "certain": sum(1 for n in affected if seen[n] == "certain"),
            "possible": sum(1 for n in affected if seen[n] == "possible"),
            "candidates": len(candidates),
            "unresolved_calls_in_project": uses.get("calls", {}).get("unresolved"),
            "uses_available": uses.get("available", False),
        },
    }
