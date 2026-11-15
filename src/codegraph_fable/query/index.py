"""查詢用的索引：把圖整理成「誰連到誰」。規格：docs/spec/query.md"""

from __future__ import annotations

from collections import defaultdict

from ..model import Edge, Graph, Node


def owner_file(node_id: str) -> str | None:
    """節點屬於哪個檔案（相對路徑）；不是檔案或檔案內的定義就回 None。"""
    kind, _, rest = node_id.partition(":")
    if kind == "file":
        return rest
    if kind in ("class", "function", "variable"):
        return rest.split("::")[0]
    return None


class Index:
    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.nodes: dict[str, Node] = {n.id: n for n in graph.nodes}
        self._out: dict[tuple[str, str], list[Edge]] = defaultdict(list)
        self._in: dict[tuple[str, str], list[Edge]] = defaultdict(list)
        self.parent: dict[str, str] = {}  # 包含關係（contains／defines）的上一層
        self.children: dict[str, list[str]] = defaultdict(list)
        for edge in graph.edges:
            self._out[(edge.source, edge.type)].append(edge)
            self._in[(edge.target, edge.type)].append(edge)
            if edge.type in ("contains", "defines"):
                self.parent[edge.target] = edge.source
                self.children[edge.source].append(edge.target)

    def outgoing(self, node_id: str, *types: str) -> list[Edge]:
        return [e for t in types for e in self._out.get((node_id, t), [])]

    def incoming(self, node_id: str, *types: str) -> list[Edge]:
        return [e for t in types for e in self._in.get((node_id, t), [])]

    def descendants(self, node_id: str) -> list[str]:
        """這個節點裡面定義的所有東西（沿 defines 往下）。"""
        found, queue = [], [node_id]
        while queue:
            for edge in self.outgoing(queue.pop(), "defines"):
                found.append(edge.target)
                queue.append(edge.target)
        return found

    def ancestors(self, node_id: str) -> list[str]:
        """由近到遠的上層節點（不含自己）。"""
        found = []
        while node_id in self.parent:
            node_id = self.parent[node_id]
            found.append(node_id)
        return found

    def find(self, name: str) -> list[Node]:
        """依名字找定義：完整 id、`檔案::名字`、`類別.方法`、或單純的名字。"""
        if name in self.nodes:
            return [self.nodes[name]]
        hits = []
        for node in self.graph.nodes:
            if node.type not in ("class", "function", "variable", "file"):
                continue
            tail = node.id.split(":", 1)[1]
            qualname = tail.split("::")[-1]
            if name in (node.label, tail, qualname) or qualname.endswith("." + name):
                hits.append(node)
        return hits
