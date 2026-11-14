# CONTEXT — current state & pending decisions

> Read this first when resuming. Written 2026-11-13, after the first live run against BOSS直聘.

## Where we are

- Repo: `mirror-autopilot` — closed-loop autonomous iPhone Mirroring control.
- The controller, OCR tool, postmortem and design are committed and pushed.
- **Live-tested on 2026-11-13**: one real contact was sent on BOSS直聘 —
  深势科技 · "AI agent 产品实习生"（北京海淀，300-350元/天）· 王佳淼·招聘者. That send was
  user-approved ("产品相关直接点沟通，我批准").

## What the loop does (decision rules, fixed)

1. Scroll the 职位 feed continuously (read-only).
2. Open a job **only** when its title contains a target keyword (`target_keywords` in profile).
3. Read the JD, score it 0-100 against the profile: skills hit-rate (≤35) + target-role (≤15)
   + must/boost words (±) + context fit.
4. `score ≥ threshold` (default 60) AND daily count < `max_daily_contacts` (default 3)
   AND `--contact` flag → tap 立即沟通 (the ONLY irreversible action).
5. Skip = logged with the score breakdown, loop continues.

## Pending (needs the user — the only human input)

1. **Background info** → fill `~/.local/share/mirror-autopilot/profile.json`
   (template: `ops/profile.example.json`). User will provide: education, skills, experience,
   target roles, city/salary expectations.
2. **Confirm parameters** (defaults, user may override):
   | Param | Default | Meaning |
   |---|---|---|
   | threshold | 60/100 | minimum score to auto-contact |
   | max_daily_contacts | 3 | daily cap (BOSS greeting quota) |
3. When provided: run `python3 src/autopilot.py` (read-only verify) then
   `python3 src/autopilot.py --contact`.

## Hard safety rules (never break)

- The 立即沟通 click is the only irreversible act; it stays behind the policy gate.
- Matching uses window-level OCR inside the phone's geometric band only — never full-display grep
  (terminal text contaminated matches and caused wrong-target clicks on 2026-11-13).
- Every click is atomic: capture → relocalize (tab-bar anchors) → double-click → verify by state.
- Never ask a human to take over a stuck navigation; extend `go_back()` retry rotation instead.
- `events.jsonl` is the audit trail; log every action, decision and result.

## How to verify the loop is healthy (cheap, read-only)

```bash
cd ~/mirror-autopilot && python3 src/autopilot.py   # browse+score, no sends
tail -f ~/.local/share/mirror-autopilot/events.jsonl
```

Expected first lines: state=feed, then scroll/open/score entries. If state=lock_or_spotlight:
phone is locked — unlock once, loop auto-resumes.

## Environment facts (this machine)

- iPhone 17 Pro "tony bi 17p" — **PUA USB path exists** (configured 2026-11-08, service currently
  down) but the mirror path (this repo) does not need USB.
- Mirror live-view window id `w-27069` (change in `src/autopilot.py` if it changes).
- macOS 27.2, single display 1440×900, agent-desktop v2.6, swift/Xcode present.
- Screen Recording + Accessibility granted to kitty (and screenpipe runs with 7-day media
  retention — see ~/.local/share/iphone-use/ops for the earlier manual ops log).

## Opportunity radar (second component, added 2026-11-14)

The repo now holds two independent things: the iPhone mirror loop (`src/autopilot.py`, above) and
**机会雷达** (`radar/`, entry `python -m radar` or `python radar.py`), which reads public Ottawa
opportunities, gates them, drops what is not relevant, scores the rest and prints a Top 10.

- Run: `python -m radar --city ottawa --dry-run` (read-only). Full guide: `RADAR.md`.
- Sources: Eventbrite, Luma, uOttawa, Carleton (required) + Meetup (bonus, plain HTTP on its
  JSON-LD, no headless).
- Layers: gate (can Tony attend?) → relevance high/mid/low (worth his time?) → score (ordering).
  Low relevance never reaches the Top 10 and is never added to the permanent seen list.
- State (only without `--dry-run`): `data/` — git-ignored, stays local.
- Tests: `python -m unittest discover -s tests` (49, offline, no network).
- Status: adapters, gate, relevance, scoring, digest and the red lines are done and verified
  against live Ottawa data; pending: Tony's read of the first real digest, and the CTO's follow-ups.
