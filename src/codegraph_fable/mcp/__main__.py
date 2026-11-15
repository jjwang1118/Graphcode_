"""啟動 MCP 伺服器（stdio）：python -m codegraph_fable.mcp"""

from .server import build_server

if __name__ == "__main__":
    build_server().run()
