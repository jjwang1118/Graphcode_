"""執行時觀察：實際跑一個指令，記錄專案內真正發生的呼叫，用來量靜態分析漏了多少。

規格：docs/spec/trace.md。這會**執行被分析專案的程式碼**，所以只能由命令列明確啟動，
不透過 MCP 或網頁。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..model import Edge, Graph, file_id
from ..query import Index

_TRACER = Path(__file__).with_name("tracer.py")


def record(project: str | Path, command: list[str], python: str | None = None) -> dict[str, Any]:
    """在專案資料夾裡用指定的 Python 跑 command（例：["-m", "pytest", "-q"]），回傳觀察結果。"""
    root = Path(project).resolve()
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "observed.json"
        completed = subprocess.run(
            [
                python or sys.executable,
                str(_TRACER),
                "--root",
                str(root),
                "--out",
                str(out),
                *command,
            ],
            cwd=root,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},  # 不在專案裡留 __pycache__
            capture_output=True,
            text=True,
            check=False,
        )
        if not out.is_file():
            raise RuntimeError(f"沒有產生觀察結果：{completed.stderr.strip()[-2000:]}")
        observed = json.loads(out.read_text(encoding="utf-8"))
    observed["returncode"] = completed.returncode
    observed["output_tail"] = (completed.stdout + completed.stderr)[-1500:]
    return observed


class _Mapper:
    """觀察到的 (檔案, 名字, 行號) → 圖上的節點 id。"""

    def __init__(self, index: Index) -> None:
        self.index = index
        self.by_file: dict[str, list[Any]] = {}
        for node in index.graph.nodes:
            if node.type in ("class", "function"):
                rel = node.id.split(":", 1)[1].split("::")[0]
                self.by_file.setdefault(rel, []).append(node)

    def node(self, item: dict[str, Any]) -> str | None:
        rel = item["file"]
        if file_id(rel) not in self.index.nodes:
            return None
        if item["name"] == "<module>":
            return file_id(rel)
        if item["qualname"]:
            # `outer.<locals>.inner` → `outer.inner`；結尾的 <lambda>、<listcomp> 算在外層頭上
            parts = [p for p in item["qualname"].split(".") if p != "<locals>"]
            while parts and parts[-1].startswith("<"):
                parts.pop()
            if not parts:
                return file_id(rel)
            qualname = ".".join(parts)
            for kind in ("function", "class"):
                node_id = f"{kind}:{rel}::{qualname}"
                if node_id in self.index.nodes:
                    return node_id
        if item["name"].startswith("<"):
            return None
        # 沒有完整名字（舊版 Python）或同名重複定義：同名、定義行在觀察到的行號之後最近的那個
        named = [n for n in self.by_file.get(rel, []) if n.label == item["name"]]
        after = [n for n in named if n.properties["line"] >= item["line"]]
        best = min(after, key=lambda n: n.properties["line"]) if after else None
        return best.id if best else None


def compare(graph: Graph, observed: dict[str, Any]) -> dict[str, Any]:
    """觀察到的呼叫，靜態分析有沒有。回傳統計與漏掉的清單。

    confirmed：圖上有這條 calls 邊。
    dispatch：圖上沒有這條邊，但呼叫者有一條邊指向被呼叫者覆寫的祖先方法（影響範圍查得到，標為「可能」）。
    missing：靜態分析漏掉的。
    """
    index = Index(graph)
    mapper = _Mapper(index)
    static = {(e.source, e.target) for e in graph.edges if e.type == "calls"}
    pairs: dict[tuple[str, str], int] = {}
    unmapped = 0
    for pair in observed["pairs"]:
        if pair["callee"]["name"] == "<module>":
            continue  # 這是 import 執行了模組，不是呼叫
        source, target = mapper.node(pair["caller"]), mapper.node(pair["callee"])
        if source is None or target is None:
            unmapped += 1
            continue
        if target.startswith("class:"):
            continue  # class 本體在定義時執行，不是呼叫
        if source == target and pair["callee"]["name"].startswith("<"):
            continue  # 函式裡的產生器運算式、lambda 是它自己的一部分，不是「自己呼叫自己」
        pairs[(source, target)] = pairs.get((source, target), 0) + pair["count"]

    def ancestors(method: str) -> set[str]:
        found, queue = set(), [method]
        while queue:
            for edge in index.outgoing(queue.pop(), "overrides"):
                if edge.target not in found:
                    found.add(edge.target)
                    queue.append(edge.target)
        return found

    confirmed, dispatch, missing = [], [], []
    for (source, target), count in sorted(pairs.items()):
        item = {"caller": source, "callee": target, "count": count}
        if (source, target) in static:
            confirmed.append(item)
        elif any((source, base) in static for base in ancestors(target)):
            dispatch.append(item)
        else:
            missing.append(item)
    total = len(pairs)
    return {
        "command": observed.get("command"),
        "returncode": observed.get("returncode"),
        "observed": total,
        "confirmed": len(confirmed),
        "dispatch": len(dispatch),
        "missing": len(missing),
        "unmapped": unmapped,
        "recall": round(len(confirmed) / total, 4) if total else None,
        "recall_with_dispatch": round((len(confirmed) + len(dispatch)) / total, 4)
        if total
        else None,
        "missing_calls": missing,
        "dispatch_calls": dispatch,
    }


def merge(graph: Graph, observed: dict[str, Any]) -> dict[str, Any]:
    """把靜態分析漏掉、但執行時觀察到的呼叫加進圖：另成一類 `observed_calls`，不與靜態的混在一起。"""
    report = compare(graph, observed)
    for item in report["missing_calls"]:
        graph.edges.append(
            Edge(
                item["caller"],
                item["callee"],
                "observed_calls",
                {"count": item["count"], "evidence": "runtime"},
            )
        )
    graph.meta["runtime"] = {k: v for k, v in report.items() if not k.endswith("_calls")}
    graph.validate()
    return report


__all__ = ["compare", "merge", "record"]
