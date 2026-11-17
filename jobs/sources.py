"""Public ATS board fetchers (Greenhouse / Lever / Ashby). GET only, no auth, honest UA, polite pacing."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request

UA = "OpportunityRadar/0.2 (personal job search; read-only; contact via github.com/Tooonnnnyyy)"
_last: dict[str, float] = {}


def _get(url: str, host_gap: float = 1.5, tries: int = 3) -> dict | list | None:
    host = url.split("/")[2]
    for attempt in range(tries):
        wait = _last.get(host, 0) + host_gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                body = r.read().decode("utf-8", "replace")
            if "rate limit" in body[:500].lower():
                return None
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 429):
                return None
            time.sleep(2 ** attempt * 2)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(2 ** attempt * 2)
    return None


def strip_html(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "- ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def greenhouse(board: str, company: str):
    d = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    for j in (d or {}).get("jobs", []):
        yield {
            "company": company, "title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""), "posted": j.get("updated_at") or j.get("first_published"),
            "jd_text": strip_html(j.get("content", "")), "ats": "greenhouse", "source": f"greenhouse:{board}",
        }


def lever(board: str, company: str):
    d = _get(f"https://api.lever.co/v0/postings/{board}?mode=json")
    for j in d or []:
        cat = j.get("categories") or {}
        lists = "\n".join(f"{l.get('text','')}\n{strip_html(l.get('content',''))}" for l in j.get("lists", []))
        yield {
            "company": company, "title": j.get("text", ""),
            "location": cat.get("location", "") + (" / " + ", ".join(cat.get("allLocations", [])) if cat.get("allLocations") else ""),
            "url": j.get("hostedUrl", ""), "posted": j.get("createdAt"),
            "jd_text": strip_html(j.get("description", "")) + "\n" + lists + "\n" + strip_html(j.get("additional", "")),
            "ats": "lever", "source": f"lever:{board}",
        }


def ashby(board: str, company: str):
    d = _get(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=false")
    for j in (d or {}).get("jobs", []):
        locs = [j.get("location") or ""] + [x.get("location", "") for x in j.get("secondaryLocations") or []]
        yield {
            "company": company, "title": j.get("title", ""), "location": " / ".join(l for l in locs if l),
            "remote": bool(j.get("isRemote")), "url": j.get("jobUrl", ""), "posted": j.get("publishedAt"),
            "jd_text": j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", "")),
            "ats": "ashby", "source": f"ashby:{board}",
        }


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}
