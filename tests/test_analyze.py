"""T2 的驗收：定義抽取、import 解析、套件分類。標準答案寫死在這裡。

fixture：tests/fixtures/p2/project（被分析的專案）＋ tests/fixtures/p2/site（假的套件安裝目錄，
裝了 PyYAML、openai、opencv-python；沒有裝 notinstalled）。
"""

from pathlib import Path

import pytest

from codegraph_fable.analyze import analyze

FIXTURE = Path(__file__).parent / "fixtures" / "p2"


@pytest.fixture(scope="module")
def graph():
    return analyze(FIXTURE / "project", extra_paths=[FIXTURE / "site"])


def _edge(graph, source, module, name=None):
    found = [
        e
        for e in graph.edges
        if e.type == "imports"
        and e.source == f"file:{source}"
        and e.properties["module"] == module
        and e.properties.get("name") == name
    ]
    assert len(found) == 1, f"{source}: import {module} {name} → {len(found)} 條邊"
    return found[0]


def _node(graph, node_id):
    return next(n for n in graph.nodes if n.id == node_id)


# (來源檔案, 寫法, from-import 的名字, 應該接到)
IMPORT_TARGETS = [
    # 標準庫
    ("main.py", "os", None, "ext:os"),
    ("main.py", "sys", None, "ext:sys"),
    ("main.py", "os.path", None, "ext:os"),
    ("app/user.py", "__future__", "annotations", "ext:__future__"),
    ("app/user.py", "typing", "TYPE_CHECKING", "ext:typing"),
    ("app/user.py", "json", None, "ext:json"),
    # 套件內的同名檔案搶不走標準庫與第三方（參照專案在這裡判錯）
    ("app/user.py", "types", None, "ext:types"),
    ("app/user.py", "openai", None, "ext:openai"),
    ("app/openai.py", "openai", "Client", "ext:openai"),
    # 根目錄的同名檔案真的會蓋掉（Python 執行時也是如此）
    ("main.py", "colorsys", None, "file:colorsys.py"),
    ("main.py", "yaml", None, "file:yaml.py"),
    # 第三方
    ("main.py", "cv2", None, "ext:cv2"),
    # 沒安裝的套件不會被接到本地同名資料夾
    ("app/bridges/notinstalled/bridge.py", "notinstalled", None, "ext:notinstalled"),
    ("app/bridges/notinstalled/bridge.py", "notinstalled.agents.env", None, "ext:notinstalled"),
    ("app/user.py", "ujson", None, "ext:ujson"),
    # 本地
    ("main.py", "srcpkg.core", None, "file:src/srcpkg/core.py"),
    ("src/srcpkg/core.py", "srcpkg", None, "file:src/srcpkg/__init__.py"),
    ("main.py", "nsdir.sub.leaf", None, "file:nsdir/sub/leaf.py"),
    ("main.py", "app.sideeffect", None, "file:app/sideeffect.py"),
    ("main.py", "app", "models", "file:app/models.py"),
    ("main.py", "app.pkg", "thing", "file:app/pkg/__init__.py"),
    ("main.py", "app.pkg", "impl", "file:app/pkg/impl.py"),
    ("main.py", "app", "*", "file:app/__init__.py"),
    ("app/user.py", "app.models", "Model", "file:app/models.py"),
    ("scripts/run.py", "app.models", None, "file:app/models.py"),
    # 相對 import
    ("app/user.py", ".", "types", "file:app/types.py"),
    ("app/user.py", ".util", "helper", "file:app/util.py"),
    ("app/pkg/__init__.py", ".impl", "thing", "file:app/pkg/impl.py"),
    # 當成腳本執行才成立的同層 import
    ("app/sib.py", "util", None, "file:app/util.py"),
    ("scripts/run.py", "helpers", None, "file:scripts/helpers.py"),
    ("scripts/run.py", "yaml", None, "file:yaml.py"),
]


@pytest.mark.parametrize(("source", "module", "name", "target"), IMPORT_TARGETS)
def test_import_target(graph, source, module, name, target):
    assert _edge(graph, source, module, name).target == target


def test_external_categories(graph):
    expected = {
        "ext:os": "stdlib",
        "ext:types": "stdlib",
        "ext:json": "stdlib",
        "ext:openai": "third_party",
        "ext:cv2": "third_party",
        "ext:notinstalled": "third_party",  # 沒安裝，但 requirements.txt 有宣告
        "ext:ujson": "unknown",  # 沒安裝、也沒宣告
    }
    actual = {i: _node(graph, i).properties["category"] for i in expected}
    assert actual == expected


