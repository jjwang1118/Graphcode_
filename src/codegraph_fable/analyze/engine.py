"""Jedi 包裝。只有 analyze/ 會用到 Jedi。規格：docs/spec/analyze.md

兩個用途：核對 import（F2）、解析呼叫／繼承／引用指向哪個定義（calls.py）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class Engine:
    def __init__(self, root: Path, python: str, sys_path: list[str]) -> None:
        import jedi

        self.version: str = jedi.__version__
        self._jedi = jedi
        self._root = root
        self._environment = jedi.create_environment(python, safe=False)
        # F1：路徑清單由我們明定，關掉 Jedi 自己的猜測
        self._project = jedi.Project(
            str(root), sys_path=list(sys_path), smart_sys_path=False, load_unsafe_extensions=False
        )

    def module_paths(self, name: str) -> list[str]:
        """`import <name>` 會載入的檔案；解不出回空清單。"""
        code = f"import {name}\n"
        script = self._jedi.Script(
            code=code,
            path=str(self._root / "__codegraph_check__.py"),
            project=self._project,
            environment=self._environment,
        )
        found = script.goto(1, len(code) - 2, follow_imports=True, follow_builtin_imports=True)
        return sorted({str(d.module_path) for d in found if d.module_path is not None})

    def script(self, path: Path, source: str) -> Any:
        return self._jedi.Script(
            code=source, path=str(path), project=self._project, environment=self._environment
        )

    @staticmethod
    def goto(script: Any, line: int, col: int) -> list[Any]:
        """這個位置的名字「是在哪裡定義的」；會跟著 import 走到底。解不出回空清單。"""
        try:
            return script.goto(line, col, follow_imports=True, follow_builtin_imports=True)
        except Exception:
            return []

    @staticmethod
    def infer(script: Any, line: int, col: int) -> list[Any]:
        """這個位置的運算式「值是什麼」（型別推論）。解不出回空清單。"""
        try:
            return script.infer(line, col)
        except Exception:
            return []
