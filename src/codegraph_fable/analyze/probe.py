"""在「被分析專案的 Python」裡執行的探針：回報環境，並用 Python 自己的模組查找回答查詢。

獨立腳本：只用標準庫、不 import 本套件、不執行被查找的模組。
輸入（stdin, JSON）：{"extra_paths": [...], "queries": [{"id", "name", "paths", "with_env"}]}
輸出（stdout, JSON）：環境資訊 ＋ {"results": {id: chain}}
chain：點狀名字每一段的查找結果 [{"origin", "locations"}]，查不到就停，所以可能比段數短。
"""

import sys

_STARTUP = sorted(sys.modules)  # 直譯器啟動時就載入的模組：本地同名檔案搶不走

import json  # noqa: E402
import os  # noqa: E402
import sysconfig  # noqa: E402
import types  # noqa: E402
from importlib.machinery import PathFinder  # noqa: E402


def _resolve(name, search, use_meta_path):
    parts = name.split(".")
    chain = []
    path = search
    for index in range(len(parts)):
        full = ".".join(parts[: index + 1])
        spec = None
        # 無 __init__.py 的套件（namespace package）在查子模組時會去讀 sys.modules 裡的上層，
        # 我們沒有真的 import 它，所以暫時放一個只帶 __path__ 的替身
        parent = ".".join(parts[:index])
        placeholder = bool(parent) and parent not in sys.modules
        if placeholder:
            sys.modules[parent] = types.ModuleType(parent)
            sys.modules[parent].__path__ = list(path)
        try:
            spec = PathFinder.find_spec(full, path)
            locations = list(spec.submodule_search_locations or []) if spec else []
        except Exception:
            spec = None
        finally:
            if placeholder:
                del sys.modules[parent]
        if spec is None and index == 0 and use_meta_path:
            # 可編輯安裝（editable install）等自訂的查找器
            for finder in sys.meta_path:
                if getattr(finder, "__name__", "") in (
                    "BuiltinImporter",
                    "FrozenImporter",
                    "PathFinder",
                ):
                    continue
                try:
                    spec = finder.find_spec(full, None)
                except Exception:
                    spec = None
                if spec is not None:
                    break
        if spec is None:
            break
        if index == 0 and not locations:
            locations = list(spec.submodule_search_locations or [])
        origin = spec.origin if getattr(spec, "has_location", False) else None
        chain.append({"origin": origin, "locations": locations})
        if not locations:
            break
        path = locations
    return chain


def main():
    request = json.load(sys.stdin)
    here = os.path.dirname(os.path.abspath(__file__))
    env_paths = [p for p in sys.path if p and os.path.abspath(p) != here]
    for extra in request.get("extra_paths", []):
        if extra not in env_paths:
            env_paths.append(extra)
    sys.path[:] = env_paths  # 讓下面的套件清單也看得到 extra_paths

    packages, installed = {}, []
    try:
        from importlib import metadata

        installed = sorted(
            {d.metadata["Name"] for d in metadata.distributions() if d.metadata["Name"]}
        )
        if hasattr(metadata, "packages_distributions"):
            packages = {k: sorted(set(v)) for k, v in metadata.packages_distributions().items()}
    except Exception:
        pass

    paths = sysconfig.get_paths()
    results = {}
    for query in request.get("queries", []):
        with_env = query.get("with_env", True)
        search = list(query["paths"]) + (env_paths if with_env else [])
        results[query["id"]] = _resolve(query["name"], search, with_env)

    json.dump(
        {
            "executable": sys.executable,
            "version": ".".join(map(str, sys.version_info[:3])),
            "env_paths": env_paths,
            "stdlib_names": sorted(getattr(sys, "stdlib_module_names", ())),
            "stdlib_dirs": sorted({paths.get("stdlib", ""), paths.get("platstdlib", "")} - {""}),
            "builtin_names": sorted(sys.builtin_module_names),
            "startup_modules": _STARTUP,
            "packages_distributions": packages,
            "installed": installed,
            "results": results,
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
