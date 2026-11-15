"""搜尋根目錄、專案宣告的依賴、執行探針。規格：docs/spec/analyze.md"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

_PROBE = Path(__file__).with_name("probe.py")
# 名字後面必須接版本條件、extras、`@`、`;` 或結尾；`git+https://…` 這種網址行不是套件名
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?=$|[\[<>=!~;@,(])")


def normalize(name: str) -> str:
    """套件名正規化（PEP 503）：`PyYAML`、`py_yaml` → `pyyaml`。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def default_roots(root: Path) -> list[Path]:
    """預設的搜尋根：專案根，加上 `src/`（若裡面有 Python 檔或套件）。"""
    roots = [root]
    src = root / "src"
    if src.is_dir() and (any(src.glob("*.py")) or any(src.glob("*/*.py"))):
        roots.append(src)
    return roots


def _names(requirements: list[Any]) -> set[str]:
    found = set()
    for item in requirements:
        match = _NAME.match(item) if isinstance(item, str) else None
        if match:
            found.add(normalize(match.group(1)))
    return found


def declared_dependencies(root: Path) -> set[str]:
    """專案宣告的依賴（正規化後的套件名），來自 requirements*.txt 與 pyproject.toml。"""
    declared: set[str] = set()
    for path in sorted(root.glob("requirements*.txt")):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        declared |= _names([ln.split("#")[0] for ln in lines if not ln.lstrip().startswith("-")])
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            return declared
        project = data.get("project", {})
        declared |= _names(project.get("dependencies", []))
        for group in project.get("optional-dependencies", {}).values():
            declared |= _names(group)
        for group in data.get("dependency-groups", {}).values():
            declared |= _names(group)
        poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        declared |= {normalize(name) for name in poetry if name.lower() != "python"}
    return declared


def run_probe(
    python: str | None, queries: list[dict[str, Any]], extra_paths: list[str]
) -> dict[str, Any]:
    """在目標環境的 Python 裡跑探針，回傳環境資訊與查詢結果。"""
    completed = subprocess.run(
        [python or sys.executable, str(_PROBE)],
        input=json.dumps({"extra_paths": extra_paths, "queries": queries}),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"探針執行失敗（{python or sys.executable}）：{completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)
