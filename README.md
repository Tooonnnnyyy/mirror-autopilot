# Mirror Autopilot

Autonomous, closed-loop control of **iPhone Mirroring on macOS**: continuously reads the mirrored
screen, makes its own decisions, acts with atomic anchor-relocalized clicks, verifies every action,
self-heals navigation failures, and audits everything. A human enters the loop only twice: once to
supply a `profile.json` (your background), and once to confirm the contact threshold.

```
        ┌────────────────────────────────────────────┐
        │              CLOSED LOOP                    │
        │  detect state ──► decide ──► act ──► verify │
        │       ▲                              │      │
        │       └──────────── log ◄────────────┘      │
        └────────────────────────────────────────────┘
```

## Why this exists

See [POSTMORTEM.md](POSTMORTEM.md) — a day of naive scripting failed on: slow one-shot OCR,
terminal-text contamination of screen matching, window drift between capture and click, macOS
first-click-focus semantics, silent lock-screen input, and human-takeover dead ends. This project
is the fixed version: one long-lived process, one state machine, zero human takeover.

## 机会雷达 (opportunity radar) — second component

The repo also holds the **opportunity radar**: it reads public events (Luma, Meetup) for a city,
normalizes them into one schema, scores them against a profile and prints a daily digest. It needs
no phone, no login and no API key, and it never signs up or messages anyone.

```bash
python radar.py --city ottawa --dry-run    # read-only: fetch, score, print
python -m unittest discover -s tests       # offline tests
```

Full guide, schema and scoring rubric: [RADAR.md](RADAR.md).

## Quick start


```bash
git clone https://github.com/Tooonnnnyyy/mirror-autopilot.git && cd mirror-autopilot
cp ops/profile.example.json ~/.local/share/mirror-autopilot/profile.json   # fill in your background
python3 src/autopilot.py          # feed-browse (read-only)
python3 src/autopilot.py --contact  # enable auto-contact for jobs scoring >= threshold
```

Dependencies (already on the dev machine): `agent-desktop`, `swift` (Xcode), macOS Accessibility +
Screen Recording permissions.

## Files

| File | What |
|---|---|
| `src/autopilot.py` | The closed-loop controller |
| `src/ocr.swift` | Local Vision OCR (text + normalized boxes) |
| `ops/profile.example.json` | Your background + decision parameters |
| `DESIGN.md` | State machine, relocalization math, self-healing, policy gate |
| `POSTMORTEM.md` | What failed before and the fix for each failure |
| `~/.local/share/mirror-autopilot/events.jsonl` | Audit log (every action, decision, result) |

## Safety

The **only irreversible action** is tapping 立即沟通 (sends a greeting + your resume). It runs only
when `policy.score >= profile.threshold` AND `--contact` is passed, and is capped by
`profile.max_daily_contacts`. Everything else is read-only navigation, fully logged, fully replayable.
