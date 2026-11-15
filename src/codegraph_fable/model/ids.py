"""節點 id 規則：型別前綴 ＋ 以檔案路徑為基底。規格：docs/spec/model.md"""

from __future__ import annotations

REPO_ID = "repo:."


def file_id(rel_path: str) -> str:
    return f"file:{rel_path}"


def dir_id(rel_path: str) -> str:
    return f"dir:{rel_path}"


def ext_id(top_level_name: str) -> str:
    return f"ext:{top_level_name}"


def decl_id(kind: str, rel_path: str, qualname: str) -> str:
    """kind 是 class / function / variable；qualname 例如 `Runner.run`。"""
    return f"{kind}:{rel_path}::{qualname}"
