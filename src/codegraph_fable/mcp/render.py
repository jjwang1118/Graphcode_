"""把查詢結果排成精簡文字。規格：docs/spec/mcp.md

規則：截斷一定寫出總數；每個答案都附完整度；不確定的要標出來。
"""

from __future__ import annotations

from typing import Any

from ..model import Node
from ..query import Index

_CERTAINTY = {"certain": "確定", "possible": "可能"}
_RELIABILITY = {"exact": "準確", "inferred": "推論", "heuristic": "估計"}


def short(node_id: str) -> str:
    kind, _, rest = node_id.partition(":")
    return f"{kind} {rest}"


def _lines(lines: list[int], limit: int = 6) -> str:
    if not lines:
        return ""
    shown = ",".join(str(n) for n in lines[:limit])
    return f"L{shown}" + (f"…(共{len(lines)}處)" if len(lines) > limit else "")


def _completeness(calls: dict[str, Any] | None, available: bool) -> str:
    if not available or not calls:
        return "完整度：沒有呼叫關係的資料（Jedi 不可用或已停用），答案只含 import。"
    return (
        f"完整度：專案共 {calls['expressions']} 個呼叫，解出 {calls['resolved']}，"
        f"解不出 {calls['unresolved']}（解不出的不在答案裡）。"
    )


def render_summary(index: Index, source: str) -> str:
    meta = index.graph.meta
    counts, imports = meta["counts"], meta["imports"]
    uses = meta.get("uses", {})
    out = [
        f"專案：{meta['root']}",
        f"分析結果來源：{source}",
        f"Python 環境：{meta['python']['executable']}（{meta['python']['version']}）",
        f"搜尋根目錄：{', '.join(meta['search_roots'])}",
        "節點：" + "、".join(f"{k} {v}" for k, v in counts["nodes"].items()),
        "關係：" + "、".join(f"{k} {v}" for k, v in counts["edges"].items()),
        (
            f"import：共 {imports['total']}（本地 {imports['local']}、標準庫 {imports['stdlib']}、"
            f"第三方 {imports['third_party']}、未知 {imports['unknown']}、解不出 {imports['unresolved']}）"
        ),
        _completeness(uses.get("calls"), uses.get("available", False)),
    ]
    if meta["missing_dependencies"]:
        missing = meta["missing_dependencies"]
        out.append(
            f"⚠ 有宣告但這個環境沒安裝的套件（{len(missing)}）：{', '.join(missing[:15])}"
            + ("…" if len(missing) > 15 else "")
            + "。用到它們的呼叫可能解不出；可用 python 參數指定專案的環境後重新 analyze。"
        )
    if meta["parse_errors"]:
        out.append(
            f"⚠ 語法錯誤、未分析的檔案：{', '.join(e['file'] for e in meta['parse_errors'][:10])}"
        )
    return "\n".join(out)


def render_overview(result: dict[str, Any]) -> str:
    done = result["completeness"]
    out = [f"專案：{result['root']}", "Python 檔數（依最上層資料夾）："]
    out += [f"  {name}: {count}" for name, count in list(result["packages"].items())[:20]]
    for category, names in result["externals"].items():
        shown = ", ".join(names[:30]) + (f" …(共{len(names)})" if len(names) > 30 else "")
        out.append(f"外部套件 {category}（{len(names)}）：{shown}")
    if result["entry_points"]:
        entries = result["entry_points"]
        out.append(
            f"可直接執行的檔案（{len(entries)}）：{', '.join(entries[:15])}"
            + ("…" if len(entries) > 15 else "")
        )
    out.append("被最多檔案依賴：")
    out += [
        f"  {item['file']}（{item['dependents']} 個檔案）" for item in result["most_used_files"]
    ]
    out.append(_completeness(done["calls"], done["uses_available"]))
    if done["unresolved_imports"] or done["parse_errors"]:
        out.append(
            f"解不出的 import：{done['unresolved_imports']}；語法錯誤的檔案：{done['parse_errors']}"
        )
    return "\n".join(out)


def render_find(name: str, nodes: list[Node], limit: int = 30) -> str:
    if not nodes:
        return f"找不到名為 `{name}` 的定義。"
    out = [
        f"`{name}` 找到 {len(nodes)} 筆"
        + (f"（只列前 {limit} 筆）" if len(nodes) > limit else "")
        + "："
    ]
    for node in nodes[:limit]:
        props = node.properties
        where = f"  L{props['line']}–{props['end_line']}" if "line" in props else ""
        out.append(f"  {short(node.id)}{where}  {props.get('signature', '')}".rstrip())
    return "\n".join(out)


