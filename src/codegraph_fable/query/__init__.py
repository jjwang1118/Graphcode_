"""查詢層：只讀分析結果（Graph），不讀專案、不碰 Jedi。規格：docs/spec/query.md

唯一的例外是 `detail` 會依行號從磁碟讀 function 的原始碼。
"""

from .detail import SIDE_EFFECTS, detail
from .impact import impact
from .index import Index, owner_file
from .overview import file_dependencies, overview
from .view import EDGE_TYPES, locate, view

__all__ = [
    "EDGE_TYPES",
    "SIDE_EFFECTS",
    "Index",
    "detail",
    "file_dependencies",
    "impact",
    "locate",
    "overview",
    "owner_file",
    "view",
]
