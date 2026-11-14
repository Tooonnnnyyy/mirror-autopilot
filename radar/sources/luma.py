"""Luma (luma.com).

Two public, read-only endpoints, both the ones the site itself calls:
1. the Ottawa AI and Tech Community calendar (sources.md #1). On 2026-11-14 it had no future
   events, so it alone cannot feed the radar;
2. the discovery search behind luma.com's own search box, which returns the city's public events
   (`GET api.luma.com/discover/get-paginated-events?query=ottawa`). This is what actually fills
   the radar for Ottawa today.

No account, no cookie, no key.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..schema import Opportunity, iso_local, parse_time, now_local
from ..dedupe import make_id
from .base import Http, SourceBlocked

CALENDAR_API = "https://api.lu.ma/calendar/get-items"
CALENDAR_ID = "cal-lGggwyc7FbxEg7T"  # Ottawa AI and Tech Community (sources.md #1)
DISCOVER_API = "https://api.luma.com/discover/get-paginated-events"
EVENT_URL = "https://luma.com/{slug}"

CALENDAR_HEADERS = {"Origin": "https://luma.com", "Referer": "https://luma.com/ottawa"}
DISCOVER_HEADERS = {"Origin": "https://luma.com", "Referer": "https://luma.com/discover"}


class Luma:
    id = "luma"

    def fetch(self, http: Http, limit: int) -> list[Opportunity]:
        rows: list[Opportunity] = []
        rows.extend(self._calendar(http, limit))
        if len(rows) < limit:
            try:
                rows.extend(self._discover(http, limit - len(rows)))
            except SourceBlocked:
                if not rows:
                    raise
        return rows[:limit]

    def _calendar(self, http: Http, limit: int) -> list[Opportunity]:
        query = urlencode({"calendar_api_id": CALENDAR_ID, "period": "future", "pagination_limit": limit})
        body = http.get(f"{CALENDAR_API}?{query}", self.id, headers=CALENDAR_HEADERS)
        return parse(body, calendar_only=True)

    def _discover(self, http: Http, limit: int) -> list[Opportunity]:
        query = urlencode({"query": "ottawa", "pagination_limit": max(1, min(limit, 50))})
        body = http.get(f"{DISCOVER_API}?{query}", self.id, headers=DISCOVER_HEADERS)
        return parse(body, calendar_only=False)


def parse(body: str, calendar_only: bool = False) -> list[Opportunity]:
    """Pure parser on the API's JSON, so tests never touch the network."""
    import json

    payload = json.loads(body)
    entries = payload.get("entries") or []
    now = now_local()
    out: list[Opportunity] = []
    for entry in entries:
        event = entry.get("event") or {}
        title = (event.get("name") or "").strip()
        if not title:
            continue
        city = ((event.get("geo_address_info") or {}).get("city") or "").strip()
        if not calendar_only and city.lower() != "ottawa":
            continue  # the search also returns other cities that merely mention Ottawa
        starts = parse_time(event.get("start_at"))
        if starts and starts.astimezone(now.tzinfo) < now:
            continue  # already happened
        slug = event.get("url") or ""
        url = EVENT_URL.format(slug=slug) if slug else ""
        calendar = entry.get("calendar") or {}
        ticket = entry.get("ticket_info") or {}
        venue = (event.get("geo_address_info") or {}).get("short_address") or ""
        out.append(
            Opportunity(
                id=make_id("luma", url, title),
                type="event",
                title=title,
                org=(calendar.get("name") or "").strip(),
                url=url,
                city=city or "Ottawa",
                date=iso_local(event.get("start_at")),
                deadline=None,
                source="luma",
                raw_text=f"{venue}".strip(),
                signals={
                    "free": ticket.get("is_free"),
                    "price": ticket.get("price"),
                    "guests": entry.get("guest_count"),
                    "venue": venue,
                    "registration": entry.get("registration_availability"),
                },
            )
        )
    return out


def _unused(_: Any) -> None:  # keep the import list honest for type checkers
    return None
