"""The daily Top 10 and its Markdown file (spec 4.4).

Selection: gate passed, status new, relevance not low, score at or above the threshold, and the id
not shown in the last 90 days (or ever, for a row Tony ignored by hand).

Ranking: score, then nearest deadline, then earliest date, then newest fetch — date never adds
points, it only breaks ties.

Coverage: when candidates allow it, at least one job, one event and one club are kept, and only a
`relevance: high` row may take a coverage slot. If fewer than 7 rows are tech/career/builder, the
digest says so instead of padding the list.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .schema import Opportunity, TORONTO, day_of

CATEGORY = {"job": "工作", "event": "活动", "hackathon": "黑客松", "club": "社团", "collab": "合作"}
KIND = {"hackathon": "event", "collab": "club"}  # what counts as an event / club for coverage
COVERAGE = ("job", "event", "club")
RELEVANT_BUCKETS = ("tech", "career", "builder")
SHORTFALL_TARGET = 7


def level_of(row: Opportunity) -> str:
    """The relevance level from the fixed first reason (spec 4.3 rule 4)."""
    return row.reasons[0].split(":")[1].split("(")[0].strip() if row.reasons else "mid"


def bucket_of_row(row: Opportunity) -> str:
    for reason in row.reasons[:3]:
        if reason.startswith("bucket: "):
            return reason.split(":", 1)[1].strip()
    return "tech"


def eligible(rows: Iterable[Opportunity], threshold: int, excluded: set[str]) -> list[Opportunity]:
    return [
        row
        for row in rows
        if row.gate.passed and row.status == "new" and row.score >= threshold and row.id not in excluded
    ]


def select_top(rows: list[Opportunity], threshold: int, excluded: set[str], limit: int = 10) -> list[Opportunity]:
    """The Top N: coverage first (high relevance only), then by rank."""
    candidates = sorted(eligible(rows, threshold, excluded), key=lambda row: row.sort_key())
    picked: list[Opportunity] = []
    for wanted in COVERAGE:
        for row in candidates:
            if len(picked) >= limit:
                break
            if KIND.get(row.type, row.type) == wanted and level_of(row) == "high" and row not in picked:
                picked.append(row)
                break
    for row in candidates:
        if len(picked) >= limit:
            break
        if row not in picked:
            picked.append(row)
    return sorted(picked, key=lambda row: row.sort_key())


def shortfall(rows: list[Opportunity]) -> tuple[int, list[str]]:
    """How many of the Top rows are tech/career/builder, and which buckets are missing."""
    relevant = [row for row in rows if bucket_of_row(row) in RELEVANT_BUCKETS]
    seen = {bucket_of_row(row) for row in relevant}
    missing = [name for name in RELEVANT_BUCKETS if name not in seen]
    return len(relevant), missing


def _when(row: Opportunity) -> str:
    if row.deadline:
        return f"截止 {day_of(row.deadline)}"
    if row.date:
        return day_of(row.date)
    return "日期未知"


def _why(row: Opportunity) -> str:
    return "；".join(row.reasons[3:6]) if len(row.reasons) > 3 else "无附加证据"


def render_markdown(rows: list[Opportunity], *, city: str, total: int, sources: dict[str, int], blocked: int) -> str:
    today = datetime.now(TORONTO).strftime("%Y-%m-%d")
    relevant, missing = shortfall(rows)
    lines = [
        f"# 机会雷达 · {city} · {today}",
        "",
        f"抓取 {total} 条，门拦 {blocked} 条，入 Top {len(rows)} 条，其中 tech/career/builder {relevant} 条。"
        f"来源: " + "，".join(f"{name} {count} 条" for name, count in sources.items()) + "。",
        "",
    ]
    if relevant < SHORTFALL_TARGET:
        lines.append(f"> shortfall: {relevant}/{len(rows)} 相关（目标 ≥{SHORTFALL_TARGET}），缺 {', '.join(missing) or '—'}。")
        lines.append("")
    if not rows:
        lines.append("今天没有过门且高相关的候选。")
        return "\n".join(lines) + "\n"

    order: list[str] = []
    for row in rows:
        kind = CATEGORY.get(row.type, row.type)
        if kind not in order:
            order.append(kind)
    for kind in order:
        lines.append(f"## {kind}")
        for row in rows:
            if CATEGORY.get(row.type, row.type) != kind:
                continue
            lines.append(
                f"- **{row.title}** · {row.org or '主办未标明'} · {_when(row)} · {row.score} 分 · "
                f"{level_of(row)} · [{row.source}]({row.url})"
            )
            lines.append(f"  - {'；'.join(row.reasons[:3])}")
            lines.append(f"  - 证据: {_why(row)}")
        lines.append("")
    lines.append("---")
    lines.append("对外动作(报名/私信/投递)都不在这个 CLI 里；点链接自己决定，或让 Agent 准备草稿等你确认。")
    return "\n".join(lines) + "\n"


def render_console(rows: list[Opportunity], *, city: str, total: int, sources: dict[str, int], blocked: int, dry_run: bool, rest: list[Opportunity] | None = None) -> str:
    relevant, missing = shortfall(rows)
    out = [
        f"机会雷达 · {city} · Top {len(rows)} 条（抓 {total}，门拦 {blocked}，tech/career/builder {relevant} 条）",
        "来源: " + "，".join(f"{name} {count}" for name, count in sources.items()),
        "dry run: 不写库，不做任何对外动作" if dry_run else "已写入 data/",
        "",
    ]
    if relevant < SHORTFALL_TARGET:
        out.append(f"shortfall: {relevant}/{len(rows) or 0} 相关（目标 ≥{SHORTFALL_TARGET}），缺 {', '.join(missing) or '—'}")
        out.append("")
    if not rows:
        out.append("今天没有过门且高相关的候选（看 data/events.jsonl 里被拦/降档的原因）。")
        return "\n".join(out)
    for index, row in enumerate(rows, 1):
        out.append(f"{index:>2}. {row.score:3d} 分 · {CATEGORY.get(row.type, row.type)} · {_when(row)} · {row.title}")
        out.append(f"    {row.org or '主办未标明'} · {row.source} · {row.url}")
        out.append(f"    {row.reasons[0]} · {row.reasons[1]} · {row.reasons[2]}")
        out.append(f"    证据: {_why(row)}")

    # Everything else that passed the gate: shown for checking, explicitly not in the Top list.
    if rest:
        out.append("")
        out.append(f"其余过门候选（不进 Top，供核对，共 {len(rest)} 条）")
        for index, row in enumerate(rest, 1):
            out.append(f"  {index:>2}. {row.score:3d} 分 · {CATEGORY.get(row.type, row.type)} · {_when(row)} · {row.title}")
            out.append(f"      {row.org or '主办未标明'} · {row.source} · {row.url}")
            out.append(f"      {row.reasons[0]} · {row.reasons[1]} · {row.reasons[2]}")
            out.append(f"      证据: {_why(row)}")
    return "\n".join(out)
