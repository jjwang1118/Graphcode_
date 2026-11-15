"""T4（影響範圍）與 T5（function 細節）的驗收。答案照 Python 語意人工判定。"""

from pathlib import Path

import pytest

from codegraph_fable.analyze import analyze
from codegraph_fable.query import Index, detail, file_dependencies, impact, overview

FIXTURES = Path(__file__).parent / "fixtures"
USE, MODELS, UTIL = "app/use.py", "app/models.py", "app/util.py"


@pytest.fixture(scope="module")
def calls():
    return Index(analyze(FIXTURES / "calls" / "project", engine_check=False))


@pytest.fixture(scope="module")
def effects():
    return Index(analyze(FIXTURES / "effects" / "project", engine_check=False))


def _levels(result):
    return [{(e["id"], e["relation"], e["certainty"]) for e in level} for level in result["levels"]]


def test_impact_of_a_function_spreads_level_by_level(calls):
    result = impact(calls, f"function:{UTIL}::helper")
    assert _levels(result) == [
        {
            (f"file:{USE}", "calls", "certain"),  # 檔案層的呼叫
            (f"function:{MODELS}::Helper.work", "calls", "certain"),
            (f"function:{USE}::alias", "calls", "certain"),
            (f"function:{USE}::ref_only", "references", "certain"),  # 只傳參考、沒呼叫
        },
        {(f"function:{MODELS}::Foo.go", "calls", "certain")},  # self.b.work()
        {(f"function:{USE}::local_instance", "calls", "certain")},
    ]


def test_impact_lists_unresolved_calls_that_mention_the_name_as_candidates(calls):
    result = impact(calls, f"function:{UTIL}::helper")
    candidates = {(c["id"], c["text"]) for c in result["candidates"]}
    assert candidates == {
        (f"function:{USE}::param_shadow", "helper"),  # 其實是參數：列為候選並附原因，不當成確定
        (f"function:{USE}::dynamic", "getattr(util, 'helper')"),  # 真的會呼叫，但靜態解不出
    }
    done = result["completeness"]
    assert (done["affected"], done["certain"], done["possible"], done["candidates"]) == (6, 6, 0, 2)
    assert done["unresolved_calls_in_project"] == 4


def test_impact_of_an_override_includes_callers_of_the_base_method(calls):
    result = impact(calls, f"function:{MODELS}::Foo.step")
    assert _levels(result) == [
        {
            # Base.run 寫的是 self.step()：self 可能是 Foo，所以可能呼叫到這個覆寫
            (f"function:{MODELS}::Base.run", "dispatch", "possible"),
            (f"function:{USE}::union", "calls", "possible"),  # 兩種可能型別之一
        },
        {(f"function:{MODELS}::Foo.go", "calls", "possible")},  # 上游不確定，下游也不確定
        {(f"function:{USE}::local_instance", "calls", "possible")},
    ]


def test_impact_of_a_base_method_reports_who_overrides_it(calls):
    result = impact(calls, f"function:{MODELS}::Base.step")
    assert result["overridden_by"] == [f"function:{MODELS}::Foo.step"]
    assert (f"function:{MODELS}::Base.run", "calls", "certain") in _levels(result)[0]


def test_impact_of_a_class_covers_its_methods_subclasses_and_annotations(calls):
    result = impact(calls, f"class:{MODELS}::Foo", max_depth=1)
    assert _levels(result) == [
        {
            (f"class:{USE}::Child", "inherits", "certain"),
            (f"function:{USE}::annotated", "references", "certain"),
            (f"function:{USE}::local_instance", "calls", "certain"),
            (f"function:{USE}::union", "calls", "certain"),
            (f"function:{MODELS}::Base.run", "dispatch", "possible"),
        }
    ]


def test_impact_of_a_file_includes_importers(calls):
    first = _levels(impact(calls, f"file:{UTIL}", max_depth=1))[0]
    assert (f"file:{MODELS}", "imports", "certain") in first
    assert (f"file:{USE}", "imports", "certain") in first
    assert (f"function:{USE}::decorated", "references", "certain") in first


