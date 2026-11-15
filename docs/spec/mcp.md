# mcp 規格

給 Agent 的介面。程式：`src/codegraph_fable/mcp/`。測試：`tests/test_mcp.py`（含真的啟動伺服器、用 MCP 客戶端呼叫）。

---

## 連接方式

| 項目 | 內容 |
|---|---|
| 形式 | 本機 MCP 伺服器（stdio），由 Agent 當子程式啟動 |
| 啟動指令 | `<codegraph_fable 環境的 python> -m codegraph_fable.mcp` |
| 註冊（Claude Code） | `claude mcp add codegraph -- <codegraph_fable 環境的 python> -m codegraph_fable.mcp`（用絕對路徑） |
| 依賴 | 官方 Python 套件 `mcp`（2.x：`from mcp.server.mcpserver import MCPServer`；1.x 的 `FastMCP` 寫法不能用） |
| 適用對象 | 任何支援 MCP 的 Agent |

不連網、不呼叫 LLM。

---

## 檔案分工

| 檔案 | 做什麼 |
|---|---|
| `../service.py` | 取得分析結果：記憶體 → 專案內的存檔 → 重新分析；判斷是否過期。**與網頁共用**，所以放在套件最上層 |
| `render.py` | 把 `query/` 的結果排成精簡文字（純函式，不依賴 `mcp` 套件） |
| `server.py` | 註冊五個工具；只呼叫 `service`、`query`、`render` |
| `__main__.py` | 啟動 |

---

## 工具

每個工具的 `project` 是專案資料夾的絕對路徑。回傳都是文字。

| 工具 | 參數 | 回什麼 |
|---|---|---|
| `analyze` | `project`、`python=""`、`force=false` | 摘要：節點與關係數量、import 分類、解不出的數量、缺少的依賴、語法錯誤的檔案 |
| `overview` | `project` | 各資料夾檔案數、外部套件（依類別）、可直接執行的檔案、被最多檔案依賴的檔案 |
| `find` | `project`、`name` | 定義位置與簽名；同名的全部列出 |
| `impact` | `project`、`target`、`depth=3`、`limit=60` | 一層層的使用者，每筆標「確定／可能」；候選；被誰覆寫；完整度 |
| `detail` | `project`、`target`、`source=true` | 介面、呼叫、引用、狀態、副作用、例外、回傳、原始碼，每區塊標「準確／推論／估計」 |

`target`／`name` 接受：`helper`、`Foo.go`、`app/util.py::helper`、完整 id。

---

## 規則

| # | 規則 |
|---|---|
| MCP-1 | 只呼叫 `query/` 與 `analyze()`，不自己做圖的運算 |
| MCP-2 | **不回答過期的結果**：每次查詢前重算所有 `.py` 的雜湊（`meta.fingerprint`），與存下來的不同就重新分析。寧可慢 |
| MCP-3 | 分析結果存在 `<專案>/.codegraph/graph.json`，同資料夾放一份內容為 `*` 的 `.gitignore`。無法寫入時只留在記憶體，並在來源說明裡寫出 |
| MCP-4 | 結果來源寫在 `analyze` 的回覆裡：`cached`（記憶體）／`loaded`（存檔）／`analyzed（原因）` |
| MCP-5 | 專案的 Python 環境：`python` 參數 → 上次用的 → 專案內的 `.venv`／`venv` → 本工具的 Python。指定了不同的 `python` 會重新分析 |
| MCP-6 | 截斷時一定寫出總數（`只列出 N 筆，共 M 筆`） |
| MCP-7 | `impact`、`overview`、`analyze` 的回覆都附完整度（專案內有幾個呼叫解不出） |
| MCP-8 | `target` 對到多筆 → 列出全部，請 Agent 用完整 id 再查；對不到 → 說明怎麼找 |
| MCP-9 | 工具內的錯誤回傳成 `錯誤：…` 文字，不丟例外 |
| MCP-10 | 伺服器的 `instructions` 告訴 Agent 建議的使用順序，並要求回覆使用者時保留「確定／可能／候選」的區別 |

---

## 已知限制

| 限制 | 說明 |
|---|---|
| 第一次查詢要等分析 | foreman（145 個檔案）約 20 秒；期間該次工具呼叫不會回應 |
| 過期判斷只看 `.py` 的內容 | 依賴安裝狀態、`requirements.txt`、`pyproject.toml` 變了不會觸發；用 `analyze` 的 `force=true` |
| 每次查詢都重算雜湊 | 要讀過所有 `.py`；大專案每次查詢多幾百毫秒 |
| 存檔寫進被分析的專案 | 會多一個 `.codegraph/` 資料夾（已自帶 `.gitignore`） |

沒有測試的：`python` 參數換環境後重新分析、專案唯讀時的行為、MCP-5 的「沿用上次的環境」。
