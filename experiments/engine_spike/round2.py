"""Round 2: Jedi with guessing disabled (smart_sys_path=False) and explicit roots = [project root] + env sys.path."""
import os
import sys
from pathlib import Path
import jedi
from spike import PROJ, VENV, markers, short

# 真實專案放在哪裡：用環境變數指定，不把本機路徑寫進程式
T = Path(os.environ.get("CODEGRAPH_EVAL_TARGETS", "targets"))
env = jedi.create_environment(str(VENV), safe=False)
ENV_PATH = [p for p in env.get_sys_path() if p]


def fmt(ds, root):
    return sorted({(short(d.module_path) if root == PROJ else str(d.module_path).replace(str(T), "LOCAL").replace(str(VENV), "SITE"))
                   + f":{d.line}" for d in ds}) or "UNRESOLVED"


def resolve(root, p, line, col, strict):
    if strict:
        pr = jedi.Project(str(root), environment_path=str(VENV), sys_path=[str(root)] + ENV_PATH, smart_sys_path=False)
    else:
        pr = jedi.Project(str(root), environment_path=str(VENV))
    s = jedi.Script(path=str(p), project=pr, environment=env)
    return fmt(s.goto(line, col, follow_imports=True, follow_builtin_imports=True), root), pr


print("ENV sys.path:", [short(p) for p in ENV_PATH])
print("\n== fixture: all markers, default vs strict (only differences + P2 cases shown) ==")
same = 0
for p, line, col, tok, case in markers():
    a, _ = resolve(PROJ, p, line, col, False)
    b, pr = resolve(PROJ, p, line, col, True)
    name = case.split(":")[0][:30]
    if a != b or any(k in name for k in ("shadow", "dirpkg", "sibling", "entrypoint", "syspath", "src_layout", "namespace")):
        print(f"{'DIFF' if a != b else 'same'} {name:30} default={a}\n     {'':30} strict ={b}")
    else:
        same += 1
print(f"(other markers identical: {same})")

print("\n== real cases, strict ==")
for root, rel, line, tok in [
    ("envharness", "envharness/bridges/alfworld/bridge.py", 519, "alfworld"),
    ("envharness", "envharness/bridges/alfworld/bridge.py", 495, "environment"),
    ("envharness", "envharness/prompts/webarena_reasoning_bank_agent.py", 122, "dynamic_prompting"),
    ("envharness", "scripts/run_harness.py", 73, "yaml"),
    ("envharness", "scripts/run_harness.py", 87, "LiteLLMClient"),
    ("foreman", "src/foreman/decision_models/openai.py", 85, "AsyncOpenAI"),
    ("foreman", "tests/test_decision_models.py", 9, "AsyncOpenAI"),
]:
    p = T / root / rel
    col = p.read_text().splitlines()[line - 1].rfind(tok)
    print(f"{root}/{rel}:{line} {tok}\n     default={resolve(T / root, p, line, col, False)[0]}\n     strict ={resolve(T / root, p, line, col, True)[0]}")