def test_distribution_name_differs_from_import_name(graph):
    props = _node(graph, "ext:cv2").properties
    assert props["distributions"] == ["opencv-python"]
    assert props["declared"] is True
    assert props["installed"] is True


def test_missing_dependency_is_reported(graph):
    assert _node(graph, "ext:notinstalled").properties["installed"] is False
    assert graph.meta["missing_dependencies"] == ["notinstalled"]


def test_shadowing_is_flagged(graph):
    assert _edge(graph, "main.py", "colorsys").properties["shadows"] == "stdlib"
    assert _edge(graph, "main.py", "yaml").properties["shadows"] == "third_party"
    assert "shadows" not in _edge(graph, "app/user.py", "types").properties
    assert graph.meta["imports"]["shadowing"] == 3  # main.py ×2 ＋ scripts/run.py 的 yaml


def test_entry_sensitive_imports(graph):
    script_yaml = _edge(graph, "scripts/run.py", "yaml").properties
    assert script_yaml["entry_sensitive"] is True
    assert script_yaml["alt_target"] == "ext:yaml"  # python scripts/run.py 時是第三方的 PyYAML
    for source, module in (("app/sib.py", "util"), ("scripts/run.py", "helpers")):
        props = _edge(graph, source, module).properties
        assert props["via"] == "script_dir"
        assert props["entry_sensitive"] is True
    assert "entry_sensitive" not in _edge(graph, "scripts/run.py", "app.models").properties
    assert "entry_sensitive" not in _edge(graph, "main.py", "yaml").properties


def test_import_statement_properties(graph):
    assert _edge(graph, "app/user.py", "app.models", "Model").properties["type_checking"] is True
    assert _edge(graph, "app/user.py", "json").properties["scope"] == "function"
    assert _edge(graph, "app/user.py", "ujson").properties["guarded"] is True
    assert _edge(graph, "main.py", "os").properties["scope"] == "module"


def test_unresolved_imports_are_listed_not_dropped(graph):
    unresolved = {(u["file"], u["module"], u["name"]) for u in graph.meta["unresolved_imports"]}
    assert unresolved == {("main.py", "app.nothing", None), ("app/user.py", "..", "nothing_above")}
    assert graph.meta["imports"]["unresolved"] == 2
    stats = graph.meta["imports"]
    edges = sum(1 for e in graph.edges if e.type == "imports")
    assert stats["total"] == edges + stats["unresolved"]


def test_engine_agrees_with_python(graph):
    engine = graph.meta["engine"]
    assert engine["available"] is True
    assert graph.meta["engine_disagreements"] == []
    assert engine["agree"] > 0


def test_scan_ignores_virtualenv_and_keeps_other_files(graph):
    ids = {n.id for n in graph.nodes}
    assert "file:requirements.txt" in ids
    assert not any("ignored_env" in i for i in ids)
    assert graph.meta["search_roots"] == [".", "src"]


def test_parse_error_is_recorded(graph):
    assert [e["file"] for e in graph.meta["parse_errors"]] == ["broken.py"]
    assert "parse_error" in _node(graph, "file:broken.py").properties


def test_definitions(graph):
    prefix = "defs.py::"
    found = {
        n.id.split("::")[1]: n for n in graph.nodes if n.id.split(":", 1)[1].startswith(prefix)
    }
    kinds = {name: node.type for name, node in found.items()}
    assert kinds == {
        "LIMIT": "variable",
        "a": "variable",
        "b": "variable",
        "Runner": "class",
        "Runner.retries": "variable",
        "Runner.__init__": "function",
        "Runner.fetch": "function",
        "Runner.fetch.inner": "function",
        "Runner.Config": "class",
        "Runner.Config.debug": "variable",
        "helper": "function",
        "helper@30": "function",
    }
    init = found["Runner.__init__"].properties
    assert init["signature"] == "(self, name: str, *args, flag=False, **kwargs) -> None"
    assert init["is_method"] is True
    assert (init["line"], init["end_line"]) == (12, 13)
    fetch = found["Runner.fetch"].properties
    assert fetch["is_async"] is True
    assert fetch["decorators"] == ["staticmethod"]
    assert found["Runner"].properties["bases"] == ["Base"]
    assert found["Runner"].properties["docstring"] == "跑東西。"
    assert found["LIMIT"].properties["annotation"] == "int"
    assert found["helper@30"].properties["redefinition"] is True


def test_defines_edges_follow_nesting(graph):
    defines = {(e.source, e.target) for e in graph.edges if e.type == "defines"}
    assert ("file:defs.py", "class:defs.py::Runner") in defines
    assert ("class:defs.py::Runner", "function:defs.py::Runner.fetch") in defines
    assert ("function:defs.py::Runner.fetch", "function:defs.py::Runner.fetch.inner") in defines
