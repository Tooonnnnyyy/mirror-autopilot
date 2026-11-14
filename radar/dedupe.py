"""Stable ids, URL normalization and near-duplicate merging (spec section 2 and 5).

The id is the dedupe anchor: `{source}_{sha256(canonical url + title)[:12]}`. The canonical URL
drops tracking parameters, so the same page seen twice keeps the same id. Cross-source duplicates
(a Meetup event also posted on Eventbrite) are merged by title similarity or by org + day.
"""

from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .schema import Opportunity, day_of

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "source", "mc_cid", "mc_eid", "fbclid", "gclid", "igshid", "srsltid",
    "aff", "aff_id", "partner",
}

SIMILARITY = 0.9  # spec section 5: titles this close are the same thing


def canonical_url(url: str) -> str:
    """Same page, no tracking parameters, lower-case host, no trailing slash, no fragment."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    if not parts.scheme:
        return url.strip().rstrip("/")
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def make_id(source: str, url: str, title: str) -> str:
    seed = f"{canonical_url(url)}|{title.strip().lower()}"
    return f"{source}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}"


def title_key(title: str) -> str:
    return " ".join("".join(ch if ch.isalnum() or ch.isspace() else " " for ch in title.lower()).split())


def similar(left: Opportunity, right: Opportunity) -> bool:
    """Same event on two platforms: a near-identical title, or the same organizer on the same day."""
    if not left.title or not right.title:
        return False
    ratio = SequenceMatcher(None, title_key(left.title), title_key(right.title)).ratio()
    if ratio >= SIMILARITY:
        return True
    same_org = left.org and right.org and left.org.strip().lower() == right.org.strip().lower()
    same_day = day_of(left.date) == day_of(right.date) != "?"
    return bool(same_org and same_day)


def dedupe(rows: list[Opportunity]) -> list[Opportunity]:
    """Keep one row per opportunity: same id first, then the near-duplicate check. The row kept is
    the one with the richer record (a URL, an organizer, a description)."""
    rows = sorted(rows, key=lambda row: (-len(row.raw_text), -int(bool(row.org)), -int(bool(row.url))))
    kept: list[Opportunity] = []
    ids: set[str] = set()
    for row in rows:
        row.validate()
        if row.id in ids:
            continue
        if any(similar(row, other) for other in kept):
            continue
        ids.add(row.id)
        kept.append(row)
    return kept
