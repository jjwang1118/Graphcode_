# analyze 規格

專案目錄 → 一張圖。程式：`src/codegraph_fable/analyze/`。測試：`tests/test_analyze.py`（共用測試專案，標準答案寫死在測試檔裡）、`tests/test_analyze_cases.py`（每個案例自建小專案）、`tests/test_uses.py`（呼叫／繼承／引用，測試專案在 `tests/fixtures/calls/`）。

**涵蓋範圍**：目錄結構、定義、import 與套件分類、呼叫、繼承、覆寫（含 Protocol）、引用。影響範圍與 function 細節是查詢層的事，見 `query.md`。

**本文件描述程式現在的實際行為。** 發現錯的行為時列在最後的「已知問題」，不混在規則裡；目前沒有未修的。

---

## 用法

```python
from codegraph_fable.analyze import analyze
graph = analyze("專案目錄", python=None, roots=None, extra_paths=None, engine_check=True, resolve_uses_=True)
```

```bash
python -m codegraph_fable.analyze <專案目錄> [-o 結果.json] [--python <執行檔>] [--root <目錄>]... [--extra-path <目錄>]...
```

| 參數 | 意思 | 預設 |
|---|---|---|
| `python` | 專案環境的 Python 執行檔（依賴裝在那裡） | 執行本工具的 Python（此時環境路徑會含本工具自己的套件） |
| `roots` | 搜尋根目錄 | 專案根；`src/*.py` 或 `src/*/*.py` 存在時再加 `src/`（更深才有 `.py` 不算） |
| `extra_paths` | 額外的套件安裝目錄，排在環境路徑之後 | 無 |
| `engine_check` | 是否做 Jedi 核對（AN-I11）。命令列沒有對應選項 | `True` |
| `resolve_uses_` | 是否解析呼叫、繼承、引用（AN-U，需要 Jedi；大專案最花時間的一步）。命令列沒有對應選項 | `True` |

命令列補充：
- `--root`、`--extra-path` 的相對路徑以**目前工作目錄**為準，不是專案目錄。
- 不給 `-o` 只印摘要，不存檔。

失敗方式：

| 情況 | 行為 |
|---|---|
| `python` 路徑不存在 | 丟 `FileNotFoundError` |
| probe 執行失敗 | 丟 `RuntimeError` |
| Jedi 不可用或被停用 | 不中斷，`meta.engine.available = False` |

---

## 檔案分工

| 檔案 | 做什麼 | 不做什麼 |
|---|---|---|
| `scan.py` | 走訪目錄，列出檔案與資料夾 | 讀檔案內容 |
| `definitions.py` | 逐檔抽出定義與 import 敘述（`ast`） | 看別的檔案、解析名字 |
| `probe.py` | 在**專案的 Python** 裡執行：回報環境、用 Python 自己的模組查找回答查詢 | import 本套件、執行被查的模組 |
| `roots.py` | 預設搜尋根、讀宣告的依賴、執行 probe | — |
| `imports.py` | 決定要查什麼、把答案變成 `imports` 邊與外部套件節點 | 模組查找（交給 probe）。只有兩處自己看檔案：資料夾有沒有 `__init__.py`、`from . import x` 的套件目標 |
| `uses.py` | 逐檔找出使用點：呼叫、繼承的 base、對名字的引用（`ast`） | 解析它們指向誰 |
| `calls.py` | 把使用點交給 Jedi，把答案變成 `calls`／`inherits`／`overrides`／`references` 邊 | 自己推論型別 |
| `engine.py` | Jedi 包裝。**只有這個檔案 import Jedi** | — |
| `run.py` | 讀檔、串起各步、組圖、寫 `meta`、判定 Jedi 核對結果 | — |
| `__main__.py` | 命令列；會用到 `store` 存檔 | — |

---

## 規則

編號前綴 `AN-`，避免與 `CLAUDE.md` 的決定編號（D1–D9）撞號。

### 掃描

