"""Read-only probe of the reference's known-wrong cases (resolve.md 9.1) with both engines.
Env = spike venv (openai installed, alfworld NOT installed)."""
import os, sys
from pathlib import Path
import jedi
from spike import LSP, VENV

# 真實專案放在哪裡：用環境變數指定，不把本機路徑寫進程式
T = Path(os.environ.get("CODEGRAPH_EVAL_TARGETS", "targets"))
CASES = [  # (project root, file, line, token)
    ("foreman", "src/foreman/decision_models/openai.py", 85, "AsyncOpenAI"),
    ("foreman", "tests/test_decision_models.py", 9, "AsyncOpenAI"),
    ("envharness", "envharness/bridges/alfworld/bridge.py", 519, "alfworld"),
    ("envharness", "envharness/bridges/alfworld/bridge.py", 495, "environment"),
    ("envharness", "envharness/prompts/webarena_reasoning_bank_agent.py", 122, "dynamic_prompting"),
    ("envharness", "scripts/run_harness.py", 73, "yaml"),
]
def sh(p):
    return str(p).replace(str(T), "LOCAL").replace(str(VENV), "SITE").replace("file://", "")
for root, rel, line, tok in CASES:
    p = T / root / rel
    col = p.read_text().splitlines()[line - 1].rfind(tok)
    pr = jedi.Project(str(T / root), environment_path=str(VENV))
    g = jedi.Script(path=str(p), project=pr).goto(line, col, follow_imports=True)
    print(f"JEDI    {root}/{rel}:{line} {tok} -> {[f'{sh(d.module_path)}:{d.line}' for d in g] or 'UNRESOLVED'}")
for root in ("foreman", "envharness"):
    r = T / root
    ls = LSP([str(VENV / "bin" / "pyright-langserver"), "--stdio"], str(r))
    ls.request("initialize", {"processId": os.getpid(), "rootUri": r.as_uri(), "capabilities": {},
               "initializationOptions": {}, "workspaceFolders": [{"uri": r.as_uri(), "name": root}]})
    ls.notify("initialized", {})
    ls.notify("workspace/didChangeConfiguration", {"settings": {"python": {"pythonPath": str(VENV / "bin/python")}}})
    for root2, rel, line, tok in CASES:
        if root2 != root:
            continue
        p = r / rel
        col = p.read_text().splitlines()[line - 1].rfind(tok)
        ls.notify("textDocument/didOpen", {"textDocument": {"uri": p.as_uri(), "languageId": "python", "version": 1, "text": p.read_text()}})
        d = ls.request("textDocument/definition", {"textDocument": {"uri": p.as_uri()}, "position": {"line": line - 1, "character": col}}) or []
        print(f"PYRIGHT {root}/{rel}:{line} {tok} -> {sorted({sh(x['uri']) + ':' + str(x['range']['start']['line'] + 1) for x in d}) or 'UNRESOLVED'}")
    ls.request("shutdown", None); ls.notify("exit", None)
