"""T6 的驗收：存檔與過期判斷、文字輸出、經 MCP 協定實際呼叫。"""

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from codegraph_fable.mcp import render
from codegraph_fable.query import detail, impact, overview
from codegraph_fable.service import Service, detect_python

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def project(tmp_path):
    return shutil.copytree(FIXTURES / "calls" / "project", tmp_path / "proj")


def test_result_is_stored_in_the_project_and_reused(project):
    service = Service()
    _, first = service.index(str(project))
    assert first.startswith("analyzed")
    assert (project / ".codegraph" / "graph.json").is_file()
    assert (project / ".codegraph" / ".gitignore").read_text() == "*\n"
    assert service.index(str(project))[1] == "cached"
    assert Service().index(str(project))[1] == "loaded"  # 另一個行程：從存檔讀


def test_changed_source_triggers_reanalysis(project):
    service = Service()
    index, _ = service.index(str(project))
    assert not index.find("brand_new")
    (project / "app" / "util.py").write_text("def brand_new():\n    return 1\n")
    index, source = service.index(str(project))
    assert source.startswith("analyzed（原始碼或設定已變動")
    assert [n.id for n in index.find("brand_new")] == ["function:app/util.py::brand_new"]
    assert Service().index(str(project))[1] == "loaded"


def test_stored_result_is_not_scanned_as_part_of_the_project(project):
    service = Service()
    service.index(str(project))
    index, source = service.index(str(project), force=True)
    assert source.startswith("analyzed（強制")
    assert not any(".codegraph" in n.id for n in index.graph.nodes)


def test_missing_project_and_python_detection(tmp_path, project):
    with pytest.raises(FileNotFoundError):
        Service().index(str(tmp_path / "nope"))
    assert detect_python(project) is None
    fake = project / ".venv" / "bin" / "python"
    fake.parent.mkdir(parents=True)
    fake.write_text("")
    assert detect_python(project) == str(fake)


@pytest.fixture(scope="module")
def calls_index(tmp_path_factory):
    target = tmp_path_factory.mktemp("calls") / "proj"
    shutil.copytree(FIXTURES / "calls" / "project", target)
    return Service().index(str(target))[0]


def test_impact_text_separates_certain_possible_and_candidates(calls_index):
    text = render.render_impact(impact(calls_index, "function:app/util.py::helper"))
    assert "受影響 6（確定 6、可能 0）；候選 2" in text
    assert "[確定] calls ← function app/models.py::Helper.work L14" in text
    assert "第 3 層（1）" in text
    assert "`getattr(util, 'helper')`" in text
    assert "有 4 個呼叫解不出" in text
    possible = render.render_impact(impact(calls_index, "function:app/models.py::Foo.step"))
    assert "[可能] dispatch ← function app/models.py::Base.run" in possible


def test_impact_text_states_the_total_when_truncated(calls_index):
    text = render.render_impact(impact(calls_index, "function:app/util.py::helper"), limit=2)
    assert "只列出 2 筆，共 6 筆" in text


def test_detail_text_labels_reliability(tmp_path):
    target = shutil.copytree(FIXTURES / "effects" / "project", tmp_path / "proj")
    index = Service().index(str(target))[0]
    text = render.render_detail(detail(index, "function:app/effects.py::outer"))
    assert "介面【準確】 (path)" in text
    assert "呼叫【推論；依原始碼位置，非執行順序】" in text
    assert "專案內 function app/effects.py::cleanup L29" in text
    assert "直接：console（builtins.print）" in text
    assert "os.remove 於 cleanup" in text and "副作用【估計" in text
    assert text.rstrip().endswith('print("done")')
    no_source = render.render_detail(detail(index, "function:app/effects.py::outer"), False)
    assert 'print("done")' not in no_source
    saved = render.render_detail(detail(index, "function:app/effects.py::Store.save"))
    assert "讀：count；寫：last；寫入全域變數：TOTAL" in saved
    assert "例外【準確；只含明寫的 raise】：ValueError" in saved


def test_overview_and_summary_text(calls_index):
    text = render.render_overview(overview(calls_index))
    assert "app: 6" in text and "外部套件 stdlib（2）：builtins, os" in text
    assert "共 24 個呼叫，解出 20，解不出 4" in text
    summary = render.render_summary(calls_index, "loaded")
    assert "分析結果來源：loaded" in summary and "import：共 8" in summary


def test_tools_over_the_mcp_protocol(project):
    """真的啟動伺服器行程，用 MCP 客戶端列出並呼叫工具。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "codegraph_fable.mcp"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)

            async def call(tool, **arguments):
                result = await session.call_tool(tool, {"project": str(project), **arguments})
                return "\n".join(c.text for c in result.content if hasattr(c, "text"))

            return names, {
                "analyze": await call("analyze"),
                "find": await call("find", name="helper"),
                "impact": await call("impact", target="helper", depth=1),
                "ambiguous": await call("impact", target="step"),
                "detail": await call("detail", target="Foo.go", source=False),
                "missing": await call("detail", target="no_such_thing"),
                "overview": await call("overview"),
            }

    names, out = asyncio.run(run())
    assert names == ["analyze", "detail", "find", "impact", "overview"]
    assert "分析結果來源：analyzed" in out["analyze"]
    assert "function app/util.py::helper" in out["find"]
    assert "第 1 層（4）" in out["impact"] and "第 2 層" not in out["impact"]
    assert "有多個同名的定義" in out["ambiguous"] and "Foo.step" in out["ambiguous"]
    assert "專案內 function app/models.py::Helper.work L25" in out["detail"]
    assert "找不到 `no_such_thing`" in out["missing"]
    assert "被最多檔案依賴" in out["overview"]
