"""給網頁的 HTTP API。只呼叫 query/ 與 service，不自己做圖的運算。規格：docs/spec/web.md"""

from .app import create_app

__all__ = ["create_app"]
