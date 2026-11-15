"""分析結果的取得：記憶體 → 專案內的存檔 → 重新分析。MCP 與網頁共用。規格：docs/spec/mcp.md（MCP-2 – MCP-5）

每次查詢前都比對原始碼的雜湊，過期就重新分析——寧可慢，不回答舊的結果。
"""

from __future__ import annotations

import sys
from pathlib import Path

from .analyze import analyze
from .analyze.scan import fingerprint, scan
from .model import SCHEMA_VERSION, Graph
from .query import Index
from .store import load, save

STORE_DIR = ".codegraph"
STORE_FILE = "graph.json"
_PYTHON_CANDIDATES = (
    ".venv/bin/python", "venv/bin/python", ".venv/Scripts/python.exe", "venv/Scripts/python.exe",
)  # fmt: skip


def detect_python(project: Path) -> str | None:
    """專案資料夾裡的虛擬環境；找不到回 None。"""
    for candidate in _PYTHON_CANDIDATES:
        if (project / candidate).is_file():
            return str(project / candidate)
    return None


def _fresh(graph: Graph, current: str, python: str | None) -> bool:
    meta = graph.meta
    if meta.get("schema_version") != SCHEMA_VERSION or meta.get("fingerprint") != current:
        return False
    return python is None or meta.get("options", {}).get("python") == python


class Service:
    def __init__(self) -> None:
        self._cache: dict[str, Index] = {}

    def index(
        self, project: str, python: str | None = None, force: bool = False
    ) -> tuple[Index, str]:
        """回傳 (索引, 來源)。來源：cached／loaded／analyzed（附原因）。"""
        root = Path(project).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"找不到專案資料夾：{root}")
        key = str(root)
        current = fingerprint(scan(root))
        store = root / STORE_DIR / STORE_FILE
        reason = "強制重新分析" if force else "還沒有分析結果"
        previous: Graph | None = None
        if not force:
            cached = self._cache.get(key)
            if cached is not None:
                previous = cached.graph
                if _fresh(previous, current, python):
                    return cached, "cached"
            elif store.is_file():
                try:
                    previous = load(store)
                except Exception:  # 存檔壞掉或格式不符：當作沒有
                    previous = None
                if previous is not None and _fresh(previous, current, python):
                    self._cache[key] = Index(previous)
                    return self._cache[key], "loaded"
            if previous is not None:
                reason = "原始碼或設定已變動"
        # 沒指定環境時：沿用上次的 → 專案內的虛擬環境 → 本工具的 Python
        if python is None and previous is not None:
            used = previous.meta.get("options", {}).get("python")
            python = used if used and Path(used).is_file() else None
        python = python or detect_python(root) or sys.executable
        graph = analyze(root, python=python)
        note = ""
        try:
            store.parent.mkdir(exist_ok=True)
            ignore = store.parent / ".gitignore"
            if not ignore.exists():
                ignore.write_text("*\n", encoding="utf-8")
            save(graph, store)
        except OSError as error:
            note = f"；無法存檔（{error}），結果只留在記憶體"
        self._cache[key] = Index(graph)
        return self._cache[key], f"analyzed（{reason}{note}）"
