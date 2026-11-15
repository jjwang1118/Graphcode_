"""逐檔找出「使用點」：呼叫、繼承的 base、對名字的引用。只看單一檔案，不解析。

規格：docs/spec/analyze.md（AN-U 規則）。解析由 calls.py 交給 Jedi。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .definitions import FileFacts


@dataclass
class Site:
    role: str  # call / base / ref
    scope: str | None  # 所在定義的 qualname；None 表示檔案層
    line: int  # 交給引擎的位置：行（從 1 起算）
    col: int  # 欄（字元，從 0 起算）
    text: str  # 原始寫法，給人看
    resolvable: bool = True  # False：被呼叫的不是名字（`d[k]()`、`f()()`），引擎無從解起
    decorator: bool = False


def _text(node: ast.AST) -> str:
    text = ast.unparse(node)
    return text if len(text) <= 80 else text[:77] + "..."


class _Collector(ast.NodeVisitor):
    def __init__(self, source: str, facts: FileFacts, candidates: set[str]) -> None:
        self.sites: list[Site] = []
        self._lines = source.splitlines()
        self._qualnames = {(d.kind, d.name, d.line): d.qualname for d in facts.definitions}
        self._candidates = candidates
        self._stack: list[str] = []
        self._handled: set[int] = set()  # 已經以 call / base 身分記過的節點
        self._decorator = False

    # --- 位置 ---

    def _col(self, line: int, byte_offset: int) -> int:
        """ast 的欄是 UTF-8 位元組位移，引擎要的是字元位移。"""
        try:
            raw = self._lines[line - 1].encode("utf-8")[:byte_offset]
        except IndexError:
            return byte_offset
        return len(raw.decode("utf-8", errors="ignore"))

    def _position(self, node: ast.Name | ast.Attribute) -> tuple[int, int]:
        if isinstance(node, ast.Name):
            return node.lineno, self._col(node.lineno, node.col_offset)
        line = node.end_lineno or node.lineno
        return line, self._col(line, node.end_col_offset or 0) - len(node.attr)

    def _add(self, role: str, node: ast.expr, scope: str | None = None) -> None:
        resolvable = isinstance(node, (ast.Name, ast.Attribute))
        line, col = self._position(node) if resolvable else (node.lineno, 0)  # type: ignore[arg-type]
        self.sites.append(
            Site(
                role=role,
                scope=scope if scope is not None else (self._stack[-1] if self._stack else None),
                line=line,
                col=col,
                text=_text(node),
                resolvable=resolvable,
                decorator=self._decorator,
            )
        )

    # --- 使用點 ---

    def visit_Call(self, node: ast.Call) -> None:
        self._add("call", node.func)
        self._handled.add(id(node.func))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if (
            isinstance(node.ctx, ast.Load)
            and id(node) not in self._handled
            and node.id in self._candidates
        ):
            self._add("ref", node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.ctx, ast.Load)
            and id(node) not in self._handled
            and node.attr in self._candidates
        ):
            self._add("ref", node)
        self.visit(node.value)

    # --- 定義：決定「誰在用」 ---

    def _enter(
        self, kind: str, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> bool:
        qualname = self._qualnames.get((kind, node.name, node.lineno))
        if qualname is None:
            return False
        self._stack.append(qualname)
        # 裝飾器寫在定義外面，但它影響的是這個定義：算在被裝飾者頭上
        previous, self._decorator = self._decorator, True
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._decorator = previous
        return True

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        entered = self._enter("class", node)
        for base in node.bases:
            target = base.value if isinstance(base, ast.Subscript) else base  # Generic[T] → Generic
            if isinstance(target, (ast.Name, ast.Attribute)):
                self._add("base", target)
                self._handled.add(id(target))
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword)
        for child in node.body:
            self.visit(child)
        if entered:
            self._stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        entered = self._enter("function", node)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        for child in node.body:
            self.visit(child)
        if entered:
            self._stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function


def collect_sites(source: str, facts: FileFacts, candidates: set[str]) -> list[Site]:
    """candidates：專案內所有定義的名字 ＋ import 的別名。引用只記名字在這份名單裡的。"""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    collector = _Collector(source, facts, candidates)
    collector.visit(tree)
    return collector.sites
