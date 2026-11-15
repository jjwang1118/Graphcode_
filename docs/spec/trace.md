# trace 規格

執行時觀察：實際跑一個指令，記錄專案內真正發生的呼叫，拿來量靜態分析漏了多少。
程式：`src/codegraph_fable/trace/`。測試：`tests/test_trace.py`（答案照實際執行路徑人工推定）。

---

## 用法

```bash
python -m codegraph_fable.trace <專案> [--python <專案環境的 python>] [-o 圖.json] [--top 20] -- <指令…>

# 例：跑專案的測試
python -m codegraph_fable.trace ~/proj --python ~/proj/.venv/bin/python -- -m pytest -q -p no:cacheprovider
# 例：跑一支腳本
python -m codegraph_fable.trace ~/proj -- scripts/run.py
```

```python
from codegraph_fable.trace import record, compare, merge
observed = record(project, ["-m", "pytest", "-q"], python=None)
report = compare(graph, observed)      # 只比對
report = merge(graph, observed)        # 比對，並把漏掉的加進圖
```

---

## 安全

| # | 規則 |
|---|---|
| T-S1 | **這會執行被分析專案的程式碼。** 只能由命令列或程式明確呼叫；MCP 與網頁都沒有這個功能 |
| T-S2 | 執行時設 `PYTHONDONTWRITEBYTECODE=1`，不在專案裡留 `__pycache__`。跑 pytest 時加 `-p no:cacheprovider` 才不會留 `.pytest_cache` |

---

## 檔案分工

| 檔案 | 做什麼 |
|---|---|
| `tracer.py` | 在**專案的 Python** 裡執行：用 `sys.setprofile` 記錄呼叫後寫成 JSON。獨立腳本，只用標準庫，要相容舊版 Python |
| `__init__.py` | `record`（啟動 tracer）、`compare`（與圖比對）、`merge`（把漏掉的加進圖） |
| `__main__.py` | 命令列：分析 → 執行 → 比對 → 印報告 |

---

## 規則

| # | 規則 |
|---|---|
| T-1 | 只記「呼叫者與被呼叫者的程式碼都在專案內」的呼叫。經由外部程式碼轉進來的不記（pytest 呼叫測試函式、框架呼叫回呼） |
| T-2 | 不算呼叫：import 執行了模組、class 本體在定義時執行、函式裡的產生器運算式／lambda／comprehension（算是函式自己的一部分） |
| T-3 | 觀察到的程式碼對回節點：有完整名字（Python 3.11+）就用名字；否則找同名、定義行在其後最近的。對不回去的計入 `unmapped` |
| T-4 | 寫在檔案層的呼叫，呼叫者是 `file` 節點 |
| T-5 | 每一組（呼叫者, 被呼叫者）分三類：`confirmed`＝圖上有這條 `calls` 邊；`dispatch`＝沒有這條邊，但呼叫者連到被呼叫者覆寫的祖先方法（含 Protocol），影響範圍查得到、標「可能」；`missing`＝靜態分析漏掉 |
| T-6 | `recall` ＝ confirmed ÷ observed；`recall_with_dispatch` ＝（confirmed ＋ dispatch）÷ observed |
| T-7 | `merge` 把 `missing` 加進圖，邊的型別是 **`observed_calls`**（`count`、`evidence: runtime`），**不與靜態的 `calls` 混在一起**；摘要寫進 `meta.runtime`。影響範圍查詢目前不走 `observed_calls` |
| T-8 | 指令失敗不隱藏：`returncode` 照實回報，已經觀察到的呼叫仍然保留 |

---

## 量測結果（2026-11-15）

參照專案的後端（`codegraph/backend`），跑它自己的 171 個測試：

| 項目 | 數字 |
|---|---|
| 觀察到的呼叫（組） | 479 |
| 圖上有這條邊 | 470（98.1%） |
| 經覆寫／Protocol 查得到 | 8 |
| 漏掉 | 1 |
| 合計查得到 | 478（99.8%） |

漏掉的 1 組：`tests/test_facts_inherits.py::produce` → `tests/test_facts_calls.py::produce`，原因未查。

---

## 已知限制

| 限制 | 說明 |
|---|---|
| 只涵蓋執行到的路徑 | 沒有測試的專案量不到；量到的是「實際發生過的呼叫中漏了多少」，不是全部 |
| 只量得出漏邊，量不出假邊 | 圖上多出來的邊（實際不會發生的）這個方法看不到 |
| 測試替身 | 被 mock 換掉的目標不是專案的程式碼，自然不會被記到；但 `tests/` 裡的函式也算專案內 |
| 需要專案能跑起來 | 依賴要裝好 |
| `merge` 的結果不會自動存回 `.codegraph/` | 要用 `-o` 另存；下次重新分析就沒有了 |
| 多行程、子行程 | 只記主行程與它的執行緒 |

沒有測試的：`python` 參數（另一個環境）、沒有完整名字時的行號比對（舊版 Python）、多執行緒、命令列。
