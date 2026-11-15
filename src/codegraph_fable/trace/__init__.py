"""執行時觀察：實際跑一個指令，記錄專案內真正發生的呼叫，用來量靜態分析漏了多少。

規格：docs/spec/trace.md。這會**執行被分析專案的程式碼**，所以只能由命令列明確啟動，
不透過 MCP 或網頁。
"""

from __future__ import annotations

import json
import os
import re
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


# 一組觀察到的呼叫，在圖上屬於哪一種。前四種影響範圍都查得到。
CATEGORIES = ("confirmed", "reference", "dispatch", "nested", "candidate", "test_double", "missing")


def _is_test(node_id: str) -> bool:
    parts = node_id.split(":", 1)[1].split("::")[0].split("/")
    return (
        any(p in ("tests", "test") for p in parts[:-1])
        or parts[-1].startswith("test_")
        or parts[-1] == "conftest.py"
    )


def compare(graph: Graph, observed: dict[str, Any]) -> dict[str, Any]:
    """觀察到的每一組呼叫，靜態分析的圖上有沒有。

    confirmed：有這條 calls 邊。
    reference：有 references 邊（讀 @property 這類「不寫括號卻會執行函式」的存取）。
    dispatch：呼叫者連到被呼叫者覆寫的祖先方法（含 Protocol）；影響範圍標為「可能」。
    nested：邊記在呼叫者裡面的定義上（裝飾器：執行的是外層，我們算在被裝飾者頭上）。
    candidate：呼叫者有一筆解不出的使用點提到這個名字；影響範圍列為「候選」。
    test_double：被呼叫的是測試檔裡的函式、呼叫者不是測試（測試注入的替身），不是程式本身的依賴。
    missing：圖上完全沒有。
    """
    index = Index(graph)
    mapper = _Mapper(index)
    calls = {(e.source, e.target) for e in graph.edges if e.type == "calls"}
    references = {(e.source, e.target) for e in graph.edges if e.type == "references"}
    static = calls | references
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

    def classify(source: str, target: str) -> str:
        if (source, target) in calls:
            return "confirmed"
        if (source, target) in references:
            return "reference"
        if any((source, base) in static for base in ancestors(target)):
            return "dispatch"
        if any((child, target) in static for child in index.children.get(source, [])):
            return "nested"
        if _is_test(target) and not _is_test(source):
            return "test_double"
        name = re.escape(index.nodes[target].label)
        unresolved = index.nodes[source].properties.get("unresolved_calls", [])
        if any(re.search(rf"\b{name}\b", item["text"]) for item in unresolved):
            return "candidate"
        return "missing"

    found: dict[str, list[dict[str, Any]]] = {name: [] for name in CATEGORIES}
    for (source, target), count in sorted(pairs.items()):
        found[classify(source, target)].append({"caller": source, "callee": target, "count": count})
    total = len(pairs)
    counts = {name: len(items) for name, items in found.items()}
    covered = counts["confirmed"] + counts["reference"] + counts["dispatch"] + counts["nested"]
    expected = total - counts["test_double"]  # 測試替身不是靜態分析該找到的

    def ratio(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    return {
        "command": observed.get("command"),
        "returncode": observed.get("returncode"),
        "observed": total,
        **counts,
        "unmapped": unmapped,
        # 最嚴格：只算 calls 邊，分母是全部
        "recall": ratio(counts["confirmed"], total),
        # 影響範圍查得到的（確定或可能），分母不含測試替身
        "coverage": ratio(covered, expected),
        # 再加上列為候選的
        "coverage_with_candidates": ratio(covered + counts["candidate"], expected),
        "missing_calls": found["missing"],
        "candidate_calls": found["candidate"],
        "dispatch_calls": found["dispatch"],
    }


def merge(graph: Graph, observed: dict[str, Any]) -> dict[str, Any]:
    """把靜態分析沒連上、但執行時觀察到的呼叫加進圖：另成一類 `observed_calls`，不與靜態的混在一起。

    加的是 missing 與 candidate（程式本身真的發生的呼叫）；測試替身不加。
    """
    report = compare(graph, observed)
    for kind in ("missing_calls", "candidate_calls"):
        for item in report[kind]:
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
