# RADAR — 机会雷达 (opportunity radar)

Public opportunities in, a gated and scored Top 10 out. The radar reads Ottawa's public event
sources, normalizes everything into one schema, drops what Tony cannot attend, drops what he would
not care about, scores the rest, and prints a short digest. It never signs up, applies, messages or
RSVPs: the last step stays with Tony.

It needs no phone and no OCR; it lives in this repo only because both are Tony's side projects.

## Run it

```bash
python -m radar --city ottawa --dry-run     # read-only: fetch, gate, score, print
python radar.py --city ottawa --dry-run     # same
python -m radar --city ottawa               # also writes data/ (log, digest, state)
python -m radar --city ottawa --json        # machine-readable Top list
python -m unittest discover -s tests        # offline tests, no network
```

A dry run really fetches — it just writes nothing and performs no external action.

Useful flags: `--limit` (rows per source), `--threshold`, `--top`, `--show-more` (extra gate-passed
rows printed for checking, never part of the Top list), `--sources`, `--profile`, `--verbose`.

## What it prints

- A header: rows per source, how many the gate refused, how many are tech/career/builder.
- **Top 10** — score, category, date, title, organizer · source · link, then the three fixed
  reasons and the evidence behind them.
- **其余过门候选** — the next few rows that passed the gate but are not in the Top list, so a reader
  can check the ranking instead of trusting it.
- `shortfall: X/N` when fewer than 7 of the Top rows are tech/career/builder. It says so instead of
  padding the list.
- `⚠ 需主办方审批` on a row whose event page needs the organizer's approval (Luma marks it
  `require_approval`); the check runs on the Top rows only, one small request each.

## The three layers (spec §4)

1. **扫描门 (gate)** — *can Tony attend?* Wrong city, already over, more than 45 days out, no date,
   invite-only, a job demanding citizenship without sponsorship / French / a PhD: `blocked` +
   `status_reason: gate_failed`, with the evidence string. Never in the Top 10. Strict by design.
2. **相关性 (relevance)** — *is it worth his two minutes?* Three tiers from
   `radar/profile.json.relevance_keywords`:
   - `high` — a builder / tech / career word in the title or description → scores fully.
   - `mid` — only a weak word, a strong word that appears only in the organizer's name, or no
     evidence at all (the spec forbids promoting a guess to high) → scores at half, and never takes
     a category coverage slot.
   - `low` — only life / entertainment / consumption / religion / fitness / dating words →
     `ignored` + `status_reason: relevance_low`, never in the Top 10, and **not** added to the
     permanent list, so a better keyword list can surface it later.
3. **分数 (score)** — orders what survived both. Date never adds points; it only breaks ties.

## Scoring

`job` copies `score_jd()` from `src/autopilot.py` exactly (same JD, same number; the golden test
compares them). Every other type uses the spec's dimension table with weights and keywords from
`radar/profile.json`:

| Type | Dimensions |
| --- | --- |
| `event` | topic 0–40 · organizer 0–15 · format 0–10 · campus 0–10 · free 0–10 · RSVP open 0–15 |
| `club` | topic 0–25 · activity 0–20 · recruiting 0–20 · offline Ottawa 0–15 · cheap 0–10 |
| `hackathon` | topic 0–30 · transferable skills 0–20 · ≤48 h 0–15 · team 0–15 · awards 0–10 · deadline 0–10 |
| `collab` | overlap 0–40 · credibility 0–20 · ≤2 weeks 0–15 · clear format 0–15 · budget 0–10 |

The relevance tier then weights the result: `high` keeps it, `mid` halves it, `low` is not scored.
Threshold: 60.

## The schema

`radar/schema.py` — one row per opportunity, exactly the fields in spec §2:

`id` (stable: `{source}_{sha256(canonical url + title)[:12]}`) · `type` · `title` · `org` · `url` ·
`city` · `date` · `deadline` · `source` · `raw_text` (≤500 chars) · `score` · `reasons` · `gate`
(`pass` + `failed`) · `status` · `status_reason` · `mode` · `tags` · `fetched_at`.