| # | 規則 |
|---|---|
| AN-S1 | 所有檔案都有 `file` 節點（含空資料夾的 `directory` 節點）；只有 `.py` 會被解析，`.pyi` 不解析 |
| AN-S2 | 不進圖的資料夾，**不論在哪一層**（例外：`dist`、`build` 裡有 `__init__.py` 時是套件，照常進圖）：`.git`、`.hg`、`.svn`、`__pycache__`、`node_modules`、`.venv`、`venv`、`dist`、`build`、`.mypy_cache`、`.pytest_cache`、`.ruff_cache`、`.tox`、`.nox`、`.idea`、`.vscode`、`.codegraph`、`*.egg-info`、任何含 `pyvenv.cfg` 的資料夾。符號連結的檔案與資料夾也不進圖 |

### 定義

| # | 規則 |
|---|---|
| AN-D1 | class、function（含方法、巢狀）都記 |
| AN-D2 | 變數只記檔案層與 class 內的一般指派與帶註解的指派（含寫在 `if`／`try` 裡的）。不記：函式內的區域變數、`for` 的目標、`with … as`、`+=`、`:=` |
| AN-D3 | 變數重複指派只記第一次；class／function 重複定義都記，第二個起 id 帶 `@行號`，其成員的 id 也跟著帶（`K@52.m`） |
| AN-D4 | 同名的變數與 function：先變數後 function → function 變 `名字@行號`；先 function 後變數 → 變數不記 |
| AN-D5 | `bases` 不含 `metaclass=` 等關鍵字引數；`is_method` 表示「直接寫在 class 裡」，`staticmethod` 也是 `True` |
| AN-D6 | 語法錯誤的檔案不中斷分析：記在 `file` 節點的 `parse_error` 與 `meta.parse_errors` |

### import 解析

| # | 規則 |
|---|---|
| AN-I1 | **查找由 Python 自己做**（probe 用 `importlib` 的 `PathFinder`），搜尋順序＝搜尋根 → 環境路徑 → `extra_paths`。最頂層查不到時再問環境裡自訂的查找器（可編輯安裝用的） |
| AN-I2 | **搶不走的模組**一律判標準庫：內建模組，加上「直譯器啟動時就已載入」且在標準庫名單裡的模組。這份名單隨環境而變（例：某環境 `os`、`abc` 搶不走，`types`、`re` 仍會被根目錄的同名檔蓋掉） |
| AN-I3 | 其餘照**最頂層名字查到的位置**分類，順序：① 在專案內且在圖裡 → 本地　② 在環境路徑底下（含專案資料夾內的虛擬環境）→ 照 ④⑤ 當外部　③ 在專案內但被掃描排除 → `excluded`　④ 在標準庫名單或標準庫目錄 → `stdlib`　⑤ 其他查得到 → `third_party`　⑥ 查不到：在標準庫名單 → `stdlib`（`installed: false`）；有宣告 → `third_party`；否則 `unknown` |
| AN-I4 | 外部套件只連到最頂層（`import a.b.c` → `ext:a`），**不檢查子模組是否存在**；本地連到最後一段的檔案 |
| AN-I5 | `from 套件 import 名字`：`__init__.py` 自己綁定了這個名字 → 連 `__init__.py`；否則是子模組 → 連子模組；都不是 → 連套件 |
| AN-I6 | 相對 import 照路徑往上走；走到或走出所屬搜尋根就算解不出 |
| AN-I7 | 沒有 `__init__.py` 的套件（namespace package）連到 `directory` 節點 |
| AN-I8 | 「解不出」只有四種：本地套件裡找不到子模組、目標在專案內但被掃描排除、相對 import 超出最頂層套件、相對 import 找不到目標。解不出不產生邊，但**一定**列在 `meta.unresolved_imports`。`meta.imports.total` ＝ 邊數 ＋ 解不出數。最頂層就查不到的不算解不出，而是連到 `unknown` 的外部節點 |
| AN-I9 | **蓋掉別人**：把搜尋根拿掉、只在環境裡再查一次同一個最頂層名字。查得到且位置不同 → 邊帶 `shadows: stdlib`（名字在標準庫名單）或 `shadows: third_party`。專案自己被安裝在環境裡（`pip install -e .`）時查到的是同一個位置，不算 |
| AN-I10 | **啟動位置**：檔案有 `if __name__ == "__main__"`，或所在資料夾沒有 `__init__.py`，且所在資料夾不是搜尋根時，再以「檔案所在資料夾」取代搜尋根查一次，只比**最頂層名字**。兩邊都查得到但位置不同 → 邊帶 `entry_sensitive` 與 `alt_target`（最頂層的節點 id，該節點一定存在於圖中）；搜尋根下查不到但同資料夾有 → 連過去，帶 `via: script_dir` 與 `entry_sensitive`。搜尋根下查得到、同資料夾查不到的**不標** |
| AN-I11 | **Jedi 核對**：絕對 import 的模組再由 Jedi 解一次（關掉自動猜路徑、路徑清單與 AN-I1 相同）。不一致記在 `meta.engine_disagreements`，邊帶 `engine_check: disagree`，**以 Python 的答案為準**。不核對、記為 `unchecked` 的四類：搶不走的模組、namespace package、目標不是 `.py`、Jedi 丟例外 |
| AN-I12 | 「宣告的依賴」只讀專案根的 `requirements*.txt` 與 `pyproject.toml`（`project.dependencies`、`optional-dependencies`、`dependency-groups`、`tool.poetry.dependencies`）。不讀 `-r` 引用的檔案、`setup.py`、`setup.cfg`、Pipfile。網址行與路徑行（`git+https://…`、`./x`）不算套件名；`名字 @ 網址` 取名字 |
| AN-I13 | **有宣告但沒安裝**時怎麼認：import 名等於套件名 → 認得；不相等時查內建的常見對照表 `KNOWN_DISTRIBUTIONS`（`cv2` → `opencv-python` 等約 20 筆），認得的節點帶 `distribution_source: known_alias`（這是猜的）。表裡沒有的 → `unknown` |

