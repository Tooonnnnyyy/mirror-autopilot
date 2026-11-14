"""Shared helpers for the radar tests: profile, fixtures, and a row builder. No network."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radar.schema import Gate, Opportunity  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
PROFILE = json.loads((ROOT / "radar" / "profile.json").read_text(encoding="utf-8"))


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def future(days: int = 7) -> str:
    when = datetime.now(timezone.utc) + timedelta(days=days)
    return when.isoformat(timespec="seconds")


def past(days: int = 3) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def op(**overrides) -> Opportunity:
    base = dict(
        id="eventbrite_test1",
        type="event",
        title="Ottawa AI Builders Night",
        org="Ottawa Tech Thursday",
        url="https://luma.com/test1",
        city="Ottawa",
        date=future(7),
        source="luma",
        raw_text="AI agents, hackathon, builders",
        signals={"free": True, "guests": 74, "registration": "open"},
    )
    base.update(overrides)
    return Opportunity(**base)


def passed() -> Opportunity:
    row = op()
    row.gate = Gate()
    return row
