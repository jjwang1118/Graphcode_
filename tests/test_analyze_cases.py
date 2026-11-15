"""稽核（2026-11-15）發現的問題 B1–B9 與測試缺口。每個案例自建一個小專案。"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codegraph_fable.analyze import analyze
from codegraph_fable.store import load

FIXTURE = Path(__file__).parent / "fixtures" / "p2"


def make(base: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return base


def dist_info(name: str, top: str) -> dict[str, str]:
    folder = f"{name.replace('-', '_')}-1.0.dist-info"
    return {
        f"{folder}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n",
        f"{folder}/top_level.txt": f"{top}\n",
    }


def node(graph, node_id):
    return next(n for n in graph.nodes if n.id == node_id)


def edges(graph, source, module):
    return [
        e
        for e in graph.edges
        if e.type == "imports" and e.source == f"file:{source}" and e.properties["module"] == module
    ]


def test_b1_packages_in_a_virtualenv_inside_the_project_are_third_party(tmp_path):
    project = make(
        tmp_path / "proj",
        {
            "main.py": "import fakepkg\n",
            ".venv/pyvenv.cfg": "home = /usr/bin\n",
            ".venv/site/fakepkg/__init__.py": "",
            **{f".venv/site/{k}": v for k, v in dist_info("fakepkg", "fakepkg").items()},
        },
    )
    graph = analyze(project, extra_paths=[project / ".venv/site"], engine_check=False)
    props = node(graph, "ext:fakepkg").properties
    assert props["category"] == "third_party"
    assert props["distributions"] == ["fakepkg"]
    assert graph.meta["imports"]["excluded"] == 0


def test_b2_relative_import_in_a_file_outside_the_given_roots(tmp_path):
    project = make(
        tmp_path / "proj",
        {
            "src/pkg/__init__.py": "",
            "tools/__init__.py": "",
            "tools/x.py": "from . import y\n",
            "tools/y.py": "",
        },
    )
    graph = analyze(project, roots=[project / "src"], engine_check=False)
    assert graph.meta["search_roots"] == ["src"]
    assert [e.target for e in edges(graph, "tools/x.py", ".")] == ["file:tools/y.py"]


def test_b3_project_installed_in_its_own_environment_does_not_shadow_itself(tmp_path):
    project = make(tmp_path / "proj", {"mypkg/__init__.py": "", "main.py": "import mypkg\n"})
    site = make(tmp_path / "site", dist_info("mypkg", "mypkg"))
    # 模擬 `pip install -e .`：環境路徑裡有專案根，已安裝清單裡有自己
    graph = analyze(project, extra_paths=[site, project], engine_check=False)
    (edge,) = edges(graph, "main.py", "mypkg")
    assert edge.target == "file:mypkg/__init__.py"
    assert "shadows" not in edge.properties
    assert graph.meta["imports"]["shadowing"] == 0


def test_b4_declared_but_not_installed_with_a_different_import_name(tmp_path):
    project = make(
        tmp_path / "proj", {"main.py": "import cv2\n", "requirements.txt": "opencv-python\n"}
    )
    props = node(analyze(project, engine_check=False), "ext:cv2").properties
    assert props["category"] == "third_party"
    assert (props["declared"], props["installed"]) == (True, False)
    assert props["distributions"] == ["opencv-python"]
    assert props["distribution_source"] == "known_alias"


def test_b5_alt_target_always_points_to_an_existing_node():
    graph = analyze(FIXTURE / "project", extra_paths=[FIXTURE / "site"], engine_check=False)
    ids = {n.id for n in graph.nodes}
    targets = [e.properties["alt_target"] for e in graph.edges if "alt_target" in e.properties]
    assert targets and all(t in ids for t in targets)
    assert node(graph, "ext:yaml").properties["category"] == "third_party"


def test_b6_excluded_submodule_is_reported_as_excluded_not_missing(tmp_path):
    project = make(
        tmp_path / "proj",
        {"mylib/__init__.py": "", "mylib/dist/gen.py": "", "main.py": "import mylib.dist.gen\n"},
    )
    graph = analyze(project, engine_check=False)
    (item,) = graph.meta["unresolved_imports"]
    assert "排除" in item["reason"]


def test_b7_requirement_lines_that_are_urls_are_not_package_names(tmp_path):
    requirements = (
        "git+https://github.com/x/y.git\n"
        "foo @ https://example.com/foo-1.0.whl\n"
        "bar[extra]>=1 ; python_version > '3'\n"
        "-r other.txt\n"
        "./local/path\n"
    )
    project = make(tmp_path / "proj", {"main.py": "", "requirements.txt": requirements})
    assert analyze(project, engine_check=False).meta["missing_dependencies"] == ["bar", "foo"]


@pytest.mark.skipif(sys.platform == "win32", reason="winreg 在 Windows 上存在")
def test_b8_stdlib_module_missing_on_this_platform_is_not_installed(tmp_path):
    project = make(tmp_path / "proj", {"main.py": "import winreg\nimport json\n"})
    graph = analyze(project, engine_check=False)
    assert node(graph, "ext:winreg").properties == {"category": "stdlib", "installed": False}
    assert node(graph, "ext:json").properties == {"category": "stdlib", "installed": True}


def test_b9_package_named_build_is_kept_but_build_output_is_ignored(tmp_path):
    project = make(
        tmp_path / "proj",
        {
            "pkg/__init__.py": "",
            "pkg/build/__init__.py": "",
            "pkg/build/steps.py": "",
            "build/lib/out.py": "",
            "main.py": "import pkg.build.steps\n",
        },
    )
    graph = analyze(project, engine_check=False)
    assert [e.target for e in edges(graph, "main.py", "pkg.build.steps")] == [
        "file:pkg/build/steps.py"
    ]
    assert not any(n.id.startswith(("dir:build", "file:build")) for n in graph.nodes)


def test_startup_stdlib_module_cannot_be_shadowed_by_a_root_file(tmp_path):
    project = make(tmp_path / "proj", {"os.py": "", "main.py": "import os\n"})
    graph = analyze(project, engine_check=False)
    (edge,) = edges(graph, "main.py", "os")
    assert edge.target == "ext:os"
    assert "shadows" not in edge.properties


def test_namespace_package_import_targets_a_directory_node(tmp_path):
    project = make(tmp_path / "proj", {"ns/sub/leaf.py": "", "main.py": "import ns.sub\n"})
    graph = analyze(project, engine_check=False)
    assert [e.target for e in edges(graph, "main.py", "ns.sub")] == ["dir:ns/sub"]


def test_pyproject_dependencies_are_read(tmp_path):
    pyproject = '[project]\nname = "x"\ndependencies = ["notthere-pkg>=2"]\n'
    project = make(
        tmp_path / "proj", {"main.py": "import notthere_pkg\n", "pyproject.toml": pyproject}
    )
    graph = analyze(project, engine_check=False)
    assert graph.meta["missing_dependencies"] == ["notthere-pkg"]
    assert node(graph, "ext:notthere_pkg").properties["category"] == "third_party"


def test_engine_can_be_disabled(tmp_path):
    graph = analyze(make(tmp_path / "proj", {"main.py": "import json\n"}), engine_check=False)
    assert graph.meta["engine"]["available"] is False


def test_command_line_writes_a_loadable_result(tmp_path):
    project = make(tmp_path / "proj", {"main.py": "import json\n"})
    output = tmp_path / "graph.json"
    completed = subprocess.run(
        [sys.executable, "-m", "codegraph_fable.analyze", str(project), "-o", str(output)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(completed.stdout)["imports"]["total"] == 1
    assert {n.id for n in load(output).nodes} >= {"file:main.py", "ext:json"}


def test_names_imported_from_an_uninstalled_package_still_link_to_it(tmp_path):
    source = (
        "import nopkg.sub as ns\n"
        "from nopkg import Thing, make\n\n\n"
        "class A(Thing):\n    pass\n\n\n"
        "def f(make_arg):\n    ns.run()\n    return make()\n\n\n"
        "def g(make):\n    return make()\n"
    )
    graph = analyze(make(tmp_path / "proj", {"main.py": source}), engine_check=False)

    def out(kind, source_id):
        return {
            (
                e.target,
                e.properties.get("callee") or e.properties.get("base"),
                e.properties["evidence"],
            )
            for e in graph.edges
            if e.type == kind and e.source == source_id
        }

    assert out("inherits", "class:main.py::A") == {("ext:nopkg", "nopkg.Thing", "import")}
    assert out("calls", "function:main.py::f") == {
        ("ext:nopkg", "nopkg.sub.run", "import"),
        ("ext:nopkg", "nopkg.make", "import"),
    }
    assert out("calls", "function:main.py::g") == set()  # 參數蓋掉了 import 的名字
    assert graph.meta["uses"]["calls"]["unresolved"] == 1


def test_classes_matching_a_protocol_override_its_methods(tmp_path):
    source = (
        "from typing import Protocol\n\n\n"
        "class Resolver(Protocol):\n    def target(self, name): ...\n\n\n"
        "class PythonResolver:\n    def target(self, name):\n        return name\n\n\n"
        "class Unrelated:\n    def other(self):\n        return 1\n\n\n"
        "def use(resolver: Resolver):\n    return resolver.target('x')\n"
    )
    graph = analyze(make(tmp_path / "proj", {"main.py": source}), engine_check=False)
    overrides = [(e.source, e.target, e.properties) for e in graph.edges if e.type == "overrides"]
    assert overrides == [
        (
            "function:main.py::PythonResolver.target",
            "function:main.py::Resolver.target",
            {"via": "protocol"},
        )
    ]
    # 改 PythonResolver.target 會影響經由 Protocol 呼叫它的 use()
    from codegraph_fable.query import Index, impact

    result = impact(Index(graph), "function:main.py::PythonResolver.target")
    assert [(e["id"], e["relation"], e["certainty"]) for e in result["levels"][0]] == [
        ("function:main.py::use", "dispatch", "possible")
    ]
