"""Local tech / builder event pages (sources.md #8 and #9).

Invest Ottawa renders its events server-side into a month calendar: every entry is an anchor with
`class="event"`, a `data-datetime` like "Nov 02 @ 1:00 pm - 2:30 pm" and a tooltip with the blurb.
The badge carries no year, so the year is the current one, or the next when that month has already
passed.

Kanata North's page ("Events & Consultations") currently carries no dated list at all — no
`data-datetime`, no calendar widget, zero date strings — so the adapter parses whatever dated
anchors exist and otherwise returns nothing. It is wired in so that the day the page starts
publishing, rows appear without a code change.
"""

from __future__ import annotations

import html as htmllib
import re
from datetime import datetime
from typing import Any

from ..dedupe import make_id
from ..schema import Opportunity, TORONTO, iso_local, now_local
from .base import Http

INVEST_OTTAWA = "https://www.investottawa.ca/events/"
KANATA_NORTH = "https://www.kanatanorth.ca/events-consultations/"

# <a href="…" data-tooltip="…" data-datetime="Nov 02 @ 1:00 pm - 2:30 pm" class="event" …>Title</a>
IO_EVENT = re.compile(
    r'<a[^>]*href="(?P<url>https://www\.investottawa\.ca/[^"]+)"'
    r'[^>]*data-tooltip="(?P<tip>[^"]*)"'
    r'[^>]*data-datetime="(?P<when>[^"]+)"'
    r'[^>]*class="event"[^>]*>(?P<title>[^<]+)</a>',
    re.I,
)

MONTHS = {month: index for index, month in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# The month badge and the day number on the same card, then the title link.
KN_EVENT = re.compile(
    r'<a[^>]*href="(?P<url>https://www\.kanatanorth\.ca/[^"]*(?:event|events)[^"]*)"[^>]*>'
    r'(?P<title>[^<]{3,120})</a>',
    re.I,
)


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _date_from_when(when: str, now: datetime) -> str | None:
    """'Nov 02 @ 1:00 pm - 2:30 pm' → the ISO start, in the next 12 months."""
    match = re.match(r"\s*([A-Za-z]{3})[a-z]*\s+(\d{1,2})\s*(?:@\s*(\d{1,2}):(\d{2})\s*(am|pm))?", when, re.I)
    if not match:
        return None
    month_name, day, hour, minute, meridiem = match.groups()
    month = MONTHS.get(month_name.lower()[:3])
    if not month:
        return None
    hour_value = int(hour) if hour else 9
    if meridiem:
        hour_value = hour_value % 12 + (12 if meridiem.lower() == "pm" else 0)
    year = now.year if month >= now.month else now.year + 1
    try:
        starts = datetime(year, month, int(day), hour_value, int(minute or 0), tzinfo=TORONTO)
    except ValueError:
        return None
    return iso_local(starts.isoformat())


def parse_invest_ottawa(body: str, now: datetime | None = None) -> list[Opportunity]:
    now = now or now_local()
    out: list[Opportunity] = []
    seen: set[str] = set()
    for match in IO_EVENT.finditer(body):
        url = htmllib.unescape(match.group("url"))
        if url in seen:
            continue
        seen.add(url)
        title = _text(match.group("title"))
        date = _date_from_when(match.group("when"), now)
        if not title or not date:
            continue
        if datetime.fromisoformat(date) < now:
            continue
        tip = _text(match.group("tip"))
        out.append(
            Opportunity(
                id=make_id("invest_ottawa", url, title),
                type="event",
                title=title,
                org="Invest Ottawa",
                url=url,
                city="Ottawa",
                date=date,
                deadline=None,
                source="invest_ottawa",
                raw_text=tip,
                signals={"free": None, "price": None, "guests": None, "venue": "Ottawa"},
            )
        )
    return out


def parse_kanata_north(body: str, now: datetime | None = None) -> list[Opportunity]:
    """Only dated anchors count. Today the page has none, so this returns [] — never invented rows."""
    now = now or now_local()
    out: list[Opportunity] = []
    for match in KN_EVENT.finditer(body):
        url = htmllib.unescape(match.group("url"))
        card = _text(body[max(0, match.start() - 400): match.end() + 200])
        date_match = re.search(r"\b([A-Za-z]{3})[a-z]*\s+(\d{1,2})(?:,?\s*(20\d{2}))?", card)
        if not date_match:
            continue
        month = MONTHS.get(date_match.group(1).lower()[:3])
        if not month:
            continue
        year = int(date_match.group(3)) if date_match.group(3) else (now.year if month >= now.month else now.year + 1)
        try:
            starts = datetime(year, month, int(date_match.group(2)), 9, tzinfo=TORONTO)
        except ValueError:
            continue
        if starts < now:
            continue
        title = _text(match.group("title"))
        out.append(
            Opportunity(
                id=make_id("kanata_north", url, title),
                type="event",
                title=title,
                org="Kanata North BIA",
                url=url,
                city="Ottawa",
                date=iso_local(starts.isoformat()),
                deadline=None,
                source="kanata_north",
                raw_text=card,
                signals={"free": None, "price": None, "guests": None, "venue": "Kanata North"},
            )
        )
    return out


class InvestOttawa:
    id = "invest_ottawa"

    def fetch(self, http: Http, limit: int) -> list[Opportunity]:
        body = http.get(INVEST_OTTAWA, self.id)
        return parse_invest_ottawa(body)[:limit]


class KanataNorth:
    id = "kanata_north"

    def fetch(self, http: Http, limit: int) -> list[Opportunity]:
        body = http.get(KANATA_NORTH, self.id)
        return parse_kanata_north(body)[:limit]
