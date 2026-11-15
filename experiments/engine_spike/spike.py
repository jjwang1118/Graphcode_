"""Throwaway spike: how do Jedi and pyright resolve marked use sites in fixtures/proj?

Run:  .venv/bin/python spike.py [jedi|pyright|runtime|all]
Markers in fixtures:  <code>  #@ <token> | <case name>: note
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE / "fixtures" / "proj"
VENV = HERE / ".venv"
MARK = re.compile(r"#@\s*(\S+)\s*\|\s*(.*)$")


def markers():
    out = []
    for p in sorted(PROJ.rglob("*.py")):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            m = MARK.search(line)
            if not m:
                continue
            tok = m.group(1)
            col = line[: m.start()].rfind(tok)
            out.append((p, i, col, tok, m.group(2)))
    return out


def short(path):
    if path is None:
        return "<builtin/none>"
    s = str(path)
    for root, tag in ((str(PROJ), "LOCAL:"), (str(VENV), "SITE:")):
        if s.startswith(root):
            return tag + s[len(root) + 1:].replace("lib/python3.13/site-packages/", "")
    if "typeshed" in s:
        return "TYPESHED:" + s.split("typeshed", 1)[1].lstrip("-fallback/")
    return "STDLIB/OTHER:" + s.split("/lib/", 1)[-1]


def run_jedi(extra_sys_path=()):
    import jedi
    env = jedi.create_environment(str(VENV), safe=False)
    kw = {}
    if extra_sys_path:
        kw["added_sys_path"] = [str(PROJ / e) for e in extra_sys_path]
    project = jedi.Project(str(PROJ), environment_path=str(VENV), **kw)
    print(f"\n== JEDI {jedi.__version__}  added_sys_path={list(extra_sys_path)} ==")
    for p, line, col, tok, case in markers():
        s = jedi.Script(path=str(p), project=project, environment=env)
        try:
            g = s.goto(line, col, follow_imports=True, follow_builtin_imports=True)
            inf = s.infer(line, col)
        except Exception as e:  # noqa: BLE001
            print(f"{case[:28]:28} ERROR {e!r}")
            continue
        fmt = lambda ds: sorted({f"{short(d.module_path)}:{d.line}({d.type} {d.full_name})" for d in ds})
        print(f"{case.split(':')[0][:26]:26} goto={fmt(g) or 'NONE'}")
        if fmt(inf) != fmt(g):
            print(f"{'':26} infer={fmt(inf) or 'NONE'}")


class LSP:
    def __init__(self, cmd, root):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, cwd=root)
        self.id = 0

    def send(self, obj):
        b = json.dumps(obj).encode()
        self.p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b)
        self.p.stdin.flush()

    def read(self):
        n = 0
        while True:
            h = self.p.stdout.readline().strip()
            if not h:
                break
            if h.lower().startswith(b"content-length"):
                n = int(h.split(b":")[1])
        return json.loads(self.p.stdout.read(n))

    def request(self, method, params):
        self.id += 1
        me = self.id
        self.send({"jsonrpc": "2.0", "id": me, "method": method, "params": params})
        while True:
            m = self.read()
            if "method" in m and "id" in m:  # server -> client request
                res = [None] * len(m["params"].get("items", [])) if m["method"] == "workspace/configuration" else None
                self.send({"jsonrpc": "2.0", "id": m["id"], "result": res})
            elif m.get("id") == me:
                return m.get("result")

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})


def run_pyright():
    ls = LSP([str(VENV / "bin" / "pyright-langserver"), "--stdio"], str(PROJ))
    ls.request("initialize", {"processId": os.getpid(), "rootUri": PROJ.as_uri(), "capabilities": {},
                              "workspaceFolders": [{"uri": PROJ.as_uri(), "name": "proj"}]})
    ls.notify("initialized", {})
    print("\n== PYRIGHT (langserver: definition / hover) ==")
    opened = set()
    for p, line, col, tok, case in markers():
        if p not in opened:
            ls.notify("textDocument/didOpen", {"textDocument": {"uri": p.as_uri(), "languageId": "python",
                                                                "version": 1, "text": p.read_text()}})
            opened.add(p)
        pos = {"textDocument": {"uri": p.as_uri()}, "position": {"line": line - 1, "character": col}}
        d = ls.request("textDocument/definition", pos) or []
        if isinstance(d, dict):
            d = [d]
        locs = sorted({f"{short(x['uri'].replace('file://', ''))}:{x['range']['start']['line'] + 1}" for x in d})
        hov = ls.request("textDocument/hover", pos)
        htxt = ""
        if hov:
            htxt = hov["contents"]["value"] if isinstance(hov["contents"], dict) else str(hov["contents"])
            htxt = " ".join(htxt.replace("```python", "").replace("```", "").split())[:110]
        print(f"{case.split(':')[0][:26]:26} def={locs or 'NONE'}\n{'':26} hover={htxt!r}")
    ls.request("shutdown", None)
    ls.notify("exit", None)


def run_runtime():
    """Ground truth: which file does real Python pick, per entry point?"""
    py = str(VENV / "bin" / "python")
    probe = "import {m}; print('{m} ->', getattr({m}, '__file__', None))"
    cases = [
        ("cwd=proj, python -c (sys.path[0]='')", PROJ, ["-c", ";".join([
            "import yaml,openai,types", "print('yaml ->',yaml.__file__)", "print('openai ->',openai.__file__)",
            "print('types ->',types.__file__)",
            "import importlib.util as u", "print('srcpkg spec ->', u.find_spec('srcpkg'))",
            "import nsdir.sub.leaf as l; print('nsdir.sub.leaf ->', l.__file__)"])]),
        ("python scripts/run.py (sys.path[0]=scripts)", PROJ, ["-c",
            "import runpy,sys; sys.argv=['scripts/run.py']; sys.path[0]='scripts'; "
            "g=runpy.run_path('scripts/run.py'); print('yaml ->', g['yaml'].__file__); "
            "print('inner_fn ->', g['inner_fn'].__code__.co_filename)"]),
        ("python app/openai.py as SCRIPT (sys.path[0]=app)", PROJ, ["app/openai.py"]),
        ("python app/use_cases.py as SCRIPT (sys.path[0]=app)", PROJ, ["-c",
            "import sys; sys.path[0]='app'; import types, openai; print('types ->',types.__file__); print('openai ->',openai.__file__)"]),
        ("python -m pytest style: rootdir on path, tests/test_x imports", PROJ, ["-c",
            "import sys; sys.path.insert(0,'tests'); import openai; print('openai ->', openai.__file__)"]),
    ]
    print("\n== RUNTIME GROUND TRUTH ==")
    for name, cwd, args in cases:
        r = subprocess.run([py, *args], cwd=cwd, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip().splitlines()
        print(f"-- {name}")
        for ln in out[-7:]:
            print("   ", ln.replace(str(PROJ), "LOCAL").replace(str(VENV), "SITE"))


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("runtime", "all"):
        run_runtime()
    if what in ("jedi", "all"):
        run_jedi()
        run_jedi(extra_sys_path=("src",))
    if what in ("pyright", "all"):
        run_pyright()


def jedi_enumerate(rel="app/use_cases.py"):
    """Can Jedi enumerate ALL names in a file and resolve each one (not point queries)?"""
    import jedi
    project = jedi.Project(str(PROJ), environment_path=str(VENV))
    s = jedi.Script(path=str(PROJ / rel), project=project)
    names = s.get_names(all_scopes=True, definitions=False, references=True)
    res = {"resolved": 0, "unresolved": 0, "multi": 0}
    unresolved = []
    for n in names:
        tgt = n.goto(follow_imports=True)
        if not tgt:
            res["unresolved"] += 1
            unresolved.append(f"{n.name}@{n.line}")
        else:
            res["multi" if len(tgt) > 1 else "resolved"] += 1
    print(f"\n== JEDI get_names(references=True) on {rel}: {len(names)} names -> {res}")
    print("   unresolved:", unresolved)
    # attribute names after a dot: are they in get_names at all?
    print("   includes attribute 'bar' uses:", sorted(n.line for n in names if n.name == "bar"))
    # reverse direction
    u = jedi.Script(path=str(PROJ / "app/util.py"), project=project)
    refs = u.get_references(3, 4, scope="project")
    print("   get_references(app.util.helper):", sorted(f"{short(r.module_path)}:{r.line}" for r in refs))


def pyright_extra():
    ls = LSP([str(VENV / "bin" / "pyright-langserver"), "--stdio"], str(PROJ))
    ls.request("initialize", {"processId": os.getpid(), "rootUri": PROJ.as_uri(), "capabilities": {},
                              "workspaceFolders": [{"uri": PROJ.as_uri(), "name": "proj"}]})
    ls.notify("initialized", {})
    def open_(rel):
        p = PROJ / rel
        ls.notify("textDocument/didOpen", {"textDocument": {"uri": p.as_uri(), "languageId": "python",
                                                            "version": 1, "text": p.read_text()}})
        return p
    def pos_of(rel, needle, tok):
        p = PROJ / rel
        for i, line in enumerate(p.read_text().splitlines()):
            if needle in line:
                return {"textDocument": {"uri": p.as_uri()}, "position": {"line": i, "character": line.find(tok)}}
    open_("app/use_cases.py"); open_("app/util.py"); open_("app/extras.py")
    print("\n== PYRIGHT callHierarchy/outgoingCalls ==")
    for rel, fn in [("app/use_cases.py", "union"), ("app/use_cases.py", "table"), ("app/use_cases.py", "alias"),
                    ("app/use_cases.py", "dyn"), ("app/use_cases.py", "unann"), ("app/use_cases.py", "cb"),
                    ("app/use_cases.py", "f"), ("app/extras.py", "t")]:
        items = ls.request("textDocument/prepareCallHierarchy", pos_of(rel, f"def {fn}(", fn)) or []
        outs = []
        for it in items:
            for o in ls.request("callHierarchy/outgoingCalls", {"item": it}) or []:
                t = o["to"]
                outs.append(f"{t['name']}@{short(t['uri'].replace('file://', ''))}:{t['range']['start']['line'] + 1}")
        print(f"   {fn:8} -> {sorted(outs)}")
    refs = ls.request("textDocument/references", {**pos_of("app/util.py", "def helper", "helper"),
                                                  "context": {"includeDeclaration": False}}) or []
    print("   references(app.util.helper):",
          sorted(f"{short(r['uri'].replace('file://', ''))}:{r['range']['start']['line'] + 1}" for r in refs))
    td = ls.request("textDocument/typeDefinition", pos_of("app/use_cases.py", "return fn()", "fn"))
    print("   typeDefinition(alias fn):", td)
    ls.request("shutdown", None); ls.notify("exit", None)


if __name__ == "__main__" and (sys.argv[1:] or ["all"])[0] in ("extra", "all"):
    jedi_enumerate()
    pyright_extra()
