"""命令列：python -m codegraph_fable.trace <專案> [--python P] [-o 圖.json] -- <指令…>

例：python -m codegraph_fable.trace ~/proj --python ~/proj/.venv/bin/python -- -m pytest -q -p no:cacheprovider
注意：這會執行專案的程式碼。
"""

from __future__ import annotations

import argparse
import json
import sys

from ..analyze import analyze
from ..store import save
from . import merge, record


def main() -> None:
    if "--" not in sys.argv:
        sys.exit(__doc__)
    split = sys.argv.index("--")
    parser = argparse.ArgumentParser(prog="python -m codegraph_fable.trace")
    parser.add_argument("project")
    parser.add_argument("--python", help="專案環境的 Python（預設：目前的 Python）")
    parser.add_argument("-o", "--output", help="把含 observed_calls 的圖存成 JSON")
    parser.add_argument("--top", type=int, default=20, help="列出幾筆漏掉的呼叫")
    args = parser.parse_args(sys.argv[1:split])
    command = sys.argv[split + 1 :]
    graph = analyze(args.project, python=args.python, engine_check=False)
    observed = record(args.project, command, args.python)
    report = merge(graph, observed)
    if args.output:
        save(graph, args.output)
    missing = sorted(report.pop("missing_calls"), key=lambda item: -item["count"])
    report.pop("dispatch_calls")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    for item in missing[: args.top]:
        print(f"  漏掉 ×{item['count']}  {item['caller']}  →  {item['callee']}")
    if len(missing) > args.top:
        print(f"  …只列出 {args.top} 筆，共 {len(missing)} 筆")


if __name__ == "__main__":
    main()
