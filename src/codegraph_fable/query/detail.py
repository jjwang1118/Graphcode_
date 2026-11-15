"""function 細節：它做了什麼。每一項都標可靠度。規格：docs/spec/query.md"""

from __future__ import annotations

import ast
import textwrap
import tokenize
from pathlib import Path
from typing import Any

from .index import Index, owner_file

EXACT = "exact"  # 直接從原始碼或確切解析得到
INFERRED = "inferred"  # 引擎推論，可能不完整
HEURISTIC = "heuristic"  # 靠對照表猜的

# 外部呼叫 → 副作用類別。結尾是 `.` 或 `_` 的是前綴比對，其餘要完全相同。
# 這張表是人工維護的估計，不是事實；沒列到的呼叫不代表沒有副作用。
SIDE_EFFECTS: list[tuple[str, str]] = [
    ("builtins.open", "file"), ("io.open", "file"), ("os.remove", "file"), ("os.unlink", "file"),
    ("os.rename", "file"), ("os.replace", "file"), ("os.mkdir", "file"), ("os.makedirs", "file"),
    ("os.rmdir", "file"), ("os.listdir", "file"), ("os.walk", "file"), ("os.scandir", "file"),
    ("shutil.", "file"), ("tempfile.", "file"), ("json.dump", "file"), ("json.load", "file"),
    ("pickle.dump", "file"), ("pickle.load", "file"),
    ("pathlib.Path.write_", "file"), ("pathlib.Path.read_", "file"), ("pathlib.Path.mkdir", "file"),
    ("pathlib.Path.unlink", "file"), ("pathlib.Path.open", "file"), ("pathlib.Path.touch", "file"),
    ("pathlib.Path.rename", "file"), ("pathlib.Path.rmdir", "file"),
    ("requests.", "network"), ("urllib.request.", "network"), ("httpx.", "network"),
    ("aiohttp.", "network"), ("socket.", "network"), ("http.client.", "network"),
    ("smtplib.", "network"), ("ftplib.", "network"),
    ("subprocess.", "process"), ("os.system", "process"), ("os.popen", "process"),
    ("os.kill", "process"), ("multiprocessing.", "process"),
    ("sqlite3.", "database"), ("sqlalchemy.", "database"), ("psycopg2.", "database"),
    ("pymysql.", "database"), ("redis.", "database"), ("pymongo.", "database"),
    ("builtins.print", "console"), ("builtins.input", "console"), ("logging.", "logging"),
    ("sys.exit", "exit"), ("os._exit", "exit"), ("builtins.exit", "exit"), ("builtins.quit", "exit"),
    ("os.getenv", "environment"), ("os.putenv", "environment"),
    ("builtins.eval", "dynamic_code"), ("builtins.exec", "dynamic_code"),
    ("builtins.__import__", "dynamic_code"), ("importlib.import_module", "dynamic_code"),
    ("time.sleep", "sleep"),
]  # fmt: skip


def side_effect(callee: str) -> str | None:
    # 引擎回報的名字可能帶實作模組（pathlib._local.Path）：去掉底線開頭的中間段
    parts = callee.split(".")
    name = ".".join(p for i, p in enumerate(parts) if not p.startswith("_") or i == len(parts) - 1)
    for pattern, category in SIDE_EFFECTS:
        prefix = pattern.endswith((".", "_"))
        if (prefix and name.startswith(pattern)) or name == pattern:
            return category
    return None


def read_source(root: str, rel: str, line: int, end_line: int) -> str | None:
    try:
        with tokenize.open(Path(root) / rel) as handle:
            lines = handle.read().splitlines()
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    return "\n".join(lines[line - 1 : end_line])


