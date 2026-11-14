"""The two universities' public event calendars (spec section 3, sources.md #4 and #6).

uOttawa: `/en/events-all?_wrapper_format=drupal_ajax` returns Drupal AJAX commands; the `insert`
command carries the server-rendered cards. Each card has the title in `span.link__content`, a
description, and the date range as "Sep 1, 2026 to Dec 18, 2026" — so one request is enough.

Carleton: `events.carleton.ca` renders the upcoming cards server-side: a month and day badge, then
an `<h3><a href="…/event/<slug>/">Title</a></h3>`. The page only carries the next few events, so
this source is small by nature; the 992-entry sitemap is history, not a feed.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from datetime import datetime
from typing import Any

from ..dedupe import make_id
from ..schema import Opportunity, TORONTO, iso_local, now_local
from .base import Http

UOTTAWA_AJAX = "https://www.uottawa.ca/en/events-all?_wrapper_format=drupal_ajax&page={page}"
CARLETON_HOME = "https://events.carleton.ca/"
UOTTAWA_BASE = "https://www.uottawa.ca"

UOTTAWA_ARTICLE = re.compile(r'<article about="(/en/events-all/[a-z0-9-]+)"(.*?)</article>', re.S | re.I)
UOTTAWA_TITLE = re.compile(r'<span class="link__content"[^>]*>(.*?)</span>', re.S)
UOTTAWA_DATE = re.compile(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})")

CARLETON_CARD = re.compile(
    r'<span class="block text-xs[^"]*">\s*([A-Za-z]{3})\s*</span>\s*'
    r'<span class="block text-2xl[^"]*">\s*(\d{1,2})\s*</span>'
    r'[\s\S]{0,1500}?<a href="(https://events\.carleton\.ca/event/[^"]+)">([^<]+)</a>',
    re.I,
)


def _text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", htmllib.unescape(text)).strip()


def _uottawa_dates(text: str) -> tuple[str | None, str | None]:
    """The card states the whole window ("Sep 1, 2026 to Dec 18, 2026"): start and end."""
    matches = UOTTAWA_DATE.findall(text)
    parsed: list[str] = []
    for month, day, year in matches[:2]:
        try:
            starts = datetime.strptime(f"{month} {day} {year}", "%b %d %Y").replace(tzinfo=TORONTO)
        except ValueError:
            continue
        parsed.append(iso_local(starts.isoformat()))
    return (parsed[0] if parsed else None, parsed[1] if len(parsed) > 1 else None)


def parse_uottawa(body: str) -> list[Opportunity]:
    """Pure parser over the Drupal AJAX JSON.

    Without the AJAX header Drupal wraps the same JSON in `<textarea>` (the Drupal AJAX shim reads
    it exactly that way), so both shapes are accepted."""
    body = body.strip()
    if body.startswith("<textarea"):
        start, end = body.find(">"), body.rfind("</textarea>")
        body = body[start + 1:end] if 0 < start < end else body
    try:
        commands = json.loads(body)
    except json.JSONDecodeError:
        return []
    html = "\n".join(command.get("data", "") for command in commands if command.get("command") == "insert")
    now = now_local()
    out: list[Opportunity] = []
    for path, inner in UOTTAWA_ARTICLE.findall(html):
        title_match = UOTTAWA_TITLE.search(inner)
        if not title_match:
            continue
        title = _text(title_match.group(1))
        if not title:
            continue
        card = _text(inner)
        date, end = _uottawa_dates(card)
        last_day = datetime.fromisoformat(end) if end else None
        if last_day and last_day < now:
            continue  # the whole window is behind us
        url = f"{UOTTAWA_BASE}{path}"
        out.append(
            Opportunity(
                id=make_id("clubs_uottawa", url, title),
                type="event",
                title=title,
                org="uOttawa",
                url=url,
                city="Ottawa",
                date=date,
                deadline=end,
                source="clubs_uottawa",
                raw_text=card[:500],
                signals={"free": True, "price": None, "guests": None, "venue": "uOttawa campus", "registration": "open"},
            )
        )
    return out


MONTHS = {month: index for index, month in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_carleton(body: str) -> list[Opportunity]:
    """Pure parser over the Carleton home page. The badge carries no year: take this year, or the
    next one when the month is already behind us."""
    now = now_local()
    out: list[Opportunity] = []
    for month, day, url, title in CARLETON_CARD.findall(body):
        month_number = MONTHS.get(month.lower()[:3])
        if not month_number:
            continue
        year = now.year if month_number >= now.month else now.year + 1
        try:
            starts = datetime(year, month_number, int(day), tzinfo=TORONTO)
        except ValueError:
            continue
        if starts < now:
            continue
        clean = _text(title)
        out.append(
            Opportunity(
                id=make_id("clubs_carleton", url, clean),
                type="event",
                title=clean,
                org="Carleton University",
                url=url,
                city="Ottawa",
                date=iso_local(starts.isoformat()),
                deadline=None,
                source="clubs_carleton",
                raw_text="",
                signals={"free": True, "price": None, "guests": None, "venue": "Carleton University", "registration": "open"},
            )
        )
    return out


class UOttawaClubs:
    id = "clubs_uottawa"

    def __init__(self, pages: int = 2) -> None:
        self.pages = pages

    def fetch(self, http: Http, limit: int) -> list[Opportunity]:
        rows: list[Opportunity] = []
        for page in range(self.pages):
            if len(rows) >= limit:
                break
            body = http.get(UOTTAWA_AJAX.format(page=page), self.id)
            rows.extend(parse_uottawa(body))
        return rows[:limit]


class CarletonClubs:
    id = "clubs_carleton"

    def fetch(self, http: Http, limit: int) -> list[Opportunity]:
        body = http.get(CARLETON_HOME, self.id)
        return parse_carleton(body)[:limit]
