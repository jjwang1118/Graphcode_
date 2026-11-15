"""循環依賴：哪些檔案互相 import。規格：docs/spec/query.md（Q-C）"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .index import Index


def _file_graph(index: Index, deferred: bool) -> dict[str, dict[str, list[int]]]:
    """檔案 → 檔案的 import（值是行號）。只算執行時真的會發生的。"""
    graph: dict[str, dict[str, list[int]]] = defaultdict(dict)
    for edge in index.graph.edges:
        props = edge.properties
        if edge.type != "imports" or not edge.target.startswith("file:"):
            continue
        if props.get("type_checking"):
            continue  # 只給型別檢查用，執行時不會 import
        if props.get("scope") != "module" and not deferred:
            continue  # 寫在函式裡的 import 要等函式被呼叫才發生
        if edge.source != edge.target:
            graph[edge.source].setdefault(edge.target, []).append(props["line"])
    return graph


def _components(graph: dict[str, dict[str, list[int]]]) -> list[list[str]]:
    """互相到得了的檔案群（強連通分量），只留兩個檔案以上的。Tarjan，不用遞迴。"""
    order: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    found: list[list[str]] = []
    nodes = sorted(set(graph) | {t for targets in graph.values() for t in targets})
    for root in nodes:
        if root in order:
            continue
        work = [(root, iter(sorted(graph.get(root, {}))))]
        order[root] = low[root] = len(order)
        stack.append(root)
        on_stack.add(root)
        while work:
            node, targets = work[-1]
            advanced = False
            for target in targets:
                if target not in order:
                    order[target] = low[target] = len(order)
                    stack.append(target)
                    on_stack.add(target)
                    work.append((target, iter(sorted(graph.get(target, {})))))
                    advanced = True
                    break
                if target in on_stack:
                    low[node] = min(low[node], order[target])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == order[node]:
                group = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.append(member)
                    if member == node:
                        break
                if len(group) > 1:
                    found.append(sorted(group))
    return sorted(found, key=lambda group: (-len(group), group))


def _example(graph: dict[str, dict[str, list[int]]], group: list[str]) -> list[str]:
    """這一群裡最短的一圈，從第一個檔案出發再回到它。"""
    start, members = group[0], set(group)
    previous: dict[str, str] = {}
    queue = [start]
    while queue:
        node = queue.pop(0)
        for target in sorted(graph.get(node, {})):
            if target == start:
                path = [node]
                while path[-1] != start:
                    path.append(previous[path[-1]])
                return [*reversed(path), start]
            if target in members and target not in previous:
                previous[target] = node
                queue.append(target)
    return [start]


def cycles(index: Index, deferred: bool = False) -> dict[str, Any]:
    """deferred=False：只看寫在檔案層的 import（一 import 就會發生）。
    deferred=True：連寫在函式裡的 import 也算（呼叫到才發生）。
    """
    graph = _file_graph(index, deferred)
    components = []
    for group in _components(graph):
        path = _example(graph, group)
        components.append(
            {
                "files": [f[5:] for f in group],
                "size": len(group),
                "example": [f[5:] for f in path],
                "edges": [
                    {"source": a[5:], "target": b[5:], "lines": graph[a][b]}
                    for a, b in zip(path, path[1:], strict=False)
                ],
            }
        )
    return {"deferred": deferred, "count": len(components), "components": components}
