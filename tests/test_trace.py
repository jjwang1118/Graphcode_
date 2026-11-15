"""T9 的驗收：實際執行、記錄呼叫、與靜態分析比對。答案照程式實際的執行路徑人工推定。"""

from pathlib import Path

import pytest

from codegraph_fable.analyze import analyze
from codegraph_fable.trace import compare, merge, record

PROJECT = Path(__file__).parent / "fixtures" / "runtime" / "project"
RUN, LIB = "run.py", "lib.py"


@pytest.fixture(scope="module")
def observed():
    return record(PROJECT, ["run.py"])


@pytest.fixture(scope="module")
def report(observed):
    return compare(analyze(PROJECT, engine_check=False), observed)


def test_command_runs_and_leaves_no_bytecode(observed):
    assert observed["returncode"] == 0
    assert not (PROJECT / "__pycache__").exists()


def test_observed_calls_are_classified(report):
    def pairs(key):
        return {(i["caller"], i["callee"]) for i in report[key]}

    # 執行時 self 是 Sub：靜態只連到 Base.step，但影響範圍經覆寫查得到
    assert pairs("dispatch_calls") == {(f"function:{LIB}::Base.run", f"function:{LIB}::Sub.step")}
    # getattr(...)() 靜態解不出：這是真的漏掉
    assert pairs("missing_calls") == {(f"function:{LIB}::dynamic", f"function:{LIB}::Sub.step")}
    assert (report["observed"], report["confirmed"], report["dispatch"], report["missing"]) == (
        7,
        5,
        1,
        1,
    )
    assert report["recall"] == round(5 / 7, 4)
    assert report["recall_with_dispatch"] == round(6 / 7, 4)
    assert report["unmapped"] == 0


def test_merge_adds_missed_calls_as_a_separate_edge_type(observed):
    graph = analyze(PROJECT, engine_check=False)
    static_calls = sum(1 for e in graph.edges if e.type == "calls")
    merge(graph, observed)
    added = [e for e in graph.edges if e.type == "observed_calls"]
    assert [(e.source, e.target) for e in added] == [
        (f"function:{LIB}::dynamic", f"function:{LIB}::Sub.step")
    ]
    assert added[0].properties == {"count": 1, "evidence": "runtime"}
    assert sum(1 for e in graph.edges if e.type == "calls") == static_calls  # 靜態的邊沒被動到
    assert graph.meta["runtime"]["missing"] == 1 and "missing_calls" not in graph.meta["runtime"]


def test_generator_expression_inside_a_function_is_not_a_self_call(tmp_path):
    source = "def total(xs):\n    return sum(x * 2 for x in xs)\n\n\ndef main():\n    return total([1, 2])\n\n\nmain()\n"
    (tmp_path / "gen.py").write_text(source)
    report = compare(analyze(tmp_path, engine_check=False), record(tmp_path, ["gen.py"]))
    assert report["missing_calls"] == []
    assert (report["observed"], report["confirmed"]) == (2, 2)  # 檔案 → main、main → total


def test_a_failing_command_is_reported_not_hidden(tmp_path):
    (tmp_path / "boom.py").write_text("def f():\n    raise SystemExit(3)\n\n\nf()\n")
    observed = record(tmp_path, ["boom.py"])
    assert observed["returncode"] == 3
    assert [p["callee"]["name"] for p in observed["pairs"]] == ["f"]
