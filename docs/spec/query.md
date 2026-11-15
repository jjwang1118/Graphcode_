# query 規格

查詢層：對分析結果提問。程式：`src/codegraph_fable/query/`。測試：`tests/test_query.py`（答案照 Python 語意人工判定）。

---

## 定位

| 規則 | 理由 |
|---|---|
| 只讀 `Graph`，不讀專案、不 import Jedi | MCP 與網頁共用同一份答案；查詢不需要專案的 Python 環境 |
| 唯一例外：`detail` 依行號從磁碟讀原始碼 | 圖裡不存原始碼 |
| 回傳一般的 dict／list | 文字排版是 MCP、網頁各自的事 |

```python
from codegraph_fable.query import Index, impact, detail, overview, file_dependencies
index = Index(graph)          # 建一次，重複查詢
```

---

## 檔案分工

| 檔案 | 提供 |
|---|---|
| `index.py` | `Index`（進出邊索引、`parent`／`children`、`find`、`descendants`、`ancestors`）、`owner_file` |
| `impact.py` | `impact`：改這裡影響誰 |
| `detail.py` | `detail`：function／class 的細節清單；`SIDE_EFFECTS` 對照表 |
| `overview.py` | `overview`：專案概覽；`file_dependencies`：檔案層的依賴 |
| `view.py` | `view`：畫面用的收合視圖；`locate`：節點在畫面上由誰代表。規則見 `web.md`（W-V1 – W-V8）。參數：`expanded`、`edge_types`、`externals`、`level`、`collapsed` |

---

## `Index.find(name)`

依名字找 class／function／variable／file。接受：完整 id、`檔案::名字`、`類別.方法`、單純的名字。可能回多筆（同名）。

---

## `impact(index, target, max_depth=None)`

| # | 規則 |
|---|---|
| Q-I1 | **範圍**：改一個檔案或 class ＝ 改它裡面定義的全部（回傳的 `scope`） |
| Q-I2 | **一層一層往外**：`levels[0]` 是直接使用者，`levels[1]` 是使用者的使用者。每個節點只出現在最早的那一層 |
| Q-I3 | **使用者**＝ `calls`、`references`、`inherits` 邊的來源，以及 `imports` 邊的來源（目標是檔案時） |
| Q-I4 | **動態分派**：目標是覆寫了祖先方法的方法時，呼叫或引用祖先同名方法的人也算，`relation: dispatch`、`certainty: possible`。`__init__`／`__new__` 不適用 |
| Q-I5 | **確定程度**：`certain`＝引擎解到確切定義；`possible`＝該邊 `ambiguous`、`evidence: import`、經動態分派，或上游已是 `possible`。同一節點有兩條路時取較確定的 |
| Q-I6 | **候選**（`candidates`）：專案內所有解不出的呼叫中，寫法含有目標名字的。附 `reason`，**不算進受影響清單**。`already_listed` 表示該節點已在清單內 |
| Q-I7 | `overridden_by`：覆寫了目標的子類別方法（改父類別方法時要一併看） |
| Q-I8 | `completeness`：`affected`、`certain`、`possible`、`candidates`、`unresolved_calls_in_project`、`uses_available`。**每個答案都要帶**，讓使用者知道答案可能不完整 |
| Q-I9 | 目標不存在 → 丟 `KeyError` |

每筆使用者：`id`、`relation`（`calls`／`calls:constructor`／`calls:call_method`／`references`／`inherits`／`imports`／`dispatch`）、`certainty`、`lines`、`through`（經由範圍內的哪個節點）。

---

## `detail(index, node_id)`

每個區塊都有 `reliability`：`exact`（直接從原始碼）／`inferred`（引擎推論，可能不完整）／`heuristic`（靠對照表猜）。

| 區塊 | 內容 | 可靠度 | 不含 |
|---|---|---|---|
| `interface` | 簽名、裝飾器、是否 async／方法、docstring；class 則是 base 與成員 | exact | — |
| `calls` | `local`、`external`（含 `callee`）、`unresolved` | inferred | 執行順序、分支（只按原始碼位置） |
| `references` | 引用到的專案內定義 | inferred | — |
| `side_effects` | `direct`（自己的外部呼叫）、`indirect`（沿專案內呼叫往下找到的，附 `in`） | heuristic | 對照表沒列的呼叫 |
| `state` | `reads`／`writes`（`self.x`）、`global_writes` | exact | 經別名、`setattr`、被呼叫者代為修改的 |
| `raises` | 明寫的 `raise` | exact | 被呼叫者丟出來的 |
| `returns` | 有回傳值的 `return` 個數、是否產生器 | exact | 回傳型別 |
| `source` | 原始碼文字（依行號讀檔） | exact | — |

| # | 規則 |
|---|---|
| Q-D1 | `state`、`raises`、`returns` 只有 function 才有，且要讀得到原始碼 |
| Q-D2 | 讀不到原始碼不丟錯：`source.available = false`，圖裡有的區塊照常回 |
| Q-D3 | 副作用類別來自 `SIDE_EFFECTS`（`file`、`network`、`process`、`database`、`console`、`logging`、`exit`、`environment`、`dynamic_code`、`sleep`）。結尾是 `.` 或 `_` 的是前綴比對，其餘完全相同 |
| Q-D4 | 不產生文字摘要、不呼叫 LLM |

---

## `overview(index, top=10)`

`root`、`search_roots`、`counts`、`packages`（最上層資料夾 → Python 檔數）、`externals`（類別 → 套件名）、`entry_points`（有 `__main__` 判斷的檔案）、`most_used_files`（被最多檔案依賴的）、`completeness`。

## `file_dependencies(index)`

`{(來源檔, 目標檔): {"imports": n, "uses": n}}`。`imports` 來自 import 敘述，`uses` 是 `calls`／`references`／`inherits` 往上加總（F7）。兩者可能不同：經 `__init__.py` 轉出時，import 指向 `__init__.py`，實際用到的是定義所在的檔案。

---

## 已知限制

| 限制 | 說明 |
|---|---|
| 影響範圍的下限取決於分析 | 解不出的呼叫不在清單裡，只可能出現在候選 |
| 候選只比對名字 | 會有誤報（同名的參數），所以與清單分開 |
| 動態分派是高估 | 接收者型別其實確定時（`Foo().m()`）也會列入 `possible` |
| 副作用對照表不完整 | 第三方套件大多沒列 |

沒有測試的：`overview` 的 `entry_points`、Q-I4 的多層繼承、`detail` 用在 class 上。
