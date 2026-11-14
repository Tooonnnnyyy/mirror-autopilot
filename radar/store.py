"""Files on disk (spec section 5): the opportunity log, the digest, the state and the audit trail.

`--dry-run` writes none of them. Everything lives in the repo's `data/` folder and stays local
(red line 9: scraped text never leaves this machine).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .schema import Opportunity, TORONTO

DATA_DIR = Path(os.environ.get("RADAR_DATA") or Path(__file__).resolve().parents[1] / "data")
OPPORTUNITIES = DATA_DIR / "opportunities.jsonl"
STATE = DATA_DIR / "state.json"
AUDIT = DATA_DIR / "events.jsonl"
DIGESTS = DATA_DIR / "digests"


def today() -> str:
    return datetime.now(TORONTO).strftime("%Y-%m-%d")


_today = today  # kept for the internal callers below


def load_state(path: Path = STATE) -> dict[str, Any]:
    """seen ids, per-day counters, per-source last run. A missing or broken file is an empty state."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    state = raw if isinstance(raw, dict) else {}
    state.setdefault("seen_ids", {})
    # Ids Tony ignored by hand: these never come back. Rows skipped for low relevance or a failed
    # gate are NOT stored here, so a better keyword list can still surface them later (spec 2).
    state.setdefault("manual_ids", {})
    state.setdefault("days", {})
    state.setdefault("sources", {})
    return state


def save_state(state: dict[str, Any], path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def excluded_ids(state: dict[str, Any]) -> set[str]:
    """Everything the digest must not show again: recent seen ids plus permanent manual ignores."""
    return set(state.get("seen_ids", {})) | set(state.get("manual_ids", {}))


def requests_today(state: dict[str, Any]) -> int:
    return int(state["days"].get(_today(), {}).get("requests", 0))


def count_requests(state: dict[str, Any], amount: int) -> None:
    day = state["days"].setdefault(_today(), {"requests": 0})
    day["requests"] = int(day.get("requests", 0)) + amount
    # keep two weeks of counters; the file is read by humans too
    for old in sorted(state["days"])[:-14]:
        state["days"].pop(old, None)


def mark_seen(state: dict[str, Any], rows: Iterable[Opportunity]) -> int:
    """Remember every id shown; returns how many were new. Entries older than `seen_days` drop out."""
    today = _today()
    shown = state.setdefault("seen_ids", {})
    new = 0
    for row in rows:
        if row.id not in shown:
            shown[row.id] = today
            new += 1
    return new


def prune_seen(state: dict[str, Any], keep_days: int = 90) -> None:
    from datetime import timedelta

    cutoff = date.fromisoformat(_today()) - timedelta(days=keep_days)
    shown = state.setdefault("seen_ids", {})
    stale = [key for key, value in shown.items() if _before(value, cutoff)]
    for key in stale:
        shown.pop(key, None)


def _before(value: str, cutoff: date) -> bool:
    try:
        return date.fromisoformat(value) < cutoff
    except ValueError:
        return True


def append_opportunities(rows: Iterable[Opportunity], path: Path = OPPORTUNITIES) -> int:
    """Append rows, one JSON object per line; an id already in the file is not written twice."""
    path.parent.mkdir(parents=True, exist_ok=True)
    known: set[str] = set()
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    known.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    written = 0
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            if row.id in known:
                continue
            handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
            known.add(row.id)
            written += 1
    return written


def append_audit(entry: dict[str, Any], path: Path = AUDIT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {**entry, "at": datetime.now(TORONTO).isoformat(timespec="seconds")}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_digest(text: str, day: str | None = None, path: Path = DIGESTS) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    target = path / f"{day or _today()}.md"
    target.write_text(text, encoding="utf-8")
    return target
