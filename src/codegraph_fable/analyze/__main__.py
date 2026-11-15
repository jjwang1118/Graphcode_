"""命令列：python -m codegraph_fable.analyze <專案目錄> [-o 結果.json]"""

from __future__ import annotations

import argparse
import json

from ..store import save
from .run import analyze


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m codegraph_fable.analyze")
    parser.add_argument("root", help="要分析的專案目錄")
    parser.add_argument("-o", "--output", help="分析結果存成 JSON 檔；不給就只印摘要")
    parser.add_argument("--python", help="專案環境的 Python 執行檔（預設：目前的 Python）")
    parser.add_argument("--root", dest="roots", action="append", help="搜尋根目錄，可重複")
    parser.add_argument(
        "--extra-path", dest="extra", action="append", help="額外的套件目錄，可重複"
    )
    args = parser.parse_args()
    graph = analyze(args.root, roots=args.roots, python=args.python, extra_paths=args.extra)
    if args.output:
        save(graph, args.output)
    summary = {
        key: graph.meta[key]
        for key in ("search_roots", "counts", "imports", "missing_dependencies", "engine")
    }
    summary["unresolved_imports"] = len(graph.meta["unresolved_imports"])
    summary["parse_errors"] = len(graph.meta["parse_errors"])
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
