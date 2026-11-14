"""Meetup (meetup.com).

The city page `/ottawa/` is dead (sources.md section 3), so this reads the only working entry:
`/find/?location=ca--Ottawa&source=EVENTS`. That page server-renders its results as schema.org
JSON-LD (a list of Event objects), so no headless browser is needed and no React payload has to be
parsed. The page covers a wider radius (about 18 miles), so rows outside Ottawa are kept with their
own city and let the gate decide.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from typing import Any
from urllib.parse import urlencode

from ..dedupe import make_id
from ..schema import Opportunity, iso_local, now_local, parse_time
from .base import Http

FIND = "https://www.meetup.com/find/"
LD_JSON = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


class Meetup:
    id = "meetup"

    def fetch(self, http: Http, limit: int) -> list[Opportunity]:
        query = urlencode({"location": "ca--Ottawa", "source": "EVENTS"})
        body = http.get(f"{FIND}?{query}", self.id)
        return parse(body)[:limit]


def _events(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_events(item))
    elif isinstance(node, dict):
        if "@graph" in node:
            found.extend(_events(node["@graph"]))
        elif node.get("@type") == "Event":
            found.append(node)
    return found


def parse(body: str) -> list[Opportunity]:
    """Pure parser over the page's JSON-LD, used by the tests."""
    now = now_local()
    out: list[Opportunity] = []
    for block in LD_JSON.findall(body):
        try:
            node = json.loads(htmllib.unescape(block))
        except json.JSONDecodeError:
            continue
        for event in _events(node):
            row = _row(event, now)
            if row:
                out.append(row)
    return out


def _row(event: dict[str, Any], now: Any) -> Opportunity | None:
    title = (event.get("name") or "").strip()
    if not title:
        return None
    starts = parse_time(event.get("startDate"))
    if starts and starts.astimezone(now.tzinfo) < now:
        return None
    place = event.get("location") or {}
    address = place.get("address") or {}
    city = (address.get("addressLocality") or "").strip()
    organizer = event.get("organizer") or {}
    if isinstance(organizer, str):
        org = organizer
    else:
        org = (organizer.get("name") or "").strip()
    description = re.sub(r"\s+", " ", event.get("description") or "").strip()
    url = event.get("url") or ""
    return Opportunity(
        id=make_id("meetup", url, title),
        type="event",
        title=title,
        org=org,
        url=url,
        city=city,
        date=iso_local(event.get("startDate")),
        deadline=None,
        source="meetup",
        raw_text=description,
        signals={
            "free": None,
            "price": None,
            "guests": None,
            "venue": (place.get("name") or "").strip(),
            "attendance": event.get("eventAttendanceMode") or "",
        },
    )
