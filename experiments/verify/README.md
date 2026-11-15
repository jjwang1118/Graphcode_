# verify

用其他專案驗證分析結果是否正確的腳本與設定。**一次性的驗證，不是產品程式碼。**

| 檔案 | 用途 |
|---|---|
| `check.py` | 用另一套獨立的方法算答案（自己掃 import、在專案環境裡問 Python `issubclass`、用名字找呼叫者、另外算循環），和 codegraph_fable 的答案比對 |
| `measure.py` | 實際執行專案的測試，量圖涵蓋了多少真正發生的呼叫（觀察結果會存在 `out/`，可重用） |
| `precision.py` | 假邊的粗篩：每條專案內的 `calls` 邊，回原始碼看那幾行有沒有出現被呼叫者的名字，列出沒有的供人工看 |
| `foreman.json`、`envharness.json` | `check.py` 要問的問題（對應兩個評測專案） |

`envs/`（各專案的虛擬環境）與 `out/` 不進版控。

---

## 怎麼跑

以下 `<專案>` 是被驗證專案的資料夾，`<python>` 是裝了它的依賴的 Python。

```bash
python check.py <專案> <python> foreman.json
python measure.py <專案> <python> out/foreman.json -- -m pytest -q -p no:cacheprovider
python precision.py <專案> <python>
```

| 注意 | 說明 |
|---|---|
| 環境只裝依賴，不把專案本身裝進去 | 避免在被驗證的專案裡留下檔案。src 佈局的專案執行時加 `PYTHONPATH=src` |
| `measure.py` 會執行專案的測試 | 加 `-p no:cacheprovider` 才不會留 `.pytest_cache` |

結果記在 `docs/spec/trace.md`「量測結果」與 `docs/CHANGELOG.md`。
