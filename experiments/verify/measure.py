"""實際執行專案的測試，量靜態分析的圖涵蓋了多少真正發生的呼叫。一次性的驗證腳本。

觀察結果會存檔，下次直接重用（測試不必重跑）。
用法：python measure.py <專案根> <專案環境的 python> <觀察結果.json> -- <指令…>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from codegraph_fable.analyze import analyze
from codegraph_fable.trace import CATEGORIES, compare, record


def main() -> None:
    split = sys.argv.index("--")
    root, python, cache = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    if cache.is_file():
        observed = json.loads(cache.read_text())
    else:
        observed = record(root, sys.argv[split + 1 :], python)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(observed))
    graph = analyze(root, python=python, engine_check=False)
    report = compare(graph, observed)
    uses = graph.meta["uses"]
    print(f"指令結束代碼 {report['returncode']}；觀察到 {report['observed']} 組呼叫")
    print("  " + "  ".join(f"{name} {report[name]}" for name in CATEGORIES))
    print(
        f"  只算 calls 邊：{report['recall']:.1%}　影響範圍查得到：{report['coverage']:.1%}　"
        f"加上候選：{report['coverage_with_candidates']:.1%}"
    )
    print(
        f"  靜態：{uses['calls']['expressions']} 個呼叫、解不出 {uses['calls']['unresolved']}、"
        f"解不出的屬性存取 {uses['unresolved_property_reads']}"
    )
    where = Counter()
    for item in report["missing_calls"]:
        caller_test = "/test" in "/" + item["caller"] or "conftest" in item["caller"]
        where["呼叫者在測試裡" if caller_test else "呼叫者在程式本身"] += 1
    print(f"  漏掉的 {report['missing']} 組：{dict(where)}")
    shown = [i for i in report["missing_calls"] if "/test" not in "/" + i["caller"]]
    for item in sorted(shown, key=lambda i: -i["count"])[:10]:
        print(f"    ×{item['count']:<5} {item['caller'].split(':', 1)[1]}  →  {item['callee'].split(':', 1)[1]}")


if __name__ == "__main__":
    main()
