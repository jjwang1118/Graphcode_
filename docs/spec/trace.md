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
| T-5 | 每一組（呼叫者, 被呼叫者）歸到七類之一，依序判斷：`confirmed`＝圖上有這條 `calls` 邊；`reference`＝有 `references` 邊（讀 `@property` 這類不寫括號卻會執行函式的存取）；`dispatch`＝呼叫者連到被呼叫者覆寫的祖先方法（含 Protocol），影響範圍標「可能」；`nested`＝邊記在呼叫者裡面的定義上（裝飾器是外層在執行，我們算在被裝飾者頭上）；`test_double`＝被呼叫的在測試檔裡、呼叫者不是測試（測試注入的替身）；`candidate`＝呼叫者有一筆解不出的使用點提到這個名字，影響範圍列為「候選」；`missing`＝圖上完全沒有 |
| T-6 | 三個比率：`recall`＝confirmed ÷ 全部（最嚴格）；`coverage`＝（confirmed＋reference＋dispatch＋nested）÷（全部 − test_double），也就是影響範圍查得到的；`coverage_with_candidates`＝再加上 candidate |
| T-7 | `merge` 把 `missing` 與 `candidate` 加進圖，邊的型別是 **`observed_calls`**（`count`、`evidence: runtime`），**不與靜態的 `calls` 混在一起**；測試替身不加。摘要寫進 `meta.runtime`。影響範圍查詢目前不走 `observed_calls` |
| T-8 | 指令失敗不隱藏：`returncode` 照實回報，已經觀察到的呼叫仍然保留 |

---

## 量測結果（2026-11-15）

三個專案各跑自己的測試。數字是「組」（呼叫者, 被呼叫者）。重跑方式見 `experiments/verify/README.md`。

| | 參照專案的後端 | foreman | envharness |
|---|---|---|---|
| 觀察到 | 479 | 1640 | 573 |
| `confirmed` | 470 | 1336 | 418 |
| `reference` | 0 | 46 | 27 |
| `dispatch` | 8 | 80 | 75 |
| `nested` | 0 | 1 | 4 |
| `candidate` | 0 | 55 | 25 |
| `test_double` | 0 | 103 | 6 |
| `missing` | 1 | 19 | 18 |
| `recall`（只算 calls 邊） | 98.1% | 81.5% | 73.0% |
| `coverage`（影響範圍查得到） | 99.8% | 95.2% | 92.4% |
| `coverage_with_candidates` | 99.8% | 98.8% | 96.8% |

| 觀察 | 說明 |
|---|---|
| `recall` 在後兩個專案明顯較低 | 大量依賴 `@property` 與 Protocol／繼承的動態分派；這些在圖上是 `references` 與 `overrides`，不是 `calls` |
| foreman 的測試有失敗（結束代碼 1） | 驗證用的環境沒把專案本身裝進去；已經跑到的呼叫仍然有效 |
| 剩下的 `missing` | 裝飾器工廠回傳的函式（`register_env(...)` 的內層）、從登錄表取出類別再建構、隱含的 `__len__`、把回呼存起來之後再呼叫。都是靜態分析看不到的動態行為 |

這輪量測找到並補上的三個缺口：實作 Protocol 的類別（AN-U14）、Protocol 的 `@property` 成員可用一般屬性滿足且允許只實作一部分、解不出的 `@property` 讀取要記下來（AN-U15）。

另外兩種獨立驗證（腳本在 `experiments/verify/`）：

| 驗證 | 結果 |
|---|---|
| 與獨立方法的答案比對（誰 import 某模組、誰 import 某外部套件、循環依賴、子類別、直接呼叫者），兩個專案共 11 項 | 10 項一致。不一致的 1 項（`ActionableEnv` 的子類別）查原始碼後是我們對：獨立方法漏了兩個（一個模組缺依賴載入失敗、一個資料夾沒走訪） |
| 假邊粗篩：專案內 `calls` 邊所在的那幾行有沒有被呼叫者的名字 | 沒有的比例：後端 0.12%、foreman 0.94%、envharness 2.36%。抽查其中的類型都是對的：別名（`Directive = Intervention`）、`cls(...)`、繼承來的 `__init__`、`import … as`、`self.fn(...)`。沒有發現假邊，但這只是抽查 |

---

## 已知限制

| 限制 | 說明 |
|---|---|
| 只涵蓋執行到的路徑 | 沒有測試的專案量不到；量到的是「實際發生過的呼叫中漏了多少」，不是全部 |
| 只量得出漏邊，量不出假邊 | 圖上多出來的邊（實際不會發生的）這個方法看不到；`experiments/verify/precision.py` 只是粗篩 |
| 「候選」是用名字比對 | 算進 `coverage_with_candidates` 的那些，在影響範圍裡只是「未確認的候選」 |
| 測試替身 | 被 mock 換掉的目標不是專案的程式碼，自然不會被記到；但 `tests/` 裡的函式也算專案內 |
| 需要專案能跑起來 | 依賴要裝好 |
| `merge` 的結果不會自動存回 `.codegraph/` | 要用 `-o` 另存；下次重新分析就沒有了 |
| 多行程、子行程 | 只記主行程與它的執行緒 |

沒有測試的：`python` 參數（另一個環境）、沒有完整名字時的行號比對（舊版 Python）、多執行緒、命令列。
