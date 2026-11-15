"""在「被分析專案的 Python」裡執行：跑一個指令，記錄專案內實際發生的函式呼叫。

獨立腳本：只用標準庫、不 import 本套件。
用法：python tracer.py --root <專案> --out <結果.json> -m <模組> [參數…]
      python tracer.py --root <專案> --out <結果.json> <腳本.py> [參數…]
只記「呼叫者與被呼叫者都在專案內」的呼叫；經由外部程式碼轉進來的（例如 pytest 呼叫測試函式）不記。
"""

import json
import os
import runpy
import sys
import threading

_SKIP = ("site-packages", "dist-packages", ".venv", "venv", "node_modules")


def main():
    args = sys.argv[1:]
    options = {}
    while len(args) >= 2 and args[0] in ("--root", "--out"):
        options[args[0]] = args[1]
        args = args[2:]
    if "--root" not in options or "--out" not in options or not args:
        sys.exit(__doc__)
    root = os.path.realpath(options["--root"]) + os.sep
    pairs = {}
    known = {}

    def describe(code):
        found = known.get(code, 0)
        if found != 0:
            return found
        # `<frozen posixpath>`、`<string>` 這類不是檔案：realpath 會把它接到目前資料夾底下，誤判成專案內
        path = "" if code.co_filename.startswith("<") else os.path.realpath(code.co_filename)
        inside = path.startswith(root) and not any(part in _SKIP for part in path.split(os.sep))
        found = None
        if inside:
            rel = path[len(root) :].replace(os.sep, "/")
            # co_qualname 是 3.11 才有的；沒有就只有名字，由比對端用行號補
            found = (rel, getattr(code, "co_qualname", None), code.co_name, code.co_firstlineno)
        known[code] = found
        return found

    def profile(frame, event, _arg):
        if event != "call":
            return
        callee = describe(frame.f_code)
        if callee is None or frame.f_back is None:
            return
        caller = describe(frame.f_back.f_code)
        if caller is None:
            return
        key = caller + callee
        pairs[key] = pairs.get(key, 0) + 1

    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]
    status = 0
    threading.setprofile(profile)
    sys.setprofile(profile)
    try:
        if args[0] == "-m":
            sys.argv = args[1:]
            sys.path.insert(0, os.getcwd())
            runpy.run_module(args[1], run_name="__main__", alter_sys=True)
        else:
            sys.argv = args
            sys.path.insert(0, os.path.dirname(os.path.abspath(args[0])))
            runpy.run_path(args[0], run_name="__main__")
    except SystemExit as stop:
        status = stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    finally:
        sys.setprofile(None)
        threading.setprofile(None)

        def entry(part):
            return {"file": part[0], "qualname": part[1], "name": part[2], "line": part[3]}

        with open(options["--out"], "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "root": root.rstrip(os.sep),
                    "command": args,
                    "python": ".".join(map(str, sys.version_info[:3])),
                    "pairs": [
                        {"caller": entry(key[:4]), "callee": entry(key[4:]), "count": count}
                        for key, count in pairs.items()
                    ],
                },
                handle,
            )
    sys.exit(status)


if __name__ == "__main__":
    main()
