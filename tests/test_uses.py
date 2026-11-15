"""T3 的驗收：呼叫、繼承、覆寫、引用。標準答案是照 Python 語意人工判定的，寫死在這裡。

fixture：tests/fixtures/calls/project
"""

from pathlib import Path

import pytest

from codegraph_fable.analyze import analyze

PROJECT = Path(__file__).parent / "fixtures" / "calls" / "project"
USE = "app/use.py"
MODELS = "app/models.py"


@pytest.fixture(scope="module")
def graph():
    return analyze(PROJECT, engine_check=False)


def _targets(graph, kind, source):
    return {
        (e.target, e.properties.get("via"))
        for e in graph.edges
        if e.type == kind and e.source == source
    }


def _fn(rel, name):
    return f"function:{rel}::{name}"


def _cls(rel, name):
    return f"class:{rel}::{name}"


# (呼叫者, 應該連到的 (目標, via))
CALLS = [
    # self.方法()
    (_fn(MODELS, "Base.run"), {(_fn(MODELS, "Base.step"), None)}),
    # 模組.函式()
    (_fn(MODELS, "Helper.work"), {(_fn("app/util.py", "helper"), None)}),
    # 建構：類別沒有 __init__ 就只連類別
    (_fn(MODELS, "Foo.__init__"), {(_cls(MODELS, "Helper"), None)}),
    # self.屬性.方法()（型別推論）與 super().方法()
    (
        _fn(MODELS, "Foo.go"),
        {
            (_fn(MODELS, "Helper.work"), None),
            (_fn(MODELS, "Base.run"), None),
            ("ext:builtins", None),
        },
    ),
    # x = Foo(); x.go()：建構同時連到 __init__
    (
        _fn(USE, "local_instance"),
        {
            (_cls(MODELS, "Foo"), None),
            (_fn(MODELS, "Foo.__init__"), "constructor"),
            (_fn(MODELS, "Foo.go"), None),
        },
    ),
    # fn = util.helper; fn()
    (_fn(USE, "alias"), {(_fn("app/util.py", "helper"), None)}),
    # 兩種可能的型別 → 兩個目標
    (
        _fn(USE, "union"),
        {
            (_cls(MODELS, "Foo"), None),
            (_fn(MODELS, "Foo.__init__"), "constructor"),
            (_cls(MODELS, "Base"), None),
            (_fn(MODELS, "Base.step"), None),
            (_fn(MODELS, "Foo.step"), None),
        },
    ),
    # 經 __init__.py 轉出的函式，連到真正定義的檔案
    (_fn(USE, "reexport"), {(_fn("app/pkg/impl.py", "thing"), None)}),
    # 外部
    (_fn(USE, "external"), {("ext:os", None)}),
    (_fn(USE, "ref_only"), {("ext:builtins", None)}),
    # 物件實例被呼叫 → __call__
    (
        _fn(USE, "instance_call"),
        {(_cls(MODELS, "Invoker"), None), (_fn(MODELS, "Invoker.__call__"), "call_method")},
    ),
    # 檔案層的呼叫：來源是檔案
    (f"file:{USE}", {(_fn("app/util.py", "helper"), None)}),
    # 假邊的反例：參數遮蔽、解不出的，不可以有任何本地目標
    (_fn(USE, "param_shadow"), set()),
    (_fn(USE, "untyped"), set()),
    (_fn(USE, "dynamic"), {("ext:builtins", None)}),  # 只有 getattr 本身
]


@pytest.mark.parametrize(("source", "expected"), CALLS)
def test_calls(graph, source, expected):
    assert _targets(graph, "calls", source) == expected


def test_parameter_named_like_a_function_does_not_link_to_it(graph):
    helper = _fn("app/util.py", "helper")
    callers = {e.source for e in graph.edges if e.type == "calls" and e.target == helper}
    assert _fn(USE, "param_shadow") not in callers


def test_unresolved_calls_are_recorded_with_a_reason(graph):
    def unresolved(name):
        node = next(n for n in graph.nodes if n.id == _fn(USE, name))
        return [(u["text"], u["reason"][:2]) for u in node.properties.get("unresolved_calls", [])]

    assert unresolved("param_shadow") == [("helper", "參數")]
    assert unresolved("dynamic") == [("d[k]", "被呼"), ("getattr(util, 'helper')", "被呼")]
    assert unresolved("untyped") == [("obj.bar", "引擎")]
    assert unresolved("alias") == []


def test_call_counts_are_per_call_expression(graph):
    calls = graph.meta["uses"]["calls"]
    assert calls["expressions"] == calls["resolved"] + calls["unresolved"]
    assert calls["resolved"] == calls["local"] + calls["external"]
    assert calls["unresolved"] == sum(calls["reasons"].values()) == 4
    assert calls["reasons"] == {"param": 1, "dynamic": 2, "unknown": 1}
    assert calls["ambiguous"] == 1
    recorded = sum(len(n.properties.get("unresolved_calls", [])) for n in graph.nodes)
    assert recorded == calls["unresolved"]


def test_ambiguous_call_is_flagged(graph):
    flagged = {
        e.target
        for e in graph.edges
        if e.type == "calls" and e.source == _fn(USE, "union") and e.properties.get("ambiguous")
    }
    assert flagged == {_fn(MODELS, "Base.step"), _fn(MODELS, "Foo.step")}


def test_external_call_keeps_the_callee_name(graph):
    (edge,) = [e for e in graph.edges if e.type == "calls" and e.source == _fn(USE, "external")]
    assert edge.properties["callee"] == "os.path.join"
    assert edge.properties["evidence"] == "jedi"
    assert edge.properties["lines"] == [33]


def test_inherits(graph):
    assert _targets(graph, "inherits", _cls(MODELS, "Foo")) == {(_cls(MODELS, "Base"), None)}
    assert _targets(graph, "inherits", _cls(USE, "Child")) == {(_cls(MODELS, "Foo"), None)}
    assert _targets(graph, "inherits", _cls(USE, "Ext")) == {("ext:builtins", None)}
    assert graph.meta["uses"]["inherits"] == {"bases": 3, "resolved": 3, "unresolved": 0}


def test_overrides(graph):
    overrides = {(e.source, e.target) for e in graph.edges if e.type == "overrides"}
    assert overrides == {(_fn(MODELS, "Foo.step"), _fn(MODELS, "Base.step"))}


REFERENCES = [
    # 傳函式參考而不呼叫
    (_fn(USE, "ref_only"), {_fn("app/util.py", "helper")}),
    (_fn(USE, "alias"), {_fn("app/util.py", "helper")}),
    # 沒有括號的裝飾器、讀別的模組的變數：算在被裝飾的函式上
    (_fn(USE, "decorated"), {_fn("app/util.py", "deco"), "variable:app/util.py::LIMIT"}),
    # 型別註解
    (_fn(USE, "annotated"), {_cls(MODELS, "Foo"), _cls(MODELS, "Base")}),
    (_fn("app/util.py", "helper"), {"variable:app/util.py::LIMIT"}),
    # 參數不是對同名函式的引用
    (_fn(USE, "param_shadow"), set()),
]


@pytest.mark.parametrize(("source", "expected"), REFERENCES)
def test_references(graph, source, expected):
    assert {t for t, _ in _targets(graph, "references", source)} == expected


def test_uses_can_be_disabled():
    graph = analyze(PROJECT, engine_check=False, resolve_uses_=False)
    assert graph.meta["uses"]["available"] is False
    assert not any(e.type in ("calls", "inherits", "references", "overrides") for e in graph.edges)
