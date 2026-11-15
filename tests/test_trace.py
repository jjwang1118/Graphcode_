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
    assert report["coverage"] == round(6 / 7, 4)
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


def test_every_kind_of_observed_call_is_classified(tmp_path):
    files = {
        "lib.py": (
            'NAME = "".join(["b", "o", "x"])\n'
            "HANDLERS = {}\n\n\n"
            "class Box:\n"
            "    @property\n"
            "    def size(self):\n        return 1\n\n\n"
            "class Holder:\n"
            "    def __init__(self):\n        self.box = Box()\n\n\n"
            "def deco(fn):\n    return fn\n\n\n"
            "def typed(box: Box):\n    return box.size\n\n\n"  # 讀 property：references
            # 屬性名字執行時才知道，引擎推不出型別：候選
            "def untyped(holder):\n    return getattr(holder, NAME).size\n\n\n"
            'def register(fn):\n    HANDLERS["x"] = fn\n\n\n'
            'def dispatch():\n    return HANDLERS["x"]()\n\n\n'  # 從表裡取出來呼叫：測試替身
            "@deco\n"
            "def decorated():\n    return 1\n"  # 裝飾器在檔案層執行，邊記在 decorated 上
        ),
        "tests/test_lib.py": "def fake():\n    return 2\n",
        "main.py": (
            "from lib import Box, Holder, dispatch, register, typed, untyped\n"
            "from tests.test_lib import fake\n\n\n"
            "def run():\n"
            "    register(fake)\n"
            "    return typed(Box()), untyped(Holder()), dispatch()\n\n\n"
            "run()\n"
        ),
    }
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content)
    graph = analyze(tmp_path, engine_check=False)
    observed = record(tmp_path, ["main.py"])
    assert observed["returncode"] == 0, observed["output_tail"]
    report = compare(graph, observed)
    kinds = ("confirmed", "reference", "nested", "candidate", "test_double", "missing")
    assert {k: report[k] for k in kinds} == {
        # 檔案→run；run→typed、untyped、register、dispatch、Holder.__init__
        "confirmed": 6,
        "reference": 1,  # typed→size
        "nested": 1,  # lib.py→deco
        "candidate": 1,  # untyped→size
        "test_double": 1,  # dispatch→fake
        "missing": 0,
    }
    assert report["coverage"] == round(8 / 9, 4)  # 分母不含測試替身
    assert report["coverage_with_candidates"] == 1.0
    assert graph.meta["uses"]["unresolved_property_reads"] == 1
    untyped = next(n for n in graph.nodes if n.id == "function:lib.py::untyped")
    unresolved = [(u["text"], u["reason"][:4]) for u in untyped.properties["unresolved_calls"]]
    assert unresolved == [("getattr(holder, NAME).size", "屬性存取")]


def test_a_failing_command_is_reported_not_hidden(tmp_path):
    (tmp_path / "boom.py").write_text("def f():\n    raise SystemExit(3)\n\n\nf()\n")
    observed = record(tmp_path, ["boom.py"])
    assert observed["returncode"] == 3
    assert [p["callee"]["name"] for p in observed["pairs"]] == ["f"]
