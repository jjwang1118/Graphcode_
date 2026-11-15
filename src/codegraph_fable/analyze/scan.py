"""走訪專案目錄，列出要進圖的檔案與資料夾。規格：docs/spec/analyze.md"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

IGNORED_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
        "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
        ".nox", ".idea", ".vscode", ".codegraph",
    }
)  # fmt: skip


@dataclass
class ScanResult:
    root: Path
    files: list[str] = field(default_factory=list)  # 相對路徑，posix 寫法
    dirs: list[str] = field(default_factory=list)

    @property
    def python_files(self) -> list[str]:
        return [f for f in self.files if f.endswith(".py")]


def _ignored(parent: Path, name: str) -> bool:
    if name in ("dist", "build") and (parent / name / "__init__.py").is_file():
        return False  # 剛好叫這個名字的套件，不是建置產物
    if name in IGNORED_DIRS or name.endswith(".egg-info"):
        return True
    # 任何虛擬環境，不論叫什麼名字
    return (parent / name / "pyvenv.cfg").is_file()


def scan(root: str | Path) -> ScanResult:
    root = Path(root).resolve()
    result = ScanResult(root=root)
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(current)
        dirnames[:] = sorted(
            d for d in dirnames if not _ignored(here, d) and not (here / d).is_symlink()
        )
        rel = here.relative_to(root).as_posix()
        if rel != ".":
            result.dirs.append(rel)
        for name in sorted(filenames):
            path = here / name
            if path.is_symlink() or not path.is_file():
                continue
            result.files.append(path.relative_to(root).as_posix())
    return result


def fingerprint(scanned: ScanResult) -> str:
    """所有 Python 檔的路徑與內容的雜湊。用來判斷存下來的分析結果是否還對得上原始碼。"""
    digest = hashlib.sha256()
    for rel in scanned.python_files:
        digest.update(rel.encode("utf-8") + b"\0")
        try:
            digest.update((scanned.root / rel).read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()
