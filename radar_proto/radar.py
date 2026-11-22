#!/usr/bin/env python3
"""Opportunity Radar (Ottawa) - read-only prototype.

    python3 radar.py --city ottawa --dry-run

Pipeline: fetch (public GET only) -> normalize -> relevance pre-filter (ignore noise)
-> gate (city / date window) -> score -> dedupe -> Top N + shortfall report.

Rules baked in (spec.md section 6 / SUPERVISOR-FEEDBACK.md):
- GET only, no login, no cookies, no secrets. Honest User-Agent.
- >=3 s between requests to the same host, exponential backoff, max 3 attempts.
- A 200 is not success: body is validated (JSON parses, has expected field, no
  "rate limit" text). 403/429/rate-limit body -> source is stopped for this run.
- robots.txt is checked per host; unreachable robots.txt => treated as disallowed.
- --dry-run writes nothing. Without it a digest is written to data/digests/.
- stdlib only.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Toronto")
UA = "opportunity-radar/0.2 (personal read-only prototype; GET only)"
MIN_GAP = 3.0            # seconds between requests to one host (spec 3-8; floor 3)
MAX_ATTEMPTS = 3
MAX_REQUESTS = 120       # spec: total <=120 requests per day
WINDOW_DAYS = 45         # spec gate: farther than 45 days -> blocked
THRESHOLD = 60
ROOT = Path(__file__).resolve().parent


# ----------------------------------------------------------------- fetching
class SourceStopped(Exception):
    """Raised when a source must stop for the day (403/429/rate limit/robots)."""


class Fetcher:
    def __init__(self, verbose: bool = False):
        self.last: dict[str, float] = {}
        self.requests = 0
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.verbose = verbose

    def _wait(self, host: str):
        gap = MIN_GAP + random.uniform(0, 1.5)
        left = self.last.get(host, 0) + gap - time.time()
        if left > 0:
            time.sleep(left)

    def _raw(self, url: str, accept: str = "*/*"):
        host = urllib.parse.urlsplit(url).netloc
        self._wait(host)
        if self.requests >= MAX_REQUESTS:
            raise SourceStopped("daily request budget exhausted")
        self.requests += 1
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, r.read().decode("utf-8", "ignore")
        finally:
            self.last[host] = time.time()

    def allowed(self, url: str) -> bool:
        sp = urllib.parse.urlsplit(url)
        base = f"{sp.scheme}://{sp.netloc}"
        if base not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                status, body = self._raw(base + "/robots.txt")
                rp.parse(body.splitlines())
                self.robots[base] = rp if status == 200 else None
            except urllib.error.HTTPError as e:
                # 404 robots => no restrictions (standard); other errors => disallow
                if e.code == 404:
                    rp.parse([])
                    self.robots[base] = rp
                else:
                    self.robots[base] = None
            except Exception:
                self.robots[base] = None
        rp = self.robots[base]
        return bool(rp and rp.can_fetch(UA, url))

    def get(self, url: str, validate=None, accept: str = "*/*") -> str:
        """GET with robots check, validation, exponential backoff (max 3 tries)."""
        if not self.allowed(url):
            raise SourceStopped(f"robots.txt disallows (or unreadable): {url}")
        last_err = "unknown"
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(3 * 2 ** (attempt - 1))  # 3 s, 6 s
            try:
                status, body = self._raw(url, accept)
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    raise SourceStopped(f"HTTP {e.code} (stop, no retry): {url}")
                last_err = f"HTTP {e.code}"
                if e.code < 500:
                    break
                continue
            except SourceStopped:
                raise
            except Exception as e:
                last_err = type(e).__name__
                continue
            low = body[:4000].lower()
            if "rate limit" in low or "exceeded our rate" in low:
                raise SourceStopped(f"rate-limit body (HTTP {status}, {len(body)} B): {url}")
            if validate:
                try:
                    ok = validate(body)
                except Exception:
                    ok = False
                if not ok:
                    last_err = f"body failed validation (HTTP {status}, {len(body)} B)"
                    continue
            return body
        raise RuntimeError(f"{last_err}: {url}")


# ------------------------------------------------------------------- model
@dataclass
class Opp:
    source: str
    title: str
    url: str
    start: datetime | None          # tz-aware, America/Toronto
    org: str = ""
    city: str = ""                   # "Ottawa" / "Online" / other / ""
    text: str = ""                   # description snippet (<=500)
    free: bool | None = None
    # derived
    relevance: str = ""
    bucket: str = ""
    kw: list[str] = field(default_factory=list)
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    status: str = "new"
    also_on: list[str] = field(default_factory=list)

    @property
    def day(self) -> date | None:
        return self.start.date() if self.start else None


def clean(s: str, n: int = 500) -> str:
    s = re.sub(r"<[^>]+>", " ", unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def to_local(iso: str) -> datetime | None:
    """ISO string -> Toronto tz. Date-only / naive strings are taken as Toronto local."""
    if not iso:
        return None
    try:
        if len(iso) == 10:
            return datetime.fromisoformat(iso).replace(tzinfo=TZ)
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=TZ)
    except ValueError:
        return None


MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_text_date(s: str) -> datetime | None:
    m = re.match(r"\s*([A-Za-z]{3})[a-z]*\s+(\d{1,2}),\s*(\d{4})", s)
    if not m or m.group(1).title() not in MONTHS:
        return None
    return datetime(int(m.group(3)), MONTHS[m.group(1).title()], int(m.group(2)), tzinfo=TZ)


def jsonld_blocks(html: str):
    for b in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            yield json.loads(b)
        except ValueError:
            continue


def ld_event(e: dict, source: str) -> Opp | None:
    if not isinstance(e, dict) or e.get("@type") != "Event":
        return None
    loc = e.get("location") or {}
    addr = loc.get("address") or {} if isinstance(loc, dict) else {}
    city = (addr.get("addressLocality") or "").strip(" ,") if isinstance(addr, dict) else ""
    if isinstance(loc, dict) and "Virtual" in str(loc.get("@type", "")):
        city = "Online"
    if not city and isinstance(loc, dict) and "online" in (loc.get("name") or "").lower():
        city = "Online"
    org = e.get("organizer") or {}
    org = org.get("name", "") if isinstance(org, dict) else ""
    return Opp(source, clean(e.get("name", ""), 200), e.get("url", ""), to_local(e.get("startDate", "")),
               org=clean(org, 100), city=city, text=clean(e.get("description", "")))


# ---------------------------------------------------------------- adapters
def src_luma(f: Fetcher, **_) -> list[Opp]:
    """Luma Ottawa AI & Tech community calendar.

    1) JSON API (unofficial, no contract) with strict body validation; a rate-limit
       message or a body without `entries` is a FAILURE, not an empty calendar.
    2) Fallback: __NEXT_DATA__ embedded in https://luma.com/ottawa (data.upcoming.entries).
    """
    def entries_of(d):
        return d["entries"] if isinstance(d, dict) and isinstance(d.get("entries"), list) else None

    entries = None
    try:
        body = f.get("https://api.lu.ma/calendar/get-items?calendar_api_id=cal-lGggwyc7FbxEg7T"
                     "&period=future&pagination_limit=50",
                     validate=lambda b: entries_of(json.loads(b)) is not None)
        entries = entries_of(json.loads(body))
    except SourceStopped as e:
        print(f"  [luma] API stopped ({e}); falling back to __NEXT_DATA__", file=sys.stderr)
    except RuntimeError as e:
        print(f"  [luma] API failed ({e}); falling back to __NEXT_DATA__", file=sys.stderr)
    if entries is None:
        html = f.get("https://luma.com/ottawa", validate=lambda b: "__NEXT_DATA__" in b)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        data = json.loads(m.group(1))["props"]["pageProps"]["initialData"]["data"]
        entries = entries_of(data.get("upcoming"))
        if entries is None:
            raise RuntimeError("luma __NEXT_DATA__ has no upcoming.entries")
    out = []
    for en in entries:
        ev = en.get("event") or {}
        geo = ev.get("geo_address_info") or {}
        city = "Online" if ev.get("location_type") == "online" else (geo.get("city") or "")
        out.append(Opp("luma", clean(ev.get("name", ""), 200), "https://luma.com/" + ev.get("url", ""),
                       to_local(ev.get("start_at", "")), org=clean((en.get("hosts") or [{}])[0].get("name", ""), 100),
                       city=city))
    return out


def src_eventbrite(f: Fetcher, **_) -> list[Opp]:
    """JSON-LD ItemList on the city page, page 2, and the tech/business category pages."""
    urls = ["https://www.eventbrite.ca/d/canada--ottawa/events/",
            "https://www.eventbrite.ca/d/canada--ottawa/events/?page=2",
            "https://www.eventbrite.ca/d/canada--ottawa/science-and-tech--events/",
            "https://www.eventbrite.ca/d/canada--ottawa/business--events/"]
    out: list[Opp] = []
    for u in urls:
        try:
            html = f.get(u, validate=lambda b: "application/ld+json" in b)
        except RuntimeError as e:
            print(f"  [eventbrite] {e}", file=sys.stderr)
            continue
        for blk in jsonld_blocks(html):
            for it in (blk.get("itemListElement") or []) if isinstance(blk, dict) else []:
                o = ld_event(it.get("item"), "eventbrite")
                if o:
                    out.append(o)
    return out


def src_meetup(f: Fetcher, **_) -> list[Opp]:
    html = f.get("https://www.meetup.com/find/?location=ca--Ottawa&source=EVENTS",
                 validate=lambda b: "application/ld+json" in b)
    out = []
    for blk in jsonld_blocks(html):
        for e in blk if isinstance(blk, list) else []:
            o = ld_event(e, "meetup")
            if o:
                out.append(o)
    return out


def src_carleton(f: Fetcher, **_) -> list[Opp]:
    """Carleton: RSS first (as supervisor asked); it is a valid but EMPTY feed today
    (0 <item>), so fall back to the public WP REST endpoint (acf start date)."""
    try:
        rss = f.get("https://events.carleton.ca/feed/", validate=lambda b: "<rss" in b)
        items = re.findall(r"<item>(.*?)</item>", rss, re.S)
    except RuntimeError:
        items = []
    out: list[Opp] = []
    for it in items:  # used automatically the day the feed starts carrying events
        t = re.search(r"<title>(.*?)</title>", it, re.S)
        l = re.search(r"<link>(.*?)</link>", it, re.S)
        d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
        if t and l:
            try:
                from email.utils import parsedate_to_datetime
                start = parsedate_to_datetime(d.group(1)).astimezone(TZ) if d else None
            except Exception:
                start = None
            out.append(Opp("carleton", clean(t.group(1), 200), l.group(1).strip(), start,
                           org="Carleton University", city="Ottawa"))
    if out:
        return out
    print("  [carleton] RSS /feed/ valid but 0 items -> using WP REST", file=sys.stderr)
    for page in range(1, 16):
        try:
            body = f.get("https://events.carleton.ca/wp-json/wp/v2/cu_event?per_page=100"
                         f"&page={page}&_fields=id,link,title,acf",
                         validate=lambda b: isinstance(json.loads(b), list), accept="application/json")
        except RuntimeError as e:
            if "HTTP 400" in str(e):  # past last page
                break
            raise
        rows = json.loads(body)
        for r in rows:
            acf = r.get("acf") or {}
            start = to_local((acf.get("cu_event_start_date") or "")[:19].replace(" ", "T")) \
                if acf.get("cu_event_start_date") else None
            out.append(Opp("carleton", clean(r["title"]["rendered"], 200), r["link"], start,
                           org="Carleton University", city="Ottawa"))
        if len(rows) < 100:
            break
    return out


def src_uottawa(f: Fetcher, **_) -> list[Opp]:
    out = {}
    for page in range(0, 4):
        body = f.get(f"https://www.uottawa.ca/en/events-all?page={page}&_wrapper_format=drupal_ajax",
                     validate=lambda b: isinstance(json.loads(b), list))
        html = next((c["data"] for c in json.loads(body) if c.get("command") == "insert" and c.get("data")), "")
        for chunk in re.split(r'(?=<article about="/en/events-all/)', html):
            m = re.match(r'<article about="/en/events-all/([a-z0-9\-]+)"', chunk)
            dm = re.search(r'>\s*([A-Z][a-z]{2,8} \d{1,2}, \d{4})', chunk)
            if not (m and dm):
                continue
            tm = re.search(r'<span class="link__content"[^>]*>\s*(.*?)\s*</span>', chunk, re.S)
            out[m.group(1)] = Opp("uottawa", clean(tm.group(1) if tm else m.group(1), 200),
                                  f"https://www.uottawa.ca/en/events-all/{m.group(1)}",
                                  parse_text_date(dm.group(1)), org="University of Ottawa", city="Ottawa")
    return list(out.values())


SOURCES = {"luma": src_luma, "eventbrite": src_eventbrite, "meetup": src_meetup,
           "carleton": src_carleton, "uottawa": src_uottawa}
UNI = {"carleton", "uottawa"}


# --------------------------------------------------------------- relevance
def _rx(words):
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(words) + r")(?![a-z0-9])")


# (bucket, strong keywords). Matched on normalized TITLE (+org) => high.
HIGH = {
    "career": ["careers?", "co-?op", "internships?", "interns?", "hiring", "recruit(?:ing|ment|ers?)",
               "job fair", "resume", "new grads?", "career fair", "employers?", "job search"],
    "tech": ["ai", "a\\.i\\.", "artificial intelligence", "machine learning", "ml", "llms?", "generative",
             "data", "developers?", "programming", "coding", "hackathons?", "tech", "cyber\\w*",
             "cloud", "aws", "devops", "robot\\w*", "quantum", "python", "javascript", "open source",
             "github", "gis", "blockchain", "civic tech", "demos?", "laptop", "projects? night"],
    "builder": ["start-?ups?", "founders?", "co-?founders?", "entrepreneur\\w*", "pitch", "venture",
                "incubator", "accelerator", "networking", "product", "ux", "ui", "design", "growth hack",
                "makers?", "builders?", "demo day", "innovation", "maker ?space"],
}
# Weak words (title) => mid: seen, never counted toward the tech/career/builder quota.
MID = _rx(["software", "science", "engineering", "research", "leadership", "business", "conference", "summit",
           "forum", "workshop", "entrepreneurship", "professional", "analytics", "digital"])
# Noise words (title) => ignored unless the title also has a strong keyword.
LOW = _rx(["concerts?", "ensemble", "choir", "vocal", "jazz", "singles?", "dating", "yoga", "healing",
           "zumba", "christmas", "holiday", "markets?", "cookie", "dinner", "tea", "party", "kink", "dance",
           "silent disco", "film", "storytelling", "poetry", "wreath", "cycling", "bike", "walk",
           "philosophy", "bingo", "music", "band", "comedy", "theatre", "church", "prophets", "sound",
           "pops", "banquet", "noel", "open mic", "vinyl", "singing", "dog", "museum", "estate planning",
           "tax", "wellness", "meditation", "language partners", "fan fiction", "vagus", "burning"])
HIGH_RX = {b: _rx(ws) for b, ws in HIGH.items()}
HANDS_ON = _rx(["workshops?", "hands-on", "demos?", "bring your laptop", "networking", "meetup", "night"])


def norm(t: str) -> str:
    t = unescape(t or "").lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9\-\.]+", " ", t).strip()


def classify(o: Opp):
    title = norm(o.title + " " + o.org)
    hits = {b: sorted({m.group(0) for m in rx.finditer(title)}) for b, rx in HIGH_RX.items()}
    hits = {b: h for b, h in hits.items() if h}
    if hits:
        # order of preference for the bucket label: career > tech > builder
        for b in ("career", "tech", "builder"):
            if b in hits:
                o.bucket = b
                break
        o.kw = [k for h in hits.values() for k in h]
        o.relevance = "mid" if LOW.search(title) and len(o.kw) < 2 else "high"
        if o.relevance == "mid":
            o.bucket = ""
        return
    if LOW.search(title):
        o.relevance, o.status = "low", "ignored"
        o.reasons.append(f"relevance_low (noise keyword: {LOW.search(title).group(0)})")
        return
    mm = MID.search(title)
    if mm:
        o.relevance, o.kw = "mid", [mm.group(0)]
        return
    # no keyword in title: description may justify at most 'mid'
    desc = norm(o.text)
    for b, rx in HIGH_RX.items():
        m = rx.search(desc)
        if m:
            o.relevance, o.kw = "mid", [m.group(0) + " (description)"]
            return
    o.relevance, o.status = "low", "ignored"
    o.reasons.append("relevance_low (no tech/career/builder keyword)")


# ------------------------------------------------------------- gate + score
def gate(o: Opp, today: date) -> str | None:
    if o.start is None:
        return "no date"
    d = o.day
    if d < today:
        return "past"
    if d > today + timedelta(days=WINDOW_DAYS):
        return f">{WINDOW_DAYS}d away"
    if o.city and o.city.lower() not in ("ottawa", "online", "nepean", "kanata", "gloucester", "orleans"):
        return f"city: {o.city}"
    return None


def score(o: Opp, today: date):
    s, r = 0, o.reasons
    s += 45 if o.relevance == "high" else 20
    r.append(f"relevance: {o.relevance} (keyword: {', '.join(o.kw[:3])})")
    r.append(f"type: event" + (f"; bucket: {o.bucket}" if o.bucket else ""))
    extra = min(2, max(0, len(set(o.kw)) - 1)) * 5
    if extra:
        s += extra
        r.append(f"+{extra} multiple topic keywords")
    if o.bucket:
        s += 5
    days = (o.day - today).days
    t = 15 if days <= 7 else 10 if days <= 14 else 5 if days <= 30 else 2
    s += t
    r.append(f"within {7 if days <= 7 else 14 if days <= 14 else 30 if days <= 30 else WINDOW_DAYS}d (+{t})")
    if o.city.lower() == "online":
        s += 5
        r.append("online (+5)")
    else:
        s += 10
        r.append(f"city: {o.city or 'Ottawa (assumed from source)'} (+10)")
    if o.source in UNI:
        s += 5
        r.append("campus / student-oriented (+5)")
    txt = norm(o.title + " " + o.text)
    if re.search(r"(?<![a-z])free(?![a-z])", txt):
        s += 5
        r.append("free (+5)")
    if HANDS_ON.search(norm(o.title)):
        s += 5
        r.append("hands-on / networking format (+5)")
    o.score = min(100, s)


# ------------------------------------------------------------------- dedupe
TRACK = re.compile(r"^(utm_|ref$|aff$|fbclid|gclid)")


def canon_url(u: str) -> str:
    sp = urllib.parse.urlsplit(u)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(sp.query) if not TRACK.match(k)]
    return urllib.parse.urlunsplit((sp.scheme, sp.netloc.lower(), sp.path.rstrip("/"),
                                    urllib.parse.urlencode(q), ""))


def dedupe(items: list[Opp]):
    """Exact url, then same-day near-identical titles (>=0.9). Keep the first (richest) one."""
    pri = {"carleton": 0, "uottawa": 0, "meetup": 1, "luma": 1, "eventbrite": 2}
    items = sorted(items, key=lambda o: (pri.get(o.source, 9), o.start or datetime.max.replace(tzinfo=TZ)))
    kept: list[Opp] = []
    seen_url: dict[str, Opp] = {}
    dups = 0
    for o in items:
        cu = canon_url(o.url)
        if cu in seen_url:
            if o.source != seen_url[cu].source:
                seen_url[cu].also_on.append(o.source)
            dups += 1
            continue
        match = next((k for k in kept if k.day == o.day and difflib.SequenceMatcher(
            None, norm(k.title), norm(o.title)).ratio() >= 0.9), None)
        if match:
            if o.source != match.source:
                match.also_on.append(o.source)
            dups += 1
            continue
        seen_url[cu] = o
        kept.append(o)
    return kept, dups


def oid(o: Opp) -> str:
    return f"{o.source}_{hashlib.sha256((canon_url(o.url) + o.title).encode()).hexdigest()[:12]}"


# --------------------------------------------------------------------- main
def fmt(o: Opp, rank: int) -> str:
    when = o.start.strftime("%a %Y-%m-%d %H:%M") if o.start and o.start.hour else (
        o.start.strftime("%a %Y-%m-%d") if o.start else "?")
    also = f" (also on: {', '.join(sorted(set(o.also_on)))})" if o.also_on else ""
    return (f"{rank:>2}. [{o.score:>3}] {o.title}\n"
            f"    {when} | {o.bucket or o.relevance} | {o.org or '-'} | src={o.source}{also}\n"
            f"    {o.url}\n"
            f"    reasons: " + "; ".join(o.reasons))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--city", default="ottawa")
    ap.add_argument("--dry-run", action="store_true", help="fetch + print, write nothing")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--sources", default=",".join(SOURCES))
    ap.add_argument("--allow-night", action="store_true", help="skip the 00:00-07:00 quiet window")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.city.lower() != "ottawa":
        print("only --city ottawa is supported in v1", file=sys.stderr)
        return 2
    now = datetime.now(TZ)
    if now.hour < 7 and not a.allow_night:
        print("quiet window 00:00-07:00 (spec s6); use --allow-night to override", file=sys.stderr)
        return 2
    today = now.date()
    f = Fetcher(a.verbose)

    raw: list[Opp] = []
    stats: dict[str, dict] = {}
    for name in [s.strip() for s in a.sources.split(",") if s.strip()]:
        print(f"fetching {name} ...", file=sys.stderr)
        try:
            got = SOURCES[name](f)
            stats[name] = {"raw": len(got), "error": None}
            raw += got
        except SourceStopped as e:
            stats[name] = {"raw": 0, "error": f"STOPPED: {e}"}
        except Exception as e:
            stats[name] = {"raw": 0, "error": f"{type(e).__name__}: {e}"}

    # 1) relevance pre-filter  2) gate  3) score
    ignored = blocked = 0
    seen_urls: set[str] = set()
    pre_dups = 0
    ign_list: list[Opp] = []
    cands: list[Opp] = []
    for o in raw:
        if not o.title or not o.url:
            continue
        cu = canon_url(o.url)
        if cu in seen_urls:       # same URL fetched twice (overlapping Eventbrite pages)
            pre_dups += 1
            continue
        seen_urls.add(cu)
        classify(o)
        if o.relevance == "low":
            ignored += 1
            ign_list.append(o)
            stats[o.source]["ignored"] = stats[o.source].get("ignored", 0) + 1
            continue
        why = gate(o, today)
        if why:
            blocked += 1
            stats[o.source]["blocked"] = stats[o.source].get("blocked", 0) + 1
            continue
        score(o, today)
        cands.append(o)
    cands, dups = dedupe(cands)

    keep = [o for o in cands if o.score >= THRESHOLD]
    keep.sort(key=lambda o: (-o.score, o.start))
    top = keep[:a.top]
    tcb = sum(1 for o in top if o.relevance == "high" and o.bucket in ("tech", "career", "builder"))

    print(f"\n=== Opportunity Radar | {a.city.title()} | {today} | "
          f"{'DRY RUN' if a.dry_run else 'LIVE'} | requests={f.requests} ===")
    print(f"{'source':<11}{'raw':>5}{'ignored':>9}{'blocked':>9}  status")
    for n, s in stats.items():
        print(f"{n:<11}{s['raw']:>5}{s.get('ignored', 0):>9}{s.get('blocked', 0):>9}  "
              f"{s['error'] or 'ok'}")
    print(f"raw={len(raw)} (same-URL repeats dropped: {pre_dups}) ignored(relevance)={ignored} blocked(gate)={blocked} "
          f"dedupe_removed={dups} candidates={len(cands)} score>={THRESHOLD}: {len(keep)}")
    print(f"\n--- TOP {len(top)} (window: next {WINDOW_DAYS} days, Ottawa/online) ---\n")
    for i, o in enumerate(top, 1):
        print(fmt(o, i) + "\n")
    print(f"tech/career/builder in Top {len(top)}: {tcb}/{len(top)}  (target >=7)")
    if len(top) < 10:
        print(f"shortfall: {len(top)}/10 (not padded; threshold stays {THRESHOLD})")
    if tcb < 7:
        print(f"shortfall: tech/career/builder {tcb}/7")
    if a.verbose:
        print("\n--- ignored (relevance pre-filter) audit: future only ---")
        shown_c = 0
        for o in ign_list:
            if o.source == "carleton" and o.day and today <= o.day <= today + timedelta(days=WINDOW_DAYS):
                shown_c += 1
                if shown_c > 40:
                    continue
            elif o.source == "carleton":
                continue
            if o.day and o.day >= today:
                print(f"  {o.source:<10}{o.title[:90]}  <{o.reasons[-1][:60]}>")
    more = [o for o in cands if o not in top]
    if a.verbose and more:
        print("\n--- below threshold / not in Top ---")
        for o in sorted(more, key=lambda o: -o.score)[:10]:
            print(f"  [{o.score}] {o.relevance} {o.title} -> {o.url}")

    if not a.dry_run:
        out = ROOT / "data" / "digests"
        out.mkdir(parents=True, exist_ok=True)
        p = out / f"{today}.md"
        p.write_text(f"# Opportunity Radar {today}\n\n" + "\n".join(
            f"{i}. [{o.score}] {o.title} - {o.start:%Y-%m-%d} - {o.url}\n   " + "; ".join(o.reasons)
            for i, o in enumerate(top, 1)) + "\n", encoding="utf-8")
        print(f"\nwrote {p}")
    ok_src = [n for n, s in stats.items() if not s["error"]]
    return 0 if ok_src else 1


if __name__ == "__main__":
    sys.exit(main())