### 呼叫、繼承、覆寫、引用（T3）

每個使用點由 Jedi 回答「指向哪個定義」，我們不自己推論。

| # | 規則 |
|---|---|
| AN-U1 | **誰在用**：使用點算在最內層的 class／function 上；寫在檔案層的算在 `file` 節點上。裝飾器算在被裝飾的定義上 |
| AN-U2 | **呼叫以「每個呼叫運算式」為單位**。`meta.uses.calls`：`expressions` ＝ `resolved` ＋ `unresolved`；`resolved` ＝ `local` ＋ `external` |
| AN-U3 | 被呼叫的名字解到 function → 連 function；解到 class → 連 class，且該 class 或祖先有 `__init__` 時再連一條 `via: constructor`；解到物件實例 → 連它的 `__call__`（`via: call_method`） |
| AN-U4 | 名字指向變數或參數時，再問 Jedi「它的值是什麼」（`fn = helper; fn()`、`x = Foo(); x.go()`、`self.a.b()`） |
| AN-U5 | 一個呼叫解出多個目標（兩種可能的型別）→ 每個目標一條邊，都帶 `ambiguous: true` |
| AN-U6 | 目標在專案外 → 連到 `ext:<最頂層模組>`，邊的 `callee` 記完整名字（`os.path.join`）。圖裡還沒有這個外部節點就新增（例：`builtins`） |
| AN-U7 | **解不出不產生邊、不可丟掉**：記在呼叫者節點的 `unresolved_calls`（`line`、`text`、`reason`），並計入 `meta.uses.calls.reasons`。原因：`dynamic`（被呼叫的是運算結果，如 `d[k]()`、`getattr(…)()`）、`param`（參數）、`variable`（變數型別推不出）、`module`、`unindexed`（專案內但不是 class／function）、`no_call_method`、`unknown`。另有不是呼叫的 `property`（見 AN-U15） |
| AN-U8 | **套件沒安裝時的退路**：Jedi 回 `unknown`，而名字是檔案層 `import` 自外部套件的 → 連到那個外部節點，`evidence: import`（只知道來自哪個套件）。名字被參數或區域變數蓋掉時不適用 |
| AN-U9 | `inherits`：class → 專案內的 class 或外部節點（`base` 記寫法或完整名字）。解不出記在 class 節點的 `unresolved_bases` |
| AN-U10 | `overrides`：子類別的方法 → 沿專案內繼承往上、最近一個定義了同名方法的祖先的方法。只看專案內 |
| AN-U11 | `references`：不是呼叫的使用（傳函式當參數、沒括號的裝飾器、型別註解、讀別處的變數）→ 連到專案內的 class／function／variable。只查「名字出現在專案定義名單或 import 別名裡」的使用點；不連外部、不連自己 |
| AN-U12 | 同一對（來源、目標、`via`、`callee`）合成一條邊，`count` 是次數、`lines` 是行號 |
| AN-U13 | 引擎對同一個呼叫回了多個定義、其中有名字與寫法相符的 → 只留相符的（濾掉引擎多回的不相干型別，例：`handle.write` 多出 `typing.Callable`） |
| AN-U14 | **Protocol**：繼承 `Protocol` 的 class 是結構型別，專案內的 class 不必繼承它也可能實作它。判斷只看它宣告的**真正的方法**（`@property` 成員不當門檻：可以用類別屬性、dataclass 欄位、`self.x` 滿足，我們看不全）：全部都有 → 算實作；至少兩個且過半 → 也算，但標 `partial`（實際的程式常是鴨子型別，只實作一部分）。符合時，每個同名方法的實作（可能是從祖先繼承來的）→ Protocol 的方法，`overrides` 邊帶 `via: protocol`。照名字比對，不檢查參數 |
| AN-U15 | **解不出的屬性讀取**：讀 `@property` 會執行函式。接收者型別推不出來、而屬性名字與專案內某個 `@property` 同名時，記在該節點的 `unresolved_calls`（原因 `property`），並計入 `meta.uses.unresolved_property_reads`（不計入 `calls.unresolved`）。其他解不出的屬性存取不記 |

