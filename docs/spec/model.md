# model 規格

圖的資料格式與存檔。程式：`src/codegraph_fable/model/`、`src/codegraph_fable/store/`。測試：`tests/test_model.py`。

---

## 形狀

```json
{ "nodes": [{ "id", "type", "label", "properties" }],
  "edges": [{ "source", "target", "type", "properties" }],
  "meta":  {} }
```

- `type` 是資料：多一種型別不會多一個 key。
- 兩個節點之間可以有多條邊（每個 import 敘述一條）。
- 存檔格式＝這個形狀的 JSON（`store.save` / `store.load`）。存放位置尚未定，呼叫端自己給路徑。

---

## 節點

| type | id | 主要 properties |
|---|---|---|
| `repo` | `repo:.` | — |
| `directory` | `dir:<相對路徑>` | — |
| `file` | `file:<相對路徑>` | `language`、`parse_error`、`has_main_guard` |
| `class` | `class:<檔案>::<完整名字>` | `line`、`end_line`、`bases`、`decorators`、`docstring` |
| `function` | `function:<檔案>::<完整名字>` | `line`、`end_line`、`signature`、`is_async`、`is_method`、`decorators`、`docstring` |
| `variable` | `variable:<檔案>::<完整名字>` | `line`、`end_line`、`annotation` |
| `external_package` | `ext:<最頂層模組名>` | `category`、`installed`、`distributions`、`declared` |

- 完整名字例：`Runner.run`、`Runner.fetch.inner`。
- 同一個檔案內重複定義的 class／function：第二個起 id 帶 `@行號`（`helper@30`），並有 `redefinition: true`。
- 解不出的使用點記在節點上：`unresolved_calls`（file／class／function；含解不出的 `@property` 讀取）、`unresolved_bases`（class），每筆有 `line`、`text`、`reason`。
- 帶條件才出現的欄位：`parse_error`（有錯才有）、`has_main_guard`（為真才有）、`decorators`、`docstring`、`annotation`（有才有）、`distributions`（查得到套件名才有）、`distribution_source`（套件名是猜的才有）、`declared`（只在 `third_party`／`unknown`）。
- `category`：`stdlib`（標準庫）／`third_party`（第三方）／`unknown`（沒安裝也沒宣告）／`excluded`（在專案內但被掃描排除）。

---

## 邊

| type | 方向 | properties |
|---|---|---|
| `contains` | repo／directory → directory／file | — |
| `defines` | file／class／function → 內層定義 | — |
| `imports` | file → file／directory／external_package | 見 `analyze.md` |
| `calls` | file／class／function → function／class／external_package | 見 `analyze.md`（AN-U） |
| `inherits` | class → class／external_package | 同上 |
| `overrides` | function → function（子類別方法 → 祖先的同名方法；或實作 → Protocol 的方法） | `via: protocol`（只有 Protocol 的情況才有）、`partial: true`（只實作了 Protocol 的一部分方法） |
| `observed_calls` | file／function → function | `count`、`evidence: runtime`。只有 `trace.merge` 會加，見 `trace.md` |
| `references` | file／class／function → class／function／variable | 同上 |

邊的 properties 裡若有節點 id（`imports` 的 `alt_target`），M2 不檢查它；由 analyze 保證存在（有測試）。

---

## 規則

| # | 規則 |
|---|---|
| M1 | 節點 id 不可重複 |
| M2 | 每條邊的兩端都必須是存在的節點 |
| M3 | `save` 前與 `load` 後都會檢查 M1、M2，不合法就丟 `GraphError`。JSON 缺欄位或多欄位時丟的是 `KeyError`／`TypeError`；`load` 不檢查 `schema_version` |
| M4 | `meta.schema_version` 目前是 1；格式不相容時加 1 |
