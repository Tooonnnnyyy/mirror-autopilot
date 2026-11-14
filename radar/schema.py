"""The unified opportunity schema (spec section 2): one dataclass, one enum per field, no silent
defaults for the fields a reader depends on."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

TYPES = ("job", "event", "club", "hackathon", "collab")
STATUS_REASONS = ("gate_failed", "relevance_low", "manual")
STATUSES = ("new", "review", "tracked", "applied", "blocked", "ignored")
MODES = ("manual", "semi", "auto")

TORONTO = ZoneInfo("America/Toronto")
RAW_TEXT_LIMIT = 500  # spec section 2: keep a fragment, never the whole page


def now_local() -> datetime:
    return datetime.now(TORONTO)


def iso_local(value: str | None) -> str | None:
    """An ISO timestamp from a source, rewritten in Ottawa time with its offset."""
    parsed = parse_time(value)
    return parsed.astimezone(TORONTO).isoformat(timespec="seconds") if parsed else None


def parse_time(value: str | None) -> datetime | None:
    """An ISO date or timestamp, aware and in UTC. Never raises; a date without a time is midnight
    Ottawa time, which is what the source page means."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if len(text) == 10:  # "2026-11-20": a calendar date, not an instant
        return parsed.replace(tzinfo=TORONTO).astimezone(timezone.utc)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def day_of(value: str | None) -> str:
    parsed = parse_time(value)
    return parsed.astimezone(TORONTO).strftime("%Y-%m-%d") if parsed else "?"


@dataclass
class Gate:
    """The hard gate's verdict (spec 4.1). A failed gate keeps the reasons as evidence."""

    passed: bool = True
    failed: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.passed = False
        if reason not in self.failed:
            self.failed.append(reason)

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.passed, "failed": list(self.failed)}


@dataclass
class Opportunity:
    """One row of data/opportunities.jsonl, exactly the fields the spec lists."""

    id: str
    type: str
    title: str
    source: str
    url: str = ""
    org: str = ""
    city: str = ""
    date: str | None = None
    deadline: str | None = None
    raw_text: str = ""
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    gate: Gate = field(default_factory=Gate)
    status: str = "new"
    # Why the row is not a plain "new" candidate (spec 2): gate_failed / relevance_low / manual.
    # Only `manual` is permanent: a rejected keyword list must never bury an opportunity forever.
    status_reason: str | None = None
    mode: str = "manual"
    tags: list[str] = field(default_factory=list)
    fetched_at: str = ""
    # Source extras used by the scorer (free / price / guests / registration). Internal: the JSON
    # written to data/opportunities.jsonl stays exactly the schema in spec section 2.
    signals: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.raw_text = (self.raw_text or "")[:RAW_TEXT_LIMIT]
        if not self.fetched_at:
            self.fetched_at = now_local().isoformat(timespec="seconds")
        # The fetcher never changes mode: only Tony can promote a row (spec section 2).
        self.mode = "manual"

    def validate(self) -> None:
        """A row missing what a reader needs is a bug in the adapter, not a row to keep."""
        missing = [name for name in ("id", "type", "title", "source") if not getattr(self, name)]
        if missing:
            raise ValueError(f"opportunity missing {', '.join(missing)}: {self.title!r}")
        if self.type not in TYPES:
            raise ValueError(f"unknown type {self.type!r} on {self.title!r}")
        if self.status not in STATUSES or self.mode not in MODES:
            raise ValueError(f"bad status/mode on {self.title!r}")
        if self.status_reason is not None and self.status_reason not in STATUS_REASONS:
            raise ValueError(f"unknown status_reason {self.status_reason!r} on {self.title!r}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["gate"] = self.gate.to_dict()
        data.pop("signals", None)
        return data

    def when(self) -> datetime | None:
        return parse_time(self.deadline) or parse_time(self.date)

    def sort_key(self) -> tuple[int, float, float, float]:
        """Spec 4.3: score desc, nearest deadline, earliest date, newest fetch."""
        deadline = parse_time(self.deadline)
        date = parse_time(self.date)
        fetched = parse_time(self.fetched_at)
        return (
            -self.score,
            deadline.timestamp() if deadline else float("inf"),
            date.timestamp() if date else float("inf"),
            -(fetched.timestamp() if fetched else 0.0),
        )
