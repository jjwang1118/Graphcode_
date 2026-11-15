"""逐檔抽取：定義與 import 敘述。只看單一檔案，不解析名字。規格：docs/spec/analyze.md"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

_IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
_TYPE_CHECKING = {"TYPE_CHECKING", "typing.TYPE_CHECKING"}


@dataclass
class Definition:
    kind: str  # class / function / variable
    qualname: str  # 檔案內唯一；重複定義時後者帶 @行號
    name: str
    parent: str | None  # 外層定義的 qualname；None 表示直接在檔案層
    line: int
    end_line: int
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportStmt:
    module: str | None  # `import a.b` → "a.b"；`from . import x` → None
    level: int  # 相對 import 的點數；0 是絕對
    name: str | None  # from-import 的名字（`*` 也算）；`import a.b` 為 None
    asname: str | None
    line: int
    scope: str  # module / function / class
    type_checking: bool
    guarded: bool  # 包在會接住 ImportError 的 try 裡


@dataclass
class FileFacts:
    definitions: list[Definition] = field(default_factory=list)
    imports: list[ImportStmt] = field(default_factory=list)
    top_names: set[str] = field(default_factory=set)  # 檔案層綁定的名字
    has_main_guard: bool = False
    parse_error: str | None = None


def _is_main_guard(test: ast.expr) -> bool:
    if not (isinstance(test, ast.Compare) and len(test.comparators) == 1):
        return False
    sides = [test.left, test.comparators[0]]
    has_name = any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
    has_main = any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides)
    return has_name and has_main


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(ast.unparse(t).split(".")[-1] in _IMPORT_ERRORS for t in types)


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _target_names(elt)]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


class _Extractor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.facts = FileFacts()
        self._stack: list[tuple[str, str]] = []  # (kind, qualname)
        self._seen: set[str] = set()
        self._type_checking = False
        self._guarded = False

    # --- 定義 ---

    def _declare(self, kind: str, name: str, node: ast.AST, props: dict[str, Any]) -> str:
        parent = self._stack[-1][1] if self._stack else None
        qualname = f"{parent}.{name}" if parent else name
        if qualname in self._seen:
            if kind == "variable":
                return qualname  # 變數重複指派只記第一次
            qualname = f"{qualname}@{node.lineno}"  # type: ignore[attr-defined]
            props = {**props, "redefinition": True}
        self._seen.add(qualname)
        if not self._stack:
            self.facts.top_names.add(name)
        self.facts.definitions.append(
            Definition(
                kind=kind,
                qualname=qualname,
                name=name,
                parent=parent,
                line=node.lineno,  # type: ignore[attr-defined]
                end_line=getattr(node, "end_lineno", None) or node.lineno,  # type: ignore[attr-defined]
                properties=props,
            )
        )
        return qualname

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        signature = f"({ast.unparse(node.args)})"
        if node.returns is not None:
            signature += f" -> {ast.unparse(node.returns)}"
        props: dict[str, Any] = {
            "signature": signature,
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "is_method": bool(self._stack) and self._stack[-1][0] == "class",
        }
        if node.decorator_list:
            props["decorators"] = [ast.unparse(d) for d in node.decorator_list]
        doc = ast.get_docstring(node)
        if doc:
            props["docstring"] = doc
        qualname = self._declare("function", node.name, node, props)
        self._stack.append(("function", qualname))
        for child in node.body:
            self.visit(child)
        self._stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        props: dict[str, Any] = {"bases": [ast.unparse(b) for b in node.bases]}
        if node.decorator_list:
            props["decorators"] = [ast.unparse(d) for d in node.decorator_list]
        doc = ast.get_docstring(node)
        if doc:
            props["docstring"] = doc
        qualname = self._declare("class", node.name, node, props)
        self._stack.append(("class", qualname))
        for child in node.body:
            self.visit(child)
        self._stack.pop()

    def _visit_assign(self, node: ast.AST, targets: list[ast.expr], annotation: str | None) -> None:
        # 只記檔案層與 class 內的變數；函式內的區域變數不是定義
        if self._stack and self._stack[-1][0] != "class":
            return
        for target in targets:
            for name in _target_names(target):
                props = {"annotation": annotation} if annotation else {}
                self._declare("variable", name, node, props)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._visit_assign(node, node.targets, None)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._visit_assign(node, [node.target], ast.unparse(node.annotation))

    # --- import ---

    def _scope(self) -> str:
        return self._stack[-1][0] if self._stack else "module"

    def _add_import(
        self, node: ast.AST, module: str | None, level: int, name: str | None, asname: str | None
    ) -> None:
        self.facts.imports.append(
            ImportStmt(
                module=module,
                level=level,
                name=name,
                asname=asname,
                line=node.lineno,  # type: ignore[attr-defined]
                scope=self._scope(),
                type_checking=self._type_checking,
                guarded=self._guarded,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add_import(node, alias.name, 0, None, alias.asname)
            if not self._stack:
                self.facts.top_names.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self._add_import(node, node.module, node.level, alias.name, alias.asname)
            if not self._stack and alias.name != "*":
                self.facts.top_names.add(alias.asname or alias.name)

    # --- 會改變 import 性質的區塊 ---

    def visit_If(self, node: ast.If) -> None:
        if not self._stack and _is_main_guard(node.test):
            self.facts.has_main_guard = True
        if ast.unparse(node.test) in _TYPE_CHECKING:
            previous, self._type_checking = self._type_checking, True
            for child in node.body:
                self.visit(child)
            self._type_checking = previous
            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    def _visit_try(self, node: ast.Try) -> None:
        guards = any(_catches_import_error(h) for h in node.handlers)
        previous, self._guarded = self._guarded, self._guarded or guards
        for child in node.body:
            self.visit(child)
        self._guarded = previous
        for part in (node.handlers, node.orelse, node.finalbody):
            for child in part:
                self.visit(child)

    visit_Try = _visit_try
    visit_TryStar = _visit_try


def extract(source: str) -> FileFacts:
    """抽出一個檔案的定義與 import。語法錯誤不拋例外，記在 `parse_error`。"""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as error:
        return FileFacts(parse_error=f"{type(error).__name__}: {error}")
    extractor = _Extractor()
    extractor.visit(tree)
    return extractor.facts