`status_reason`: `gate_failed` / `relevance_low` / `manual` / `null`. Only `manual` (a row Tony
ignored by hand) is permanent; the other two are recomputed on every run.

## Sources

| Adapter | What it reads | Measured |
| --- | --- | --- |
| `eventbrite` | `eventbrite.ca/d/canada--ottawa/events/` — one schema.org ItemList in JSON-LD | 30 rows after the per-source cap (68 on the page) |
| `luma` | the community calendar `api.lu.ma/calendar/get-items` | 0 rows (the community calendar has no future events — that is the real answer) |
| `luma_discover` | Luma's own city search `api.luma.com/discover/get-paginated-events?query=ottawa` (non-official endpoint, kept as its own adapter so it can be switched off alone) | 25 rows |
| `invest_ottawa` | `investottawa.ca/events/` — server-rendered month calendar, `data-datetime` on each entry | 25 rows after the cap |
| `kanata_north` | `kanatanorth.ca/events-consultations/` — parsed for dated entries; the page currently publishes none, so it returns 0 rows and never invents any | 0 rows today |
| `clubs_uottawa` | `uottawa.ca/en/events-all?_wrapper_format=drupal_ajax` — Drupal AJAX JSON (sometimes wrapped in `<textarea>`) | 19 rows over 2 pages |
| `clubs_carleton` | `events.carleton.ca` — server-rendered cards with month/day badges | 3 rows (the page carries only the next few) |
| `meetup` | `meetup.com/find/?location=ca--Ottawa&source=EVENTS` — JSON-LD, no headless needed | 12 rows |

Meetup is a bonus source: it is not required for acceptance and a failure there never stops the run.

Every adapter has `fetch()` (network) and a pure `parse()`; the tests run `parse()` on saved pages
in `tests/fixtures/`.

## Being a good citizen (spec §6, in code)

- GET only, no cookie, no login, no key, no captcha — `radar/sources/base.py` has no other verb.
- One request at a time, 3–8 s random pause per host, ≤40 rows per source, ≤120 requests a day,
  nothing between 00:00 and 07:00 Ottawa time (raises and exits 1).
- `robots.txt` is fetched first; a disallowed path skips the source, and a robots.txt that cannot be
  read counts as forbidden.
- 401/403/429/451 stop that source for the day (`source_error` in the audit log); three errors in a
  row or a >30 % error rate stop it too. No retry loops, no workarounds.
- The UA names the project and a contact; the scraped text stays in `data/` on this machine.

## Known limitations

- **A score built mostly from defaults is mostly noise.** When a source publishes no organizer, no
  price and no registration state (Eventbrite's JSON-LD does not), the scorer falls back to
  `organizer_other` / `cost_unknown` / `rsvp_unknown`. A row like "Ottawa Design Club" scores 53 with
  20 points of evidence and 33 points of fallback, so it sits below the 60 line — correct for v1
  (sparse pages rank last) but **not comparable with a 76 that was earned from real fields**. v1
  deliberately does not adjust the weights for this; extraction is the fix, not tuning.
- Luma's city search is an unofficial endpoint; if it is withdrawn only `luma_discover` goes away.
- Kanata North's page has no dated list today; the adapter exists and returns nothing rather than
  guessing.
- Red-line violations exit 1 and produce no digest (`radar/redline.py`).

## State (only without `--dry-run`)

`data/` (override the folder with `RADAR_DATA`):

- `opportunities.jsonl` — every row of every run, one JSON object per line, deduped by id.
- `state.json` — `seen_ids` (90 days), `manual_ids` (permanent), per-day request counters, per-source
  last run.
- `events.jsonl` — the audit trail: what was fetched, what was skipped and why.
- `digests/YYYY-MM-DD.md` — the digest for the day.

`data/` is git-ignored: scraped text stays local.

## Tests

```bash
python -m unittest discover -s tests
```

49 tests, offline: each adapter on its saved page, the gate's rules, the job golden score against
`autopilot.score_jd`, relevance tiers and their caps, ids and near-duplicate merging, Top-10
selection with coverage slots and shortfall, the quiet-hours and credential red lines.
