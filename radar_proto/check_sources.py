#!/usr/bin/env python3
"""Re-check every URL listed in sources.md (Ottawa opportunity radar).

Usage:
    python3 projects/opportunity-radar/check_sources.py

Exit code 0 only if every "live" source answers 200 AND its body passes the
source-specific shape check (a 200 with an error body, e.g. Luma's
{"message":"...rate limit..."}, is a FAIL). Other URLs are re-probed and classified
from what they actually return (empty feed / comments feed / challenge page / 404).

No third-party deps: stdlib only. Requests are spaced by >=2 s (spec: 3-8 s
for the crawler; a verify run may be a bit faster, never back-to-back).
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request

UA = "opportunity-radar/0.2 (personal read-only prototype; GET only)"  # honest UA, spec s6 #8
SLEEP_BETWEEN_URLS = 2.0
MAX_ATTEMPTS = 3

# (adapter id, label, url, body_check) -- must answer HTTP 200 and pass body_check
def luma_json_ok(b: str) -> bool:
    """200 is not enough: body must parse, carry a list `entries`, and not be a rate-limit notice."""
    d = json.loads(b)
    return isinstance(d, dict) and isinstance(d.get("entries"), list) and "rate limit" not in b.lower()


def rss_ok(b: str) -> bool:
    return "<rss" in b and "<channel>" in b


LIVE = [
    ("luma", "Luma Ottawa AI+Tech calendar", "https://luma.com/ottawa",
     lambda b: "__NEXT_DATA__" in b),
    ("luma", "Luma public JSON (calendar api_id)",
     "https://api.lu.ma/calendar/get-items?calendar_api_id=cal-lGggwyc7FbxEg7T&period=future&pagination_limit=50",
     luma_json_ok),
    ("meetup", "Meetup events near Ottawa", "https://www.meetup.com/find/?location=ca--Ottawa&source=EVENTS",
     lambda b: "Ottawa" in b),
    ("eventbrite", "Eventbrite Ottawa city page", "https://www.eventbrite.ca/d/canada--ottawa/events/",
     lambda b: "application/ld+json" in b),
    ("clubs_uottawa", "uOttawa all-events calendar", "https://www.uottawa.ca/en/events-all",
     lambda b: "events-all" in b),
    ("clubs_uottawa", "uOttawa events AJAX JSON", "https://www.uottawa.ca/en/events-all?_wrapper_format=drupal_ajax",
     lambda b: "events-all" in b),
    ("clubs_uottawa", "uOttawa club directory (SEO/UOSU)", "https://www.seuo-uosu.com/student-life/clubs",
     lambda b: "Club" in b or "club" in b),
    ("clubs_carleton", "Carleton RSS /feed/ (valid RSS; item count reported below)",
     "https://events.carleton.ca/feed/", rss_ok),
    ("clubs_carleton", "Carleton events calendar", "https://events.carleton.ca/",
     lambda b: "Upcoming Events" in b),
    ("clubs_carleton", "Carleton event sitemap", "https://events.carleton.ca/cu_event-sitemap.xml",
     lambda b: "<loc>" in b),
    ("clubs_carleton", "Carleton WP REST events",
     "https://events.carleton.ca/wp-json/wp/v2/cu_event?per_page=3&_fields=id,acf",
     lambda b: isinstance(json.loads(b), list)),
    ("clubs_carleton", "CUSA club directory", "https://www.cusaclubs.ca/club-directory/",
     lambda b: "club" in b.lower()),
    ("local_tech", "Invest Ottawa events", "https://www.investottawa.ca/events/",
     lambda b: "event" in b.lower()),
    ("local_tech", "Kanata North events", "https://www.kanatanorth.ca/events-consultations/",
     lambda b: "event" in b.lower()),
]

# URLs that are NOT (or not fully) usable as data sources. Each is classified from the REAL
# response (status + body), never from a hard-coded "expected dead" label.
PROBES = [
    ("meetup", "https://www.meetup.com/ottawa/", "page"),
    ("meetup", "https://www.meetup.com/ottawa/rss/", "page"),
    ("eventbrite", "https://www.eventbrite.ca/d/canada--ottawa/events/?format=rss", "page"),
    ("clubs_uottawa", "https://www.uottawa.ca/en/events", "page"),
    ("clubs_carleton", "https://events.carleton.ca/feed/", "feed"),
    ("local_tech", "https://www.investottawa.ca/events/feed/", "feed"),
    ("city", "https://ottawa.ca/en/events", "page"),
]


def classify(code: int, body: str, kind: str) -> str:
    low = body.lower()
    if code != 200:
        return f"HTTP {code}: not available"
    if kind == "feed":
        if "<rss" not in body:
            return "200 but not RSS"
        n = len(re.findall(r"<item[ >]", body))
        title = re.search(r"<title>(.*?)</title>", body, re.S)
        title = title.group(1).strip() if title else ""
        if title.lower().startswith("comments on"):
            return f"200 RSS but it is a COMMENTS feed ({title!r}), items={n}"
        return f"200 valid RSS '{title}', items={n}" + ("  (usable)" if n else "  (empty today -> use REST/HTML fallback)")
    if "noindex" in low and len(body) < 4000:
        return f"200 but JS/bot challenge page ({len(body)} B): do not scrape"
    if "group not found" in low:
        return "200 but 'Group not found' page"
    return f"200, {len(body)} B"


def fetch(url: str):
    """GET with exponential backoff: up to 3 attempts, never a tight loop."""
    last = (0, "", url, b"")
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(2 * (2 ** (attempt - 1)))  # 2 s, 4 s
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.headers.get("content-type", ""), r.geturl(), r.read()
        except urllib.error.HTTPError as e:
            last = (e.code, e.headers.get("content-type", ""), url, b"")
            if e.code < 500:  # 4xx: no point retrying
                return last
        except Exception as e:  # DNS, TLS, timeout -> retry
            last = (0, type(e).__name__, url, b"")
    return last


def main() -> int:
    failures = 0
    print(f"{'ID':<16}{'STATUS':<8}{'BODY':<8}{'CHECK':<8}URL")
    for adapter, label, url, body_ok in LIVE:
        code, ctype, final, body = fetch(url)
        text = body.decode("utf-8", "ignore")
        try:
            ok_body = bool(body_ok(text)) and "rate limit" not in text.lower()
        except Exception:
            ok_body = False
        ok = code == 200 and ok_body
        failures += 0 if ok else 1
        print(f"{adapter:<16}{code:<8}{len(body):<8}{'OK' if ok else 'FAIL':<8}{url}")
        if not ok:
            print(f"{'':<40}body starts: {text[:160]!r}")
        if final != url:
            print(f"{'':<40}-> {final}  [{ctype}]")
        time.sleep(SLEEP_BETWEEN_URLS)

    print("\nprobed URLs, classified from the real response (no 'expected dead' labels):")
    for adapter, url, kind in PROBES:
        code, _, _, body = fetch(url)
        print(f"{adapter:<16}{code:<8}{classify(code, body.decode('utf-8', 'ignore'), kind)}  {url}")
        time.sleep(SLEEP_BETWEEN_URLS)

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