def test_impact_of_unknown_node_raises(calls):
    with pytest.raises(KeyError):
        impact(calls, "function:nope.py::x")


def test_find_by_name(calls):
    assert [n.id for n in calls.find("helper")] == [f"function:{UTIL}::helper"]
    assert [n.id for n in calls.find("Foo.go")] == [f"function:{MODELS}::Foo.go"]
    assert {n.id for n in calls.find("step")} == {
        f"function:{MODELS}::Base.step",
        f"function:{MODELS}::Foo.step",
    }
    assert calls.find("no_such_name") == []


def test_file_dependencies_separate_import_statements_from_actual_use(calls):
    deps = file_dependencies(calls)
    # 經 __init__.py 轉出：import 敘述指向 __init__.py，實際用到的是 impl.py
    assert deps[(USE, "app/pkg/__init__.py")] == {"imports": 1, "uses": 0}
    assert deps[(USE, "app/pkg/impl.py")] == {"imports": 0, "uses": 1}
    assert deps[(MODELS, UTIL)] == {"imports": 1, "uses": 1}


def test_overview(calls):
    result = overview(calls)
    assert result["packages"] == {"app": 6}
    assert result["externals"] == {"stdlib": ["builtins", "os"]}
    assert result["completeness"]["calls"]["unresolved"] == 4
    assert {"file": UTIL, "dependents": 2} in result["most_used_files"]


def _detail(index, name):
    return detail(index, f"function:app/effects.py::{name}")


def test_detail_interface_and_source_are_exact(effects):
    result = _detail(effects, "Store.save")
    assert result["interface"]["signature"] == "(self, path, data)"
    assert result["interface"]["reliability"] == "exact"
    assert (result["line"], result["end_line"]) == (12, 19)
    assert result["source"]["text"].splitlines()[0].strip() == "def save(self, path, data):"
    assert result["source"]["text"].splitlines()[-1].strip() == "return self.count"


def test_detail_state_and_raises(effects):
    result = _detail(effects, "Store.save")
    state = result["state"]
    assert (state["reads"], state["writes"], state["global_writes"]) == (
        ["count"],
        ["last"],
        ["TOTAL"],
    )
    assert state["reliability"] == "exact"
    assert result["raises"]["exceptions"] == ["ValueError"]
    assert result["returns"] == {
        "reliability": "exact",
        "return_statements": 1,
        "is_generator": False,
    }


def test_detail_calls_and_direct_side_effects(effects):
    result = _detail(effects, "cleanup")
    assert [c["target"] for c in result["calls"]["local"]] == ["function:app/util.py::helper"]
    assert [c["callee"] for c in result["calls"]["external"]] == ["os.remove", "subprocess.run"]
    assert set(result["side_effects"]["direct"]) == {"file", "process"}
    assert result["side_effects"]["reliability"] == "heuristic"
    assert result["calls"]["reliability"] == "inferred"


def test_detail_spurious_engine_answer_is_dropped(effects):
    callees = [c["callee"] for c in _detail(effects, "Store.save")["calls"]["external"]]
    assert "typing.Callable" not in callees
    assert set(_detail(effects, "Store.save")["side_effects"]["direct"]) == {"file"}


def test_detail_indirect_side_effects_follow_local_calls(effects):
    result = _detail(effects, "outer")["side_effects"]
    assert set(result["direct"]) == {"console"}
    assert set(result["indirect"]) == {"file", "process"}
    assert result["indirect"]["file"][0]["in"] == "function:app/effects.py::cleanup"


def test_detail_of_a_pure_function_is_empty(effects):
    result = _detail(effects, "pure")
    assert result["calls"]["local"] == result["calls"]["external"] == []
    assert result["side_effects"]["direct"] == result["side_effects"]["indirect"] == {}


def test_detail_reports_missing_source_instead_of_failing(calls):
    index = Index(analyze(FIXTURES / "effects" / "project", engine_check=False))
    index.graph.meta["root"] = "/nonexistent"
    result = _detail(index, "cleanup")
    assert result["source"]["available"] is False
    assert "state" not in result
    assert result["calls"]["local"]  # 圖裡的資訊仍然有
