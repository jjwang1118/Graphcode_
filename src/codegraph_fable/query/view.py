"""畫面要顯示的子圖：依層級與展開狀態收合，線往上加總。規格：docs/spec/web.md（W-V）"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..model import REPO_ID
from .index import Index

EDGE_TYPES = ("imports", "calls", "inherits", "references")
GROUP = "extgroup:"  # 外部套件依類別合成的虛擬節點
_GROUP_LABELS = {
    "stdlib": "標準庫",
    "third_party": "第三方套件",
    "unknown": "未知的外部",
    "excluded": "被排除的本地",
}
_NODE_PROPS = ("line", "end_line", "signature", "category", "language", "parse_error", "installed")


class _View:
    def __init__(
        self,
        index: Index,
        expanded: set[str],
        externals: str,
        level: int | None,
        collapsed: set[str],
    ) -> None:
        self.index = index
        # 層級決定預設展開到哪裡；使用者個別展開／收合的再疊上去
        if level is None:
            base = {n for n, children in index.children.items() if children}
        else:
            base = {REPO_ID} if level >= 1 else set()
            base |= {
                n.id
                for n in index.graph.nodes
                if n.type == "directory" and n.id.count("/") + 1 < level
            }
        self.expanded = (base | set(expanded)) - set(collapsed)
        self.parent: dict[str, str] = {}  # 畫面上的上一層（含虛擬的外部群組）
        self.visible: list[str] = [REPO_ID]
        self._rep: dict[str, str | None] = {}
        self.groups: dict[str, list[str]] = defaultdict(list)
        for node in index.graph.nodes:
            if node.type == "external_package":
                self.groups[GROUP + node.properties["category"]].append(node.id)
        if REPO_ID in self.expanded:
            self._walk(REPO_ID)
        if externals == "full":
            self.visible += sorted(m for members in self.groups.values() for m in members)
        elif externals != "hidden":
            for group, members in sorted(self.groups.items()):
                self.visible.append(group)
                if group in self.expanded:
                    for member in sorted(members):
                        self.visible.append(member)
                        self.parent[member] = group
        self._visible = set(self.visible)

    def _walk(self, node_id: str) -> None:
        for child in self.index.children.get(node_id, []):
            self.visible.append(child)
            self.parent[child] = node_id
            if child in self.expanded:
                self._walk(child)

    def rep(self, node_id: str) -> str | None:
        """這個節點在畫面上由誰代表：自己，或最近一個看得見的上層。"""
        if node_id in self._rep:
            return self._rep[node_id]
        result: str | None
        if node_id in self._visible:
            result = node_id
        elif node_id.startswith("ext:"):
            node = self.index.nodes.get(node_id)
            group = GROUP + node.properties["category"] if node else None
            result = group if group in self._visible else None
        else:
            parent = self.index.parent.get(node_id)
            result = self.rep(parent) if parent else None
        self._rep[node_id] = result
        return result

    def related(self, a: str, b: str) -> bool:
        """a 與 b 是否為畫面上的上下層（它們之間已經有骨架線）。"""
        for inner, outer in ((a, b), (b, a)):
            current = self.parent.get(inner)
            while current:
                if current == outer:
                    return True
                current = self.parent.get(current)
        return False


def view(
    index: Index,
    expanded: set[str] | list[str] = (),
    edge_types: tuple[str, ...] | list[str] = EDGE_TYPES,
    externals: str = "grouped",
    level: int | None = 1,
    collapsed: set[str] | list[str] = (),
) -> dict[str, Any]:
    """level：0＝只有專案根、n＝到第 n 層目錄、None＝不收合。
    externals：grouped（依類別合成一個節點，可展開）／full（每個套件一個節點）／hidden。
    """
    state = _View(index, set(expanded), externals, level, set(collapsed))
    nodes = []
    for node_id in state.visible:
        if node_id.startswith(GROUP):
            members = state.groups[node_id]
            entry: dict[str, Any] = {
                "id": node_id,
                "type": "external_group",
                "label": f"{_GROUP_LABELS.get(node_id[len(GROUP) :], node_id)}（{len(members)}）",
                "children": len(members),
            }
        else:
            node = index.nodes[node_id]
            entry = {
                "id": node_id,
                "type": node.type,
                "label": node.label,
                "children": len(index.children.get(node_id, [])),
                **{k: node.properties[k] for k in _NODE_PROPS if k in node.properties},
            }
            unresolved = len(node.properties.get("unresolved_calls", []))
            if unresolved:
                entry["unresolved_calls"] = unresolved
        entry["expanded"] = entry["children"] > 0 and node_id in state.expanded
        if node_id in state.parent:
            entry["parent"] = state.parent[node_id]
        nodes.append(entry)

    # 骨架：看得見的節點與它看得見的上一層
    edges = []
    for child, parent in state.parent.items():
        kind = "contains" if parent.split(":")[0] in ("repo", "dir", "extgroup") else "defines"
        edges.append(
            {
                "id": f"{kind}:{parent}→{child}",
                "source": parent,
                "target": child,
                "type": kind,
                "count": 1,
            }
        )
    merged: dict[tuple[str, str, str], int] = defaultdict(int)
    for edge in index.graph.edges:
        if edge.type not in edge_types:
            continue
        source, target = state.rep(edge.source), state.rep(edge.target)
        if source is None or target is None or source == target or state.related(source, target):
            continue
        merged[(edge.type, source, target)] += edge.properties.get("count", 1)
    for (kind, source, target), count in merged.items():
        edges.append(
            {
                "id": f"{kind}:{source}→{target}",
                "source": source,
                "target": target,
                "type": kind,
                "count": count,
            }
        )
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "visible_nodes": len(nodes),
            "visible_edges": len(edges),
            "total_nodes": len(index.graph.nodes),
            "total_edges": len(index.graph.edges),
        },
    }


def locate(
    index: Index,
    expanded: set[str] | list[str],
    ids: list[str],
    externals: str = "grouped",
    level: int | None = 1,
    collapsed: set[str] | list[str] = (),
) -> dict[str, str | None]:
    """一批節點各自在目前畫面上由誰代表（看不見的回 None）。"""
    state = _View(index, set(expanded), externals, level, set(collapsed))
    return {node_id: state.rep(node_id) for node_id in ids}
