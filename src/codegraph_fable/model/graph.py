"""圖的資料格式。規格：docs/spec/model.md"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1


class GraphError(ValueError):
    """圖不合法：id 重複，或邊指向不存在的節點。"""


@dataclass
class Node:
    id: str
    type: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    target: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        ids: set[str] = set()
        for node in self.nodes:
            if node.id in ids:
                raise GraphError(f"節點 id 重複：{node.id}")
            ids.add(node.id)
        for edge in self.edges:
            for end in (edge.source, edge.target):
                if end not in ids:
                    raise GraphError(
                        f"邊 {edge.type} {edge.source} -> {edge.target} 指向不存在的節點：{end}"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [asdict(n) for n in self.nodes],
            "edges": [asdict(e) for e in self.edges],
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Graph:
        graph = cls(
            nodes=[Node(**n) for n in data["nodes"]],
            edges=[Edge(**e) for e in data["edges"]],
            meta=data.get("meta", {}),
        )
        graph.validate()
        return graph
