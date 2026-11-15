# codegraph_Fable

把一個 Python 專案分析成**程式碼知識圖譜**，回答兩種使用者的問題：

| 使用者 | 怎麼用 | 得到什麼 |
|---|---|---|
| Agent | MCP 工具 | 專案架構、定義在哪、改這裡影響誰、function 做了什麼 |
| 人 | 網頁（2D／3D） | 看得到的架構圖，點節點看細節與影響範圍 |

全程是程式分析，不呼叫 LLM、不需要資料庫。

---

## 重點

| 項目 | 做法 |
|---|---|
| 本地與外部套件不混淆 | `import` 會載入哪個檔案，由專案環境裡 Python 自己的模組查找決定，再分成標準庫／第三方／本地 |
| 呼叫關係 | 由 Jedi 做型別推論；解不出的不丟掉，記在呼叫者上並附原因 |
| 不假裝完整 | 影響範圍分「確定／可能／候選」，每個答案附「專案內還有幾個呼叫解不出」 |
| function 細節 | 簽名、呼叫了誰、讀寫的狀態、副作用、例外、原始碼，每項標「準確／推論／估計」 |
| 可量測 | 實際執行專案的測試、記錄真正發生的呼叫，量出靜態分析漏了多少 |

---

## 安裝

需要 Python 3.11+；網頁前端另需 Node 18+。

```bash
conda create -n codegraph_fable python=3.13
conda activate codegraph_fable
pip install -r requirements.txt && pip install -e .

cd frontend && npm install --legacy-peer-deps && npm run build && cd ..   # 只有要用網頁時
```

---

## 使用

| 用途 | 指令 |
|---|---|
| 分析並存成 JSON | `python -m codegraph_fable.analyze <專案> -o 結果.json --python <專案環境的 python>` |
| 給 Agent（MCP，stdio） | `python -m codegraph_fable.mcp` |
| 網頁 | `CODEGRAPH_ALLOWED_ROOTS=<允許分析的資料夾> python -m codegraph_fable.web --reload`，開 http://127.0.0.1:8000 |
| 量靜態分析漏了多少 | `python -m codegraph_fable.trace <專案> --python <專案環境的 python> -- -m pytest -q -p no:cacheprovider` |

讓 Claude Code 使用 MCP（一次）：

```bash
claude mcp add codegraph -- <codegraph_fable 環境的 python> -m codegraph_fable.mcp
```

注意：

- `--python` 要指向**被分析專案**的 Python（依賴裝在那裡）；沒指定就用本工具的環境，第三方套件會被標成沒安裝。
- 網頁後端必須設定 `CODEGRAPH_ALLOWED_ROOTS`，沒設定就拒絕所有路徑；只聽本機。
- `trace` 會**執行被分析專案的程式碼**。
- 透過 MCP 或網頁分析過的專案，底下會多一個 `.codegraph/` 資料夾存結果（自帶 `.gitignore`）。

---

## MCP 工具

| 工具 | 回答什麼 |
|---|---|
| `analyze` | 分析一個專案，回摘要 |
| `overview` | 專案全貌 |
| `find` | 某個名字定義在哪 |
| `impact` | 改這裡影響誰 |
| `detail` | 一個 function 做了什麼 |

---

## 結構

```
src/codegraph_fable/
├── model/     圖的資料格式
├── store/     JSON 存檔
├── analyze/   專案 → 圖（定義、import、呼叫、繼承、引用）
├── query/     對圖提問（影響範圍、細節、概覽、畫面用的收合視圖）
├── service.py 取得分析結果，原始碼變了就重新分析
├── mcp/       給 Agent 的介面
├── web/       給網頁的 API
└── trace/     執行時觀察
frontend/      網頁（Vite ＋ React ＋ Cytoscape ＋ three.js）
tests/         測試與帶標準答案的測試專案
docs/          規格與紀錄
```

---

## 文件

| 文件 | 內容 |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | 任務與進度 |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | 每個任務做了什麼、改了哪些檔案、怎麼驗證 |
| [`docs/spec/model.md`](docs/spec/model.md) | 圖的格式與 id 規則 |
| [`docs/spec/analyze.md`](docs/spec/analyze.md) | 分析的規則與已知限制 |
| [`docs/spec/query.md`](docs/spec/query.md) | 查詢 |
| [`docs/spec/mcp.md`](docs/spec/mcp.md) | MCP 介面 |
| [`docs/spec/web.md`](docs/spec/web.md) | 網頁的 API、視圖與前端 |
| [`docs/spec/trace.md`](docs/spec/trace.md) | 執行時觀察與量測結果 |

---

## 開發

```bash
pytest                          # 後端測試
ruff check src tests && ruff format src tests
cd frontend && npm test && npx tsc -b
```

---

## 現況與限制

| 項目 | 狀態 |
|---|---|
| 分析對象 | 只支援 Python |
| 後端 | 有自動測試（133 個） |
| 網頁的畫面與互動 | 只有資料轉換有測試；畫面靠實際操作確認 |
| 解不出的呼叫 | 未標註型別的參數、`getattr` 等動態呼叫。會計數並列為候選 |
| 量測 | 一個專案的後端跑自己的測試：479 組實際呼叫，查得到 478 組 |

這個專案是以另一個既有專案 `codegraph` 為參照重新設計的。

文件裡提到的 `CLAUDE.md` 是開發時給 Claude Code 的工作指示，只留在本機、不在這個 repo 裡；文件中 D（決定）與 F（分析框架規則）的編號定義在那份檔案。
