"""分析結果的存檔與讀取（JSON 檔）。規格：docs/spec/model.md"""

from __future__ import annotations

import json
from pathlib import Path

from ..model import Graph


def save(graph: Graph, path: str | Path) -> None:
    graph.validate()
    Path(path).write_text(
        json.dumps(graph.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load(path: str | Path) -> Graph:
    return Graph.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


__all__ = ["load", "save"]