def _body_facts(source: str, is_method: bool, decorators: list[str]) -> dict[str, Any] | None:
    """只看這個 function 自己的原始碼能確定的事。"""
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return None
    function = next(
        (n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None
    )
    if function is None:
        return None
    receiver = None
    if is_method and "staticmethod" not in decorators and function.args.args:
        receiver = function.args.args[0].arg
    callees = {id(n.func) for n in ast.walk(function) if isinstance(n, ast.Call)}
    reads, writes, global_writes, raises = set(), set(), set(), []
    returns = yields = 0
    for node in ast.walk(function):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == receiver:
                if isinstance(node.ctx, ast.Load):
                    if id(node) not in callees:  # self.method() 是呼叫，不是讀狀態
                        reads.add(node.attr)
                else:
                    writes.add(node.attr)
        elif isinstance(node, ast.Global):
            global_writes.update(node.names)
        elif isinstance(node, ast.Raise):
            if node.exc is None:
                raises.append("(重新丟出)")
            else:
                exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
                raises.append(ast.unparse(exc))
        elif isinstance(node, ast.Return) and node.value is not None:
            returns += 1
        elif isinstance(node, (ast.Yield, ast.YieldFrom)):
            yields += 1
    return {
        "receiver": receiver,
        "reads": sorted(reads),
        "writes": sorted(writes),
        "global_writes": sorted(global_writes),
        "raises": sorted(set(raises)),
        "returns": returns,
        "is_generator": yields > 0,
    }


def detail(index: Index, node_id: str) -> dict[str, Any]:
    """一個 function（或 class）的細節清單。每個區塊都有 reliability。"""
    node = index.nodes[node_id]
    props = node.properties
    rel = owner_file(node_id)
    result: dict[str, Any] = {
        "id": node_id,
        "type": node.type,
        "file": rel,
        "line": props.get("line"),
        "end_line": props.get("end_line"),
    }
    if node.type == "function":
        result["interface"] = {
            "reliability": EXACT,
            "signature": props.get("signature"),
            "decorators": props.get("decorators", []),
            "is_async": props.get("is_async", False),
            "is_method": props.get("is_method", False),
            "docstring": props.get("docstring"),
        }
    elif node.type == "class":
        result["interface"] = {
            "reliability": EXACT,
            "bases": props.get("bases", []),
            "docstring": props.get("docstring"),
            "members": sorted(e.target for e in index.outgoing(node_id, "defines")),
        }

    local_calls, external_calls, effects = [], [], {}
    for edge in index.outgoing(node_id, "calls"):
        extra = edge.properties
        if edge.target.startswith("ext:"):
            callee = extra.get("callee", edge.target[4:])
            external_calls.append({"callee": callee, "lines": extra["lines"]})
            category = side_effect(callee)
            if category:
                effects.setdefault(category, []).append({"callee": callee, "lines": extra["lines"]})
        else:
            entry: dict[str, Any] = {"target": edge.target, "lines": extra["lines"]}
            for key in ("via", "ambiguous"):
                if extra.get(key):
                    entry[key] = extra[key]
            local_calls.append(entry)
    result["calls"] = {
        "reliability": INFERRED,
        "note": "依原始碼出現的位置，不是執行順序；分支與迴圈不反映",
        "local": sorted(local_calls, key=lambda c: c["lines"]),
        "external": sorted(external_calls, key=lambda c: c["lines"]),
        "unresolved": props.get("unresolved_calls", []),
    }
    result["references"] = {
        "reliability": INFERRED,
        "targets": sorted(e.target for e in index.outgoing(node_id, "references")),
    }

    # 間接副作用：沿專案內的呼叫往下，看被呼叫者做了什麼
    indirect: dict[str, list[dict[str, Any]]] = {}
    seen, queue = {node_id}, [e.target for e in index.outgoing(node_id, "calls")]
    while queue:
        current = queue.pop()
        if current in seen or current.startswith("ext:"):
            continue
        seen.add(current)
        for edge in index.outgoing(current, "calls"):
            if edge.target.startswith("ext:"):
                callee = edge.properties.get("callee", edge.target[4:])
                category = side_effect(callee)
                if category:
                    indirect.setdefault(category, []).append({"callee": callee, "in": current})
            else:
                queue.append(edge.target)
    result["side_effects"] = {
        "reliability": HEURISTIC,
        "note": "依對照表分類外部呼叫；沒列到不代表沒有副作用",
        "direct": effects,
        "indirect": indirect,
    }

    source = None
    if rel and props.get("line"):
        source = read_source(
            index.graph.meta.get("root", ""), rel, props["line"], props["end_line"]
        )
    if node.type == "function" and source is not None:
        facts = _body_facts(source, props.get("is_method", False), props.get("decorators", []))
        if facts:
            result["state"] = {
                "reliability": EXACT,
                "note": "只含直接寫成 self.x 的讀寫；經別名、setattr、被呼叫者代為修改的不含",
                "receiver": facts["receiver"],
                "reads": facts["reads"],
                "writes": facts["writes"],
                "global_writes": facts["global_writes"],
            }
            result["raises"] = {
                "reliability": EXACT,
                "note": "只含本 function 明寫的 raise；被呼叫者丟出來的不含",
                "exceptions": facts["raises"],
            }
            result["returns"] = {
                "reliability": EXACT,
                "return_statements": facts["returns"],
                "is_generator": facts["is_generator"],
            }
    result["source"] = {
        "reliability": EXACT,
        "available": source is not None,
        "text": source,
        "note": None if source is not None else "讀不到原始碼（檔案已移動或刪除）",
    }
    return result