`calls`／`inherits`／`references` 邊的 properties：

| 欄位 | 意思 | 何時出現 |
|---|---|---|
| `count`、`lines` | 次數、行號 | 一定有（`overrides` 沒有任何欄位） |
| `evidence` | `jedi`（解到確切定義）／`import`（AN-U8） | `calls`、`inherits` |
| `via` | `constructor`／`call_method` | 成立才有 |
| `callee`、`base` | 外部目標的完整名字；`base` 在專案內時是寫法 | 外部目標、`inherits` |
| `ambiguous`、`decorator` | 見 AN-U5、AN-U1 | 成立才有 |

### `imports` 邊的 properties

| 欄位 | 意思 | 何時出現 |
|---|---|---|
| `line`、`module`、`scope` | 第幾行、寫的模組（相對 import 含開頭的點）、寫在 `module`／`function`／`class` 哪一層 | 一定有 |
| `name` | from-import 的名字（含 `*`） | from-import 才有 |
| `type_checking` | 在 `if TYPE_CHECKING:` 或 `if typing.TYPE_CHECKING:` 裡（其他寫法不認） | 為真才有 |
| `guarded` | 包在會接住 `ImportError`／`ModuleNotFoundError`／`Exception`／`BaseException`／裸 `except` 的 `try` 裡（不認 `contextlib.suppress`） | 為真才有 |
| `shadows`、`entry_sensitive`、`alt_target`、`via`、`engine_check` | 見 AN-I9 – AN-I11 | 成立才有 |

import 的別名（`as`）不寫到邊上。

---

## meta

| 欄位 | 內容 |
|---|---|
| `schema_version`、`root` | 格式版本、專案的絕對路徑 |
| `fingerprint` | 所有 `.py` 的路徑與內容的雜湊（`scan.fingerprint`）。MCP 用它判斷結果是否過期 |
| `options` | 這次分析的參數：`python`、`roots`（沒指定為 null）、`extra_paths` |
| `search_roots`、`python`、`env_paths` | 這次分析用的搜尋根（相對專案）、Python 執行檔與版本、環境路徑 |
| `counts` | 各型別的節點數、邊數 |
| `imports` | 計數：`total`、`local`、`stdlib`、`third_party`、`unknown`、`excluded`、`unresolved`、`shadowing`、`entry_sensitive`、`via_script_dir`、`guarded`、`type_checking` |
| `unresolved_imports` | 每筆：`file`、`line`、`module`、`name`、`reason` |
| `missing_dependencies` | 有宣告但環境沒安裝的套件 |
| `parse_errors` | 語法錯誤的檔案 |
| `engine` | `name`、`available`；可用時另有 `version`、`agree`、`disagree`、`unchecked`；不可用時有 `error` |
| `engine_disagreements` | 每筆：`module`、`python`（Python 查到的檔案）、`engine`（Jedi 查到的檔案） |
| `uses` | `available`；可用時有 `calls`（`expressions`、`resolved`、`unresolved`、`local`、`external`、`ambiguous`、`reasons`）、`inherits`（`bases`、`resolved`、`unresolved`）、`references`、`overrides`（邊數）、`unresolved_property_reads` |

