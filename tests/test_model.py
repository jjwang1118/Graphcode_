import pytest

from codegraph_fable.model import Edge, Graph, GraphError, Node, decl_id, ext_id, file_id
from codegraph_fable.store import load, save


def _graph() -> Graph:
    return Graph(
        nodes=[Node("file:a.py", "file", "a.py"), Node("ext:os", "external_package", "os")],
        edges=[Edge("file:a.py", "ext:os", "imports", {"line": 1})],
        meta={"schema_version": 1},
    )


def test_ids():
    assert file_id("src/app.py") == "file:src/app.py"
    assert ext_id("yaml") == "ext:yaml"
    assert decl_id("function", "src/app.py", "Runner.run") == "function:src/app.py::Runner.run"


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "graph.json"
    save(_graph(), path)
    assert load(path).to_dict() == _graph().to_dict()


def test_duplicate_node_id_is_rejected():
    graph = _graph()
    graph.nodes.append(Node("file:a.py", "file", "a.py"))
    with pytest.raises(GraphError):
        graph.validate()


def test_edge_to_missing_node_is_rejected():
    graph = _graph()
    graph.edges.append(Edge("file:a.py", "file:missing.py", "imports"))
    with pytest.raises(GraphError):
        graph.validate()
