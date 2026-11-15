"""MCP 伺服器：五個工具。規格：docs/spec/mcp.md"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from ..model import Node
from ..query import Index, detail, impact, overview
from ..service import Service
from . import render

INSTRUCTIONS = (
    "codegraph：把一個 Python 專案分析成程式碼知識圖譜，回答架構與影響範圍的問題。"
    "每個工具的 project 參數是專案資料夾的絕對路徑。第一次查詢會自動分析（大專案需數十秒），"
    "之後原始碼有變動也會自動重新分析。"
    "建議順序：overview 看全貌 → find 找定義 → impact 看「改這裡影響誰」→ detail 看 function 做了什麼。"
    "答案標有「確定／可能／候選」與完整度，回覆使用者時請保留這些區別。"
)


def _target(index: Index, name: str) -> Node | str:
    found = index.find(name)
    if len(found) == 1:
        return found[0]
    if not found:
        return (
            f"找不到 `{name}`。先用 find 查名字，或給完整 id（例如 function:app/util.py::helper）。"
        )
    return "有多個同名的定義，請用其中一個完整 id 再查一次：\n" + render.render_find(name, found)


def build_server(service: Service | None = None) -> MCPServer:
    service = service or Service()
    server = MCPServer("codegraph", instructions=INSTRUCTIONS)

    def guarded(action):  # 工具回傳文字；錯誤也用文字說清楚，不讓 Agent 只看到例外
        try:
            return action()
        except Exception as error:
            return f"錯誤：{type(error).__name__}: {error}"

    @server.tool()
    def analyze(project: str, python: str = "", force: bool = False) -> str:
        """分析（或重新分析）一個 Python 專案，回傳摘要：節點與關係數量、import 分類、解不出的數量、缺少的依賴。

        python：專案環境的 Python 執行檔路徑（依賴裝在那裡）。不給時依序用：上次用的 → 專案內的 .venv → 本工具的 Python。
        force：即使原始碼沒變也重新分析。
        其他工具會自動分析，通常不必先呼叫這個；要換環境或確認分析狀態時才用。
        """

        def run() -> str:
            index, source = service.index(project, python or None, force)
            return render.render_summary(index, source)

        return guarded(run)

    @server.tool(name="overview")
    def overview_tool(project: str) -> str:
        """專案全貌：各資料夾的檔案數、用到的外部套件（標準庫／第三方／未知）、可直接執行的檔案、被最多檔案依賴的檔案。"""
        return guarded(lambda: render.render_overview(overview(service.index(project)[0])))

    @server.tool()
    def find(project: str, name: str) -> str:
        """依名字找 class／function／變數／檔案的定義位置與簽名。name 可以是 `helper`、`Foo.go`、`app/util.py::helper` 或完整 id。"""
        return guarded(lambda: render.render_find(name, service.index(project)[0].find(name)))

    @server.tool(name="impact")
    def impact_tool(project: str, target: str, depth: int = 3, limit: int = 60) -> str:
        """改 target 會影響誰：一層層列出呼叫它、引用它、繼承它、import 它的地方。

        target：名字或完整 id（同 find）。改檔案或 class 等於改它裡面的全部。
        depth：往外幾層（1＝只看直接使用者）。limit：最多列幾筆，超過會寫出總數。
        每筆標「確定」或「可能」；另列「候選」（解不出的呼叫裡提到這個名字，未確認）與完整度。
        """

        def run() -> str:
            index = service.index(project)[0]
            node = _target(index, target)
            if isinstance(node, str):
                return node
            return render.render_impact(impact(index, node.id, max_depth=depth), limit)

        return guarded(run)

    @server.tool(name="detail")
    def detail_tool(project: str, target: str, source: bool = True) -> str:
        """一個 function（或 class）做了什麼：簽名、呼叫了誰（專案內／外部／解不出）、讀寫哪些 self 屬性、副作用（檔案、網路、子行程…）、會丟出的例外、原始碼。

        每個區塊標可靠度：準確（直接來自原始碼）／推論（引擎解析）／估計（對照表）。
        source=False 時不附原始碼。
        """

        def run() -> str:
            index = service.index(project)[0]
            node = _target(index, target)
            if isinstance(node, str):
                return node
            return render.render_detail(detail(index, node.id), source)

        return guarded(run)

    return server
