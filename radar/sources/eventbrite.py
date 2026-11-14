"""Eventbrite (eventbrite.ca).

`sources.md` #3: the Ottawa city page embeds the whole listing as one schema.org ItemList JSON-LD
block (68 items measured 2026-11-14). Zero dependencies, no key, no login. Eventbrite gives no
description, no organizer and no price on that page, so those fields stay empty and the scoring
never pretends otherwise.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from typing import Any

from ..dedupe import make_id
from ..schema import Opportunity, iso_local, now_local, parse_time
from .base import Http

CITY_PAGE = "https://www.eventbrite.ca/d/canada--ottawa/events/"
LD_JSON = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


class Eventbrite:
    id = "eventbrite"

    def fetch(self, http: Http, limit: int) -> list[Opportunity]:
        body = http.get(CITY_PAGE, self.id)
        return parse(body)[:limit]


def _items(node: Any) -> list[dict[str, Any]]:
    """Eventbrite wraps each event as {"@type": "ListItem", "item": {Event}}; accept both shapes."""
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_items(item))
    elif isinstance(node, dict):
        if node.get("@type") in ("ItemList", "ListItem") and "itemListElement" in node:
            found.extend(_items(node["itemListElement"]))
        elif "item" in node and isinstance(node["item"], dict):
            found.extend(_items(node["item"]))
        elif node.get("@type") == "Event":
            found.append(node)
    return found


def parse(body: str) -> list[Opportunity]:
    now = now_local()
    out: list[Opportunity] = []
    for block in LD_JSON.findall(body):
        try:
            node = json.loads(htmllib.unescape(block))
        except json.JSONDecodeError:
            continue
        for event in _items(node):
            title = (event.get("name") or "").strip()
            if not title:
                continue
            starts = parse_time(event.get("startDate"))
            if starts and starts.astimezone(now.tzinfo) < now:
                continue
            place = event.get("location") or {}
            address = place.get("address") or {}
            city = (address.get("addressLocality") or "").strip()
            url = event.get("url") or ""
            online = "OnlineEventAttendanceMode" in (event.get("eventAttendanceMode") or "")
            if online and not city:
                city = "Online"
            out.append(
                Opportunity(
                    id=make_id("eventbrite", url, title),
                    type="event",
                    title=title,
                    org="",
                    url=url,
                    city=city,
                    date=iso_local(event.get("startDate")),
                    deadline=None,
                    source="eventbrite",
                    raw_text="",
                    signals={
                        "free": None,
                        "price": None,
                        "guests": None,
                        "venue": (place.get("name") or "").strip(),
                        "attendance": event.get("eventAttendanceMode") or "",
                    },
                )
            )
    return out