---

## 已知限制（設計如此）

| 限制 | 現況 |
|---|---|
| 依賴沒安裝 | 該套件判為 `third_party`（有宣告，見 AN-I13）或 `unknown`，不會接錯到本地。import 名與套件名不同、又不在對照表裡的，會判成 `unknown` |
| 動態 import（`importlib.import_module`、`__import__`） | 看不到 |
| 執行時修改 `sys.path` | 不處理；需要時用 `roots` 參數補上 |
| 套件在執行時改寫 `__path__` | 不處理 |
| `import a.b.c` | 只連到 `c`，不連沿路的 `a`、`a.b` |
| 未標註型別的參數、注入的物件（`def f(obj): obj.run()`） | 解不出，記 `unresolved_calls` |
| 動態呼叫（`getattr(…)()`、`d[k]()`、框架的註冊機制） | 解不出，記 `unresolved_calls` |
| 運算子、`with`、迭代等隱含的方法呼叫 | 不產生邊，也不計數 |
| 多型：`b: Base; b.run()` 只連到 `Base.run` | 子類別的覆寫、Protocol 的實作靠 `overrides` 邊在查詢時補上 |
| 沒有 Protocol 也沒有繼承的鴨子型別（未標註的參數） | 解不出 |
| 預設參數值裡的呼叫（`def f(x=g())`） | 算在 `f` 上（其實是在外層求值） |
| 檔案層的「實際使用」邊（F7 的另一半） | 不另存：由 `calls`／`inherits`／`references` 在查詢時往上加總（T4） |
| 「import 的名字有沒有被用到」 | 還沒做 |
| 搜尋根在專案目錄外 | 那裡的程式判為 `third_party` |
| probe 跑在 Python 3.10 以下 | 沒有標準庫名單，改靠標準庫目錄判斷 |

---

## 已知問題

目前沒有未修的。

2026-11-15 稽核發現的 B1–B9 已在 T2.1 全部修正，每一項在 `tests/test_analyze_cases.py` 有對應測試（`test_b1_…` – `test_b9_…`）：

| # | 原問題 | 修法 |
|---|---|---|
| B1 | 專案資料夾內虛擬環境的套件被判 `excluded` | AN-I3 ② |
| B2 | 自訂 `roots` 後，根之外的檔案有相對 import 會中斷 | 這種檔案以專案根為界 |
| B3 | 專案自己被安裝時誤標 `shadows` | AN-I9 改成比位置 |
| B4 | 有宣告沒安裝、import 名不同 → `unknown` | AN-I13 對照表（只涵蓋常見的） |
| B5 | `alt_target` 指向不存在的節點 | 一併建立該外部節點 |
| B6 | 被排除的子模組原因寫成「找不到」 | 原因改為「被掃描排除」 |
| B7 | 網址行被當成套件名 | AN-I12 |
| B8 | 平台沒有的標準庫模組標 `installed: true` | AN-I3 ⑥ |
| B9 | `dist`／`build` 吃掉同名的本地套件 | AN-S2 的例外 |

---

## 測試涵蓋的缺口

沒有測試的：AN-U3 的繼承來的 `__init__`、AN-U7 的 `module`／`unindexed`／`no_call_method`、Jedi 不可用時的行為、參數 `python`（非預設值）、AN-I11 的不一致路徑（造不出案例）、AN-S2 的符號連結與 `*.egg-info`、`tool.poetry` 與 `dependency-groups` 的依賴宣告。
