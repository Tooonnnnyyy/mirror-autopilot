"""Job scout CLI: public ATS boards -> student-role filter -> gate -> score -> dedupe -> roles.jsonl + digest.md

    python -m jobs.scout --cv ~/.career-os/resume/master.md --out /tmp/radar-out [--limit-companies N]

Read-only (public GETs). Writes only to --out.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from .score import STUDENT, evidence_hits, gate, score
from .sources import FETCHERS

HERE = Path(__file__).parent


def rid(company: str, title: str, url: str) -> str:
    u = re.sub(r"[?&](utm_[^=]+|ref|source)=[^&]*", "", url)
    return "job_" + hashlib.sha256(f"{company.lower()}|{title.lower().strip()}|{u}".encode()).hexdigest()[:12]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cv", default=os.path.expanduser("~/.career-os/resume/master.md"))
    ap.add_argument("--watchlist", default=str(HERE / "watchlist.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--raw", help="reuse a raw.json instead of fetching (offline/testing)")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args(argv)
    cv = Path(a.cv).read_text()
    hits = evidence_hits(cv)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    if a.raw:
        raw = json.load(open(a.raw))
    else:
        raw = []
        for c in json.load(open(a.watchlist))["companies"]:
            got = list(FETCHERS[c["ats"]](c["board"], c["company"]))
            print(f"  {c['company']:<22} {len(got):>4} postings", file=sys.stderr)
            raw += got
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    # dedupe: same company + normalised title = one role (multi-location reposts). Prefer a gate-passing copy.
    groups: dict = {}
    for r in raw:
        if not STUDENT.search(r["title"]):
            continue
        key = (r["company"].split(" (")[0].lower(), re.sub(r"\W+", " ", r["title"].lower()).strip())
        groups.setdefault(key, []).append((r, gate(r)))
    roles = []
    for copies in groups.values():
        r, fails = next(((c, f) for c, f in copies if not f), copies[0])
        role = {
            "id": rid(r["company"], r["title"], r["url"]), "type": "job", "company": r["company"], "title": r["title"],
            "location": r.get("location", ""), "url": r["url"], "ats": r["ats"], "source": r["source"],
            "posted": r.get("posted"), "fetched_at": now, "jd_text": r["jd_text"][:12000], "duplicates": len(copies) - 1,
            "gate": {"pass": not fails, "failed": fails}, "status": "blocked" if fails else "new", "mode": "manual",
        }
        if not fails:
            role.update(score(r, cv, hits))
        roles.append(role)
    passed = sorted([r for r in roles if r["gate"]["pass"]], key=lambda r: -r["fit_score"])
    with open(out / "roles.jsonl", "w") as f:
        for r in passed + [r for r in roles if not r["gate"]["pass"]]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lines = [f"# Job radar — {now}", "",
             f"Postings fetched: {len(raw)} · student roles (deduped): {len(roles)} · passed gate: {len(passed)} · "
             f"viable (>=65): {sum(r['fit_score'] >= 65 for r in passed)} · strong (>=75): {sum(r['fit_score'] >= 75 for r in passed)}", "",
             "Scoring: hard skills 40 · education 20 · title 20 · soft skills 10 · keywords 10 — evidence-only vs master CV.", ""]
    for i, r in enumerate(passed[: a.top], 1):
        b = r["breakdown"]
        lines += [f"{i}. **[{r['fit_score']}] {r['company']} — {r['title']}** ({r['tier']}, lane {r['lane']}, résumé `{r['resume_variant']}`)",
                  f"   {r['location']} · {r['url']}",
                  f"   breakdown: hard {b['hard_skills']} · edu {b['education']} · title {b['title']} · soft {b['soft_skills']} · kw {b['keywords']}"]
        lines += [f"   - {n}" for n in r["score_notes"]]
    lines += ["", "## Blocked by gate (evidence)", ""]
    lines += [f"- {r['company']} — {r['title']}: {'; '.join(r['gate']['failed'])[:220]}" for r in roles if not r["gate"]["pass"]][:60]
    (out / "jobs-digest.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[: 8 + 6 * min(a.top, 10)]))


if __name__ == "__main__":
    main()
