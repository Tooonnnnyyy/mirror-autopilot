"""Scoring (spec 4.2) and relevance (spec 4.3).

The gate answers "can Tony attend?"; relevance answers "is it worth his two minutes?"; the score
only orders the rows that survived both.

- Relevance: high = full weight, mid = half weight, low = not scored (status ignored with
  `status_reason: relevance_low`). Nothing in the text means mid, never high.
- `job` copies `score_jd()` in src/autopilot.py field for field (tests/test_scoring.py holds the
  golden comparison); every other type uses the dimension table from the spec, with weights and
  keywords read from radar/profile.json.
- Date never adds points: it only breaks ties in the digest (spec 4.3 rule 1).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .schema import Opportunity


def _hits(text: str, words: list[str]) -> list[str]:
    """Whole-word hits, case-insensitive, in the order the profile lists them."""
    lowered = f" {text.lower()} "
    out: list[str] = []
    for word in words:
        needle = (word or "").strip().lower()
        if needle and re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", lowered):
            out.append(word)
    return out


def _clamp(value: int) -> int:
    return max(0, min(100, int(value)))


# ---------------------------------------------------------------- relevance (spec 4.3)
def classify(op: Opportunity, profile: dict) -> tuple[str, str, str]:
    """(level, keyword that decided it, bucket). level is high / mid / low.

    A high word wins outright; a low word with no high word means low; weak words only are mid;
    no evidence at all is mid — the spec forbids promoting a guess to high.
    """
    rules = profile.get("relevance_keywords") or {}
    text = f"{op.title} {op.raw_text}"
    # A strong word in the organizer's name is not evidence about the event itself: "National
    # Social Networking Group" runs mixers, not networking for builders. It can only lift a row to
    # mid, never to high.
    title = op.title
    high = _hits(text, rules.get("high") or [])
    org_high = _hits(op.org or "", rules.get("high") or [])
    mid = _hits(text, rules.get("mid") or [])
    low = _hits(text, rules.get("low") or [])
    # When a word appears in both, the title is the better evidence to quote back to Tony.
    def first(word_list: list[str]) -> str:
        in_title = _hits(title, word_list)
        return in_title[0] if in_title else word_list[0]

    if high:
        return "high", first(high), bucket_of(first(high), profile)
    if low:
        word = first(low)
        return "low", word, bucket_of(word, profile)
    if mid:
        return "mid", first(mid), bucket_of(first(mid), profile)
    if org_high:
        return "mid", f"organizer: {org_high[0]}", bucket_of(org_high[0], profile)
    return "mid", "", bucket_of("", profile)


def bucket_of(keyword: str, profile: dict) -> str:
    """tech / career / builder, from the keyword that decided relevance."""
    buckets = profile.get("buckets") or {}
    for name in ("career", "builder", "tech"):
        if keyword and keyword.lower() in [word.lower() for word in buckets.get(name, [])]:
            return name
    return "tech"


# ---------------------------------------------------------------- job (golden: score_jd)
def score_job(jd: str, job: dict[str, Any]) -> tuple[int, list[str]]:
    """Identical arithmetic to score_jd(): skills 12 each (cap 35), target role 15, must-words
    +10 / missing -5, boost words 5. Same input, same number."""
    jd_lower = jd.lower()
    skills = [skill.lower() for skill in job.get("skills", [])]
    hits = [skill for skill in skills if skill in jd_lower]
    reasons: list[str] = []
    score = 0

    score += min(35, 12 * len(hits))
    reasons.append(f"skills {len(hits)}/{len(skills)}: {', '.join(hits) or '-'}")

    if any(role in jd for role in job.get("target_roles", [])):
        score += 15
        reasons.append("target role")

    for want in job.get("must_words", []):
        if want.lower() in jd_lower:
            score += 10
            reasons.append(f"has '{want}'")
        else:
            score -= 5
            reasons.append(f"missing '{want}'")

    if any(word in jd_lower for word in job.get("boost_words", [])):
        score += 5
        reasons.append("boost word")

    return _clamp(score), reasons


# ---------------------------------------------------------------- typed scoring
def _topic(text: str, rules: dict) -> tuple[int, list[str]]:
    """The type's topic dimension, before the relevance weight is applied."""
    hits = _hits(text, rules.get("topic_words", []))
    if not hits:
        return 0, []
    ladder = list(rules.get("topic_points") or [0, 20, 30, 40])
    points = min(int(rules.get("topic_max", ladder[-1])), int(ladder[min(len(hits), len(ladder) - 1)]))
    return points, [f"topic: {', '.join(hits[:4])}"]


