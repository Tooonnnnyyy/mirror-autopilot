"""radar CLI (spec section 5):

    python -m radar --city ottawa --dry-run --limit 40
    python radar.py --city ottawa --dry-run        # same thing, for a plain `python radar.py`

A dry run really fetches: it just writes nothing and performs no external action. Every run stops
before any sign-up, message or application — that last step belongs to Tony.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import digest, gate, redline, scoring, store
from .dedupe import dedupe
from .schema import Opportunity, TORONTO
from .sources import ADAPTERS
from .sources.base import Http, SourceBlocked

PROFILE_PATH = Path(__file__).with_name("profile.json")


def load_profile(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: profile must be a JSON object")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m radar",
        description="机会雷达: read public Ottawa opportunities, gate them, score them, print the Top 10.",
    )
    parser.add_argument("--city", default="ottawa", help="city to scan (default: ottawa)")
    parser.add_argument("--dry-run", action="store_true", help="fetch and print, write nothing")
    parser.add_argument("--limit", type=int, default=None, help="rows per source (default: profile limits)")
    parser.add_argument("--threshold", type=int, default=None, help="score floor for the Top list")
    parser.add_argument("--top", type=int, default=10, help="how many rows in the digest (default 10)")
    parser.add_argument("--sources", default="", help=f"comma separated subset of: {', '.join(ADAPTERS)}")
    parser.add_argument("--profile", default=str(PROFILE_PATH), help="path to profile.json")
    parser.add_argument("--show-more", type=int, default=5, help="extra gate-passed rows shown for checking (default 5)")
    parser.add_argument("--json", action="store_true", help="print the selected rows as JSON")
    parser.add_argument("--allow-night", action="store_true", help="run inside the quiet hours (testing only)")
    parser.add_argument("--verbose", "-v", action="store_true", help="show each source and each block")
    return parser


def collect(http: Http, profile: dict[str, Any], names: list[str], limit: int | None, verbose: bool) -> tuple[list[Opportunity], dict[str, int], dict[str, str]]:
    """Fetch every enabled source. A blocked source is logged and skipped; the others continue."""
    rows: list[Opportunity] = []
    counts: dict[str, int] = {}
    problems: dict[str, str] = {}
    for name in names:
        adapter = ADAPTERS[name]
        cap = limit or int((profile.get("sources") or {}).get(name, {}).get("max_items", 40))
        try:
            found = adapter.fetch(http, cap)
        except SourceBlocked as err:
            problems[name] = err.reason
            counts[name] = 0
            if verbose:
                print(f"! {name}: {err.reason}", file=sys.stderr)
            continue
        counts[name] = len(found)
        rows.extend(found)
        if verbose:
            print(f"# {name}: {len(found)} rows", file=sys.stderr)
    return rows, counts, problems


def run(args: argparse.Namespace) -> int:
    profile_path = Path(args.profile).expanduser()
    profile = load_profile(profile_path)

    limits = profile.get("limits") or {}
    quiet = tuple(limits.get("quiet_hours") or (0, 7))
    if not args.allow_night:
        redline.check_night((int(quiet[0]), int(quiet[1])))
    redline.check_no_secrets(profile_path, profile)
    redline.check_profile_shape(profile)

    state = store.load_state()
    budget = int(limits.get("per_day_requests", 120)) - store.requests_today(state)
    http = Http(
        min_delay=float(limits.get("min_delay_seconds", 3)),
        max_delay=float(limits.get("max_delay_seconds", 8)),
        request_budget=max(0, budget),
        quiet_hours=(int(quiet[0]), int(quiet[1])),
        stop_after_errors=int(limits.get("stop_after_consecutive_errors", 3)),
        stop_error_rate=float(limits.get("stop_after_error_rate", 0.3)),
    )

    enabled = [name for name, config in (profile.get("sources") or {}).items() if config.get("enabled", True)]
    names = [name.strip() for name in args.sources.split(",") if name.strip()] or enabled
    unknown = [name for name in names if name not in ADAPTERS]
    if unknown:
        print(f"unknown source(s): {', '.join(unknown)}; known: {', '.join(ADAPTERS)}", file=sys.stderr)
        return 2

    rows, counts, problems = collect(http, profile, names, args.limit, args.verbose)

    threshold = args.threshold if args.threshold is not None else int(profile.get("threshold", 60))
    for row in rows:
        gate.evaluate(row, profile)
        scoring.score(row, profile, now=None)

    rows = dedupe(rows)
    blocked = sum(1 for row in rows if not row.gate.passed)
    top = digest.select_top(rows, threshold, store.excluded_ids(state), limit=args.top)
    passed = sum(1 for row in rows if row.gate.passed)

    # The next few gate-passed rows, for the reader to check; they are never part of the Top list.
    picked = {row.id for row in top}
    rest = sorted(
        [row for row in rows if row.gate.passed and row.id not in picked],
        key=lambda row: row.sort_key(),
    )[: args.show_more]

    if args.dry_run:
        if args.json:
            print(json.dumps([row.to_dict() for row in top], ensure_ascii=False, indent=2))
        else:
            print(digest.render_console(top, city=args.city, total=len(rows), sources=counts, blocked=blocked, dry_run=True, rest=rest))
            if problems:
                print("\n! 跳过的来源: " + "；".join(f"{name} ({why})" for name, why in problems.items()), file=sys.stderr)
            print(f"\n过门 {passed} 条 · 进 Top {len(top)} 条 · 请求 {http.requests_made} 次 · 写库 0（dry run）")
        return 0

    # A real run: persist the digest, the rows, the state and the audit trail.
    markdown = digest.render_markdown(top, city=args.city, total=len(rows), sources=counts, blocked=blocked)
    written = store.write_digest(markdown)
    store.append_opportunities(rows)
    store.mark_seen(state, top)
    store.prune_seen(state, int(profile.get("seen_days", 90)))
    store.count_requests(state, http.requests_made)
    for name, count in counts.items():
        state["sources"][name] = {
            "last_run": store.today(),
            "rows": count,
            "problem": problems.get(name),
        }
    store.save_state(state)
    store.append_audit(
        {
            "kind": "run",
            "city": args.city,
            "sources": counts,
            "problems": problems,
            "rows": len(rows),
            "top": len(top),
            "blocked": blocked,
            "requests": http.requests_made,
            "digest": str(written),
        }
    )

    print(digest.render_console(top, city=args.city, total=len(rows), sources=counts, blocked=blocked, dry_run=False, rest=rest))
    print(f"\n写入 digest: {written.relative_to(store.DATA_DIR.parent)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except redline.RedLineError as err:
        print(f"红线: {err}", file=sys.stderr)
        try:
            store.append_audit({"kind": "redline", "error": str(err)})
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
