"""啟動網頁後端：python -m codegraph_fable.web [--port 8000] [--reload]

必須先設定環境變數 CODEGRAPH_ALLOWED_ROOTS（允許分析的資料夾，多個用 : 分隔）。
"""

import argparse
from pathlib import Path

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m codegraph_fable.web")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="後端程式碼一改就自動重啟（開發用）")
    args = parser.parse_args()
    # 只聽本機：這個 API 能讀取允許清單內任何專案的原始碼
    uvicorn.run(
        "codegraph_fable.web.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(Path(__file__).resolve().parents[1])] if args.reload else None,
    )
