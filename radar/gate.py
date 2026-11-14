"""扫描门 — the hard gate (spec 4.1). Boolean, before scoring: a row that fails is `blocked`,
keeps the evidence string, and never reaches the Top 10. When the text is ambiguous the row fails:
"宁严勿松" — Tony would rather miss one than wade through noise.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .schema import Gate, Opportunity, parse_time


def _contains(text: str, phrases: list[str]) -> str | None:
    """The first phrase found in the text (case-insensitive whole-phrase match)."""
    lowered = f" {text.lower()} "
    for phrase in phrases:
        needle = phrase.strip().lower()
        if needle and re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", lowered):
            return phrase.strip()
    return None


def evaluate(op: Opportunity, profile: dict, now: datetime | None = None) -> Opportunity:
    """Run the gate for this row's type and record the verdict on the row itself."""
    now = now or datetime.now(timezone.utc)
    gate = Gate()
    if op.type == "job":
        _job(op, profile, gate, now)
    else:
        _event(op, profile, gate, now)
    op.gate = gate
    if not gate.passed:
        op.status = "blocked"
        op.status_reason = "gate_failed"
    return op


def _event(op: Opportunity, profile: dict, gate: Gate, now: datetime) -> None:
    text = f"{op.title} {op.raw_text}"
    config = (profile.get("gate") or {}).get("event") or {}
    allowed = [city.lower() for city in (config.get("allowed_cities") or profile.get("allowed_cities") or [])]
    max_days = int(config.get("max_days_ahead", profile.get("max_days_ahead", 45)))

    city = (op.city or "").strip()
    if not city:
        gate.fail("city: 未标明")
    elif allowed and city.lower() not in allowed:
        gate.fail(f"city: {city}")

    when = parse_time(op.date)
    end = parse_time(op.deadline)
    rolling = end or when  # an event that runs for weeks is judged by its last day
    if not rolling:
        gate.fail("date: 没有日期")
    elif rolling < now:
        gate.fail(f"date: 已过期 ({rolling.astimezone().strftime('%Y-%m-%d')})")
    elif when and when > now + timedelta(days=max_days) and rolling > now + timedelta(days=max_days):
        days = (rolling - now).days
        gate.fail(f"date: {days} 天后（超过 {max_days} 天）")

    invite = _contains(text, config.get("invite_words") or [])
    if invite:
        gate.fail(f"eligibility: 非公开（命中 “{invite}”）")


def _job(op: Opportunity, profile: dict, gate: Gate, now: datetime) -> None:
    text = f"{op.title} {op.raw_text}"
    config = (profile.get("gate") or {}).get("job") or {}
    allowed = [city.lower() for city in (config.get("allowed_cities") or profile.get("allowed_cities") or [])]

    city = (op.city or "").strip()
    if city and allowed and city.lower() not in allowed and "remote" not in text.lower():
        gate.fail(f"city: {city}")

    relocate = _contains(text, config.get("relocate_words") or [])
    if relocate:
        gate.fail(f"relocate: 命中 “{relocate}”")

    identity = _contains(text, config.get("identity_words") or [])
    if identity and not _contains(text, config.get("sponsorship_words") or []):
        gate.fail(f"identity: 要求身份且未提工签支持（命中 “{identity}”）")

    language = _contains(text, config.get("language_words") or [])
    if language:
        gate.fail(f"language: 要求法语（命中 “{language}”）")

    degree = _contains(text, config.get("degree_words") or [])
    if degree:
        gate.fail(f"degree: 命中 “{degree}”")