def _score_event(op: Opportunity, profile: dict, now: datetime) -> tuple[int, list[str]]:
    rules = profile["scoring"]["event"]
    text = f"{op.title} {op.raw_text}"
    score, reasons = 0, []

    points, why = _topic(text, rules)
    score += points
    reasons.extend(why)

    org = (op.org or "").lower()
    if any(name in org for name in rules["known_orgs"]):
        score += rules["organizer_max"]
        reasons.append(f"organizer: {op.org}")
    elif op.org:
        score += int(rules.get("organizer_other", 10))
        reasons.append(f"organizer: {op.org}")

    hands_on = _hits(text, rules["format_words"])
    if hands_on:
        score += rules["format_max"]
        reasons.append(f"format: {', '.join(hands_on[:3])}")
    else:
        score += int(rules.get("format_default", 6))
        reasons.append("format: 宣讲/泛泛")

    if _hits(text, rules["campus_words"]):
        score += rules["campus_points"]
        reasons.append("campus: 校内/学生向")

    free = op.signals.get("free")
    if free is True:
        score += rules["free_points"]
        reasons.append("cost: free")
    elif free is None:
        score += int(rules.get("cost_unknown", 7))
        reasons.append("cost: unknown")

    if op.signals.get("registration") == "open":
        score += rules["rsvp_points"]
        reasons.append("rsvp: open")
    else:
        score += int(rules.get("rsvp_unknown", 10))
        reasons.append("rsvp: unknown")

    return _clamp(score), reasons


def _score_club(op: Opportunity, profile: dict, now: datetime) -> tuple[int, list[str]]:
    rules = profile["scoring"]["club"]
    text = f"{op.title} {op.raw_text}"
    score, reasons = 0, []

    points, why = _topic(text, rules)
    score += points
    reasons.extend(why)

    if _hits(text, rules["active_words"]):
        score += rules["activity_max"]
        reasons.append("activity: 定期活动")

    if _hits(text, rules["recruiting_words"]):
        score += rules["recruiting_max"]
        reasons.append("recruiting: 开放招新")

    if (op.city or "").lower() in [city.lower() for city in rules["offline_cities"]]:
        score += rules["offline_max"]
        reasons.append(f"offline: {op.city}")

    if op.signals.get("free") is True:
        score += rules["cheap_points"]
        reasons.append("cost: free")

    return _clamp(score), reasons


def _score_hackathon(op: Opportunity, profile: dict, now: datetime) -> tuple[int, list[str]]:
    rules = profile["scoring"]["hackathon"]
    text = f"{op.title} {op.raw_text}"
    score, reasons = 0, []

    points, why = _topic(text, rules)
    score += points
    reasons.extend(why)

    skills = _hits(text, rules["skill_words"])
    if skills:
        score += min(rules["skills_max"], 10 * len(skills))
        reasons.append(f"skills: {', '.join(skills[:4])}")

    if _hits(text, rules["short_words"]):
        score += rules["short_points"]
        reasons.append("timing: ≤48h")

    if _hits(text, rules["team_words"]):
        score += rules["team_points"]
        reasons.append("team: 可以组队")

    if _hits(text, rules["award_words"]):
        score += rules["award_points"]
        reasons.append("award: 有奖项/曝光")

    deadline = op.deadline
    if deadline:
        score += rules["deadline_points"]
        reasons.append("deadline: 有截止日")

    return _clamp(score), reasons


def _score_collab(op: Opportunity, profile: dict, now: datetime) -> tuple[int, list[str]]:
    rules = profile["scoring"]["collab"]
    text = f"{op.title} {op.raw_text}"
    score, reasons = 0, []

    points, why = _topic(text, rules)
    score += points
    reasons.extend(why)

    if op.org and op.url:
        score += rules["credibility_max"]
        reasons.append(f"credibility: {op.org}")
    elif op.url:
        score += 10
        reasons.append("credibility: 有公开链接")

    if _hits(text, rules["short_words"]):
        score += rules["effort_points"]
        reasons.append("effort: ≤2 周")

    if _hits(text, rules["how_words"]):
        score += rules["how_points"]
        reasons.append("format: 合作方式明确")

    if _hits(text, rules["budget_words"]):
        score += rules["budget_points"]
        reasons.append("budget: 有预算/互惠")

    return _clamp(score), reasons


_SCORERS = {
    "event": _score_event,
    "club": _score_club,
    "hackathon": _score_hackathon,
    "collab": _score_collab,
}


def score(op: Opportunity, profile: dict, now: datetime | None = None) -> Opportunity:
    """Fill score, reasons, tags and status. mode is never promoted here (spec section 2)."""
    now = now or datetime.now(timezone.utc)
    level, keyword, bucket = classify(op, profile)

    if op.type == "job":
        op.score, evidence = score_job(f"{op.title}\n{op.raw_text}", profile.get("job") or {})
    else:
        op.score, evidence = _SCORERS[op.type](op, profile, now)

    # Relevance weights the topic dimension: high keeps it, mid halves it, low is not scored.
    if level == "low":
        op.score = 0
    elif level == "mid":
        op.score = _clamp(op.score * float((profile.get("relevance_caps") or {}).get("mid_score_factor", 0.5)))

    # The three fixed reasons every row carries (spec 4.3 rule 4), then the evidence behind them.
    label = keyword or "no keyword"
    op.reasons = [
        f"relevance: {level} (keyword: {label})",
        f"type: {op.type}",
        f"bucket: {bucket}",
    ]
    op.reasons.extend(evidence)
    op.tags = [word.lower() for word in _hits(f"{op.title} {op.raw_text}", profile["scoring"].get(op.type, {}).get("topic_words", []))][:3]

    if level == "low":
        op.status = "ignored"
        op.status_reason = "relevance_low"
    return op
