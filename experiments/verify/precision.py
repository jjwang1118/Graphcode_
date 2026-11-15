"""假邊的粗篩：每條專案內的 calls 邊，回原始碼看那一行有沒有出現被呼叫者的名字。

沒出現不一定是錯（別名、`fn = helper; fn()`、解構指派），但錯的邊幾乎都會落在這裡，
所以把它們列出來人工看。一次性的驗證腳本。
用法：python precision.py <專案根> <專案環境的 python>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from codegraph_fable.analyze import analyze
from codegraph_fable.query import Index, owner_file


def main() -> None:
    root, python = Path(sys.argv[1]).resolve(), sys.argv[2]
    graph = analyze(root, python=python, engine_check=False)
    index = Index(graph)
    sources: dict[str, list[str]] = {}
    total = suspicious = 0
    shown = []
    for edge in graph.edges:
        if edge.type != "calls" or edge.target.startswith("ext:"):
            continue
        rel = owner_file(edge.source)
        if rel not in sources:
            sources[rel] = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        target = index.nodes[edge.target]
        names = {target.label}
        via = edge.properties.get("via")
        if via in ("constructor", "call_method"):
            # 建構或呼叫實例：那一行寫的是類別（或持有實例的變數）的名字
            names.add(index.nodes[index.parent[edge.target]].label)
        for line in edge.properties["lines"]:
            total += 1
            # 呼叫可能跨行：看那一行與前後各兩行
            window = " ".join(sources[rel][max(0, line - 3) : line + 2])
            if not any(re.search(rf"\b{re.escape(n)}\b", window) for n in names):
                if via == "call_method":
                    continue  # `obj()`：寫的是變數名，本來就不會出現類別名
                suspicious += 1
                if len(shown) < 25:
                    text = sources[rel][line - 1].strip()[:90]
                    shown.append(f"{rel}:{line}  →  {edge.target.split('::')[-1]}\n      {text}")
    print(f"專案內的呼叫位置 {total} 個；那幾行沒出現被呼叫者名字的 {suspicious} 個（{suspicious / total:.2%}）")
    for item in shown:
        print("  " + item)


if __name__ == "__main__":
    main()