def render_impact(result: dict[str, Any], limit: int = 60) -> str:
    done = result["completeness"]
    out = [
        f"影響範圍：{short(result['target'])}",
        (
            f"受影響 {done['affected']}（確定 {done['certain']}、可能 {done['possible']}）；"
            f"候選 {done['candidates']}"
        ),
    ]
    shown = 0
    for depth, level in enumerate(result["levels"], 1):
        if shown >= limit:
            break
        out.append(f"第 {depth} 層（{len(level)}）：")
        for entry in sorted(level, key=lambda e: (e["certainty"] != "certain", e["id"])):
            if shown >= limit:
                break
            via = (
                f"（經 {short(entry['through'])}）" if entry["through"] != result["target"] else ""
            )
            out.append(
                f"  [{_CERTAINTY[entry['certainty']]}] {entry['relation']} ← {short(entry['id'])} "
                f"{_lines(entry['lines'])}{via}".rstrip()
            )
            shown += 1
    if shown < done["affected"]:
        out.append(
            f"…只列出 {shown} 筆，共 {done['affected']} 筆。提高 limit 或降低 depth 可看其餘。"
        )
    if result["overridden_by"]:
        out.append("被這些子類別方法覆寫（要一併檢查）：")
        out += [f"  {short(n)}" for n in result["overridden_by"][:20]]
    if result["candidates"]:
        candidates = result["candidates"]
        out.append(f"候選（解不出的呼叫裡提到這個名字，未確認，共 {len(candidates)}）：")
        for item in candidates[:20]:
            out.append(f"  {short(item['id'])} L{item['line']} `{item['text']}` — {item['reason']}")
        if len(candidates) > 20:
            out.append(f"  …只列前 20 筆，共 {len(candidates)} 筆。")
    if done["uses_available"]:
        out.append(
            f"完整度：專案內有 {done['unresolved_calls_in_project']} 個呼叫解不出，"
            "真正受影響的可能比上面多。「可能」＝多種型別之一或經父類別方法分派。"
        )
    else:
        out.append("完整度：沒有呼叫關係的資料，上面只含 import 關係。")
    return "\n".join(out)


def _tag(block: dict[str, Any], note: str = "") -> str:
    return f"【{_RELIABILITY[block['reliability']]}{'；' + note if note else ''}】"


def render_detail(result: dict[str, Any], include_source: bool = True) -> str:
    out = [f"{short(result['id'])}　（{result['file']} L{result['line']}–{result['end_line']}）"]
    interface = result.get("interface")
    if interface:
        if result["type"] == "function":
            flags = [
                f
                for f, on in (("async", interface["is_async"]), ("方法", interface["is_method"]))
                if on
            ]
            out.append(
                f"介面{_tag(interface)} {interface['signature']}  {' '.join(flags)}".rstrip()
            )
            if interface["decorators"]:
                out.append(f"  裝飾器：{', '.join(interface['decorators'])}")
        else:
            out.append(f"介面{_tag(interface)} 繼承：{', '.join(interface['bases']) or '無'}")
            out.append(
                f"  成員（{len(interface['members'])}）："
                + ", ".join(m.split("::")[-1] for m in interface["members"][:40])
            )
        if interface.get("docstring"):
            out.append(f"  說明：{interface['docstring'].strip().splitlines()[0]}")
    calls = result["calls"]
    out.append(f"呼叫{_tag(calls, '依原始碼位置，非執行順序')}")
    for call in calls["local"]:
        marks = "".join(
            f" [{m}]" for m in (call.get("via"), "可能" if call.get("ambiguous") else None) if m
        )
        out.append(f"  專案內 {short(call['target'])} {_lines(call['lines'])}{marks}")
    for call in calls["external"]:
        out.append(f"  外部 {call['callee']} {_lines(call['lines'])}")
    for item in calls["unresolved"]:
        out.append(f"  解不出 L{item['line']} `{item['text']}` — {item['reason']}")
    if not (calls["local"] or calls["external"] or calls["unresolved"]):
        out.append("  無")
    references = result["references"]
    if references["targets"]:
        out.append(f"引用{_tag(references)}：" + ", ".join(short(t) for t in references["targets"]))
    state = result.get("state")
    if state:
        out.append(
            f"狀態{_tag(state, '只含直接寫成 ' + (state['receiver'] or 'self') + '.x 的')} "
            f"讀：{', '.join(state['reads']) or '無'}；寫：{', '.join(state['writes']) or '無'}"
            + (
                f"；寫入全域變數：{', '.join(state['global_writes'])}"
                if state["global_writes"]
                else ""
            )
        )
    effects = result["side_effects"]

    def group(found: dict[str, list[dict[str, Any]]], indirect: bool) -> str:
        parts = []
        for category, items in found.items():
            names = sorted(
                {
                    i["callee"] + (f" 於 {i['in'].split('::')[-1]}" if indirect else "")
                    for i in items
                }
            )
            parts.append(f"{category}（{', '.join(names[:4])}{'…' if len(names) > 4 else ''}）")
        return "；".join(parts) or "無"

    out.append(f"副作用{_tag(effects, '對照表分類，沒列到不代表沒有')}")
    out.append(f"  直接：{group(effects['direct'], False)}")
    out.append(f"  間接（被呼叫者造成）：{group(effects['indirect'], True)}")
    if "raises" in result:
        raises = result["raises"]
        out.append(
            f"例外{_tag(raises, '只含明寫的 raise')}：{', '.join(raises['exceptions']) or '無'}"
        )
        returns = result["returns"]
        kind = (
            "產生器"
            if returns["is_generator"]
            else f"{returns['return_statements']} 個有回傳值的 return"
        )
        out.append(f"回傳{_tag(returns)}：{kind}")
    source = result["source"]
    if not source["available"]:
        out.append(f"原始碼：{source['note']}")
    elif include_source:
        out.append(f"原始碼{_tag(source)}：")
        out.append(source["text"])
    return "\n".join(out)
