"""T7 後端的驗收：畫面用的收合視圖與 HTTP API。"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codegraph_fable.analyze import analyze
from codegraph_fable.query import Index, locate, view
from codegraph_fable.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"
USE, MODELS, UTIL = "file:app/use.py", "file:app/models.py", "file:app/util.py"


@pytest.fixture(scope="module")
def index():
    return Index(analyze(FIXTURES / "calls" / "project", engine_check=False))


def _edges(result, kind):
    return {(e["source"], e["target"]): e["count"] for e in result["edges"] if e["type"] == kind}


def _ids(result):
    return {n["id"] for n in result["nodes"]}


def test_level_controls_how_much_is_shown(index):
    assert _ids(view(index, level=0)) == {"repo:.", "extgroup:stdlib"}  # 整個專案是一個點
    assert _ids(view(index, level=1)) == {"repo:.", "dir:app", "extgroup:stdlib"}
    second = _ids(view(index, level=2))
    assert {USE, UTIL, "dir:app/pkg"} <= second and "function:app/util.py::helper" not in second
    everything = _ids(view(index, level=None))  # 不收合：看得到 function
    assert {"function:app/util.py::helper", "file:app/pkg/impl.py"} <= everything


def test_collapsed_nodes_carry_the_edges_of_what_they_hide(index):
    result = view(index, level=1)
    assert _edges(result, "contains") == {("repo:.", "dir:app"): 1}  # 骨架
    assert _edges(result, "imports") == {("dir:app", "extgroup:stdlib"): 1}  # use.py 的 import os
    assert ("dir:app", "extgroup:stdlib") in _edges(result, "calls")
    assert result["meta"]["visible_nodes"] == 3 < result["meta"]["total_nodes"]


def test_expanding_splits_the_edges_onto_the_children(index):
    result = view(index, level=2)
    by_id = {n["id"]: n for n in result["nodes"]}
    assert by_id["dir:app"]["expanded"] is True and by_id["dir:app"]["parent"] == "repo:."
    assert by_id[USE]["parent"] == "dir:app" and by_id[USE]["expanded"] is False
    assert by_id[USE]["children"] > 0
    assert _edges(result, "imports")[(USE, UTIL)] == 1
    used = sum(_edges(result, kind).get((USE, UTIL), 0) for kind in ("calls", "references"))
    assert used == 6  # 實際使用的次數
    assert (USE, "dir:app/pkg") in _edges(result, "imports")  # pkg 還沒展開：線接到資料夾
    assert ("dir:app", "extgroup:stdlib") not in _edges(result, "imports")  # 改由裡面的檔案接出去


def test_user_can_expand_and_collapse_on_top_of_the_level(index):
    opened = view(index, [UTIL], level=2)
    by_id = {n["id"]: n for n in opened["nodes"]}
    helper = by_id["function:app/util.py::helper"]
    assert helper["parent"] == UTIL and helper["signature"] == "()" and helper["line"] == 4
    assert _edges(opened, "defines")[(UTIL, "function:app/util.py::helper")] == 1
    assert (USE, "function:app/util.py::helper") in _edges(opened, "calls")
    # 檔案與自己裡面的定義之間只有骨架線
    assert (UTIL, "function:app/util.py::helper") not in _edges(opened, "references")
    closed = view(index, level=2, collapsed=["dir:app"])
    assert _ids(closed) == {"repo:.", "dir:app", "extgroup:stdlib"}


def test_externals_modes(index):
    grouped = view(index, ["extgroup:stdlib"])
    by_id = {n["id"]: n for n in grouped["nodes"]}
    assert (
        by_id["ext:os"]["parent"] == "extgroup:stdlib" and by_id["ext:os"]["category"] == "stdlib"
    )
    full = view(index, externals="full")
    assert {"ext:os", "ext:builtins"} <= _ids(full) and "extgroup:stdlib" not in _ids(full)
    hidden = view(index, externals="hidden")
    assert _ids(hidden) == {"repo:.", "dir:app"}
    assert {e["type"] for e in hidden["edges"]} == {"contains"}


def test_edge_types_filter(index):
    result = view(index, level=2, edge_types=["inherits"])
    assert set(_edges(result, "inherits")) == {(USE, MODELS), (USE, "extgroup:stdlib")}
    assert {e["type"] for e in result["edges"]} == {"contains", "inherits"}


def test_unresolved_calls_are_counted_on_the_node(index):
    by_id = {n["id"]: n for n in view(index, [USE], level=2)["nodes"]}
    assert by_id["function:app/use.py::dynamic"]["unresolved_calls"] == 2
    assert "unresolved_calls" not in by_id["function:app/use.py::alias"]


def test_locate_maps_hidden_nodes_to_their_visible_ancestor(index):
    ids = ["function:app/util.py::helper", "ext:os", UTIL]
    assert locate(index, [], ids, level=2) == {
        "function:app/util.py::helper": UTIL,
        "ext:os": "extgroup:stdlib",
        UTIL: UTIL,
    }
    assert locate(index, [], ids, level=0)[UTIL] == "repo:."
    assert index.ancestors("function:app/models.py::Foo.go") == [
        "class:app/models.py::Foo",
        MODELS,
        "dir:app",
        "repo:.",
    ]


@pytest.fixture
def client(tmp_path):
    project = shutil.copytree(FIXTURES / "calls" / "project", tmp_path / "allowed" / "proj")
    app = create_app(allowed_roots=[str(tmp_path / "allowed")])
    return TestClient(app), str(project), tmp_path


def test_paths_outside_the_allowlist_are_rejected(client):
    http, project, tmp_path = client
    outside = tmp_path / "outside"
    outside.mkdir()
    assert http.post("/api/view", json={"project": str(outside)}).status_code == 403
    assert http.post("/api/view", json={"project": project}).status_code == 200
    assert http.post("/api/view", json={"project": project + "/nope"}).status_code == 404
    nothing_allowed = TestClient(create_app(allowed_roots=[]))
    response = nothing_allowed.post("/api/view", json={"project": project})
    assert response.status_code == 403 and "尚未設定" in response.json()["detail"]


def test_api_round_trip(client):
    http, project, _ = client
    analyzed = http.post("/api/analyze", json={"project": project}).json()
    assert (
        analyzed["source"].startswith("analyzed") and analyzed["uses"]["calls"]["unresolved"] == 4
    )
    found = http.post("/api/find", json={"project": project, "name": "helper"}).json()
    assert found[0]["id"] == "function:app/util.py::helper"
    assert found[0]["ancestors"] == [UTIL, "dir:app", "repo:."]
    shown = http.post("/api/view", json={"project": project, "level": 2}).json()
    assert USE in {n["id"] for n in shown["nodes"]}
    everything = http.post("/api/view", json={"project": project, "level": None}).json()
    assert "function:app/util.py::helper" in {n["id"] for n in everything["nodes"]}
    body = {"project": project, "target": found[0]["id"], "level": 2}
    affected = http.post("/api/impact", json=body).json()
    assert affected["completeness"]["affected"] == 6
    assert affected["visible"]["function:app/models.py::Helper.work"] == MODELS
    info = http.post("/api/detail", json={"project": project, "target": found[0]["id"]}).json()
    assert info["interface"]["signature"] == "()" and "return LIMIT" in info["source"]["text"]
    assert http.post("/api/detail", json={"project": project, "target": "x"}).status_code == 404
    assert http.post("/api/overview", json={"project": project}).json()["packages"] == {"app": 6}
