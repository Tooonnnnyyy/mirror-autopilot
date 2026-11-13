# Postmortem — why the naive approach failed, and the fix for each failure

Operation: drive iPhone Mirroring to browse BOSS直聘, read JDs, contact product intern roles.
Date: 2026-11-13. Every failure below was observed live, not hypothetical.

## Failure table

| # | Symptom | Root cause | Fix (implemented here) |
|---|---|---|---|
| 1 | ~4-8s per step, dozens of round-trips | One-shot bash + per-call `swift` JIT compilation; no persistent process | `autopilot.py`: one long-lived process, state machine, OCR invoked in-process cadence |
| 2 | Clicks landed in the wrong app (DeepSeek Harness, kitty) | Full-display OCR matched words from **my own terminal transcript** ("BOSS直聘", "立即沟通") — contamination | Matching restricted to the phone's geometric band: relocalize the window rect first, then search only inside it |
| 3 | Coordinates went stale between capture and click | Window dragged / Space switched in the seconds between screenshot, OCR, and click | **Atomic act**: capture → OCR → solve affine → click inside one function, milliseconds apart |
| 4 | First click on the mirror did nothing | macOS click-through: first click only focuses an inactive window | Every tap = **double-click** (focus + act) |
| 5 | ⌘1 went to Finder, changed Finder view; ⌘3 went nowhere | Keystrokes sent without verifying frontmost app | Keyboard only after atomic frontmost check (`iPhone Mirroring`); otherwise mouse-only paths |
| 6 | Inputs silently eaten | Phone lock screen (clock + Search only) looks like a live screen | Explicit `lock` state detection → pause + one notification, auto-resume when screen changes |
| 7 | Back navigation stuck, asked human 3 times | Single retry strategy, stale coordinates | `go_back()`: ⌘[ → left-edge swipe → re-anchored chevron click, rotating, up to 3 rounds |
| 8 | "立即沟通" false-positive from terminal text marked a send as done | Verification grepped contaminated text | Verification reads **window-level OCR only** (never the full display) + state transition check (feed→detail→chat) |
| 9 | Human takeover every few minutes | No state machine, no budgets, no self-recovery | Closed loop with retry budgets, action budgets, JSONL audit; human enters only at profile + threshold |

## Metrics that matter

- **Time per action** ≤ 1.5s (capture+OCR+click in-process).
- **Human interventions** = 0 per run (except supplying profile once).
- **Wrong-target clicks** = 0, enforced by geometric-band matching.
- **Sends** = only via policy gate (score ≥ threshold, daily cap, `--contact` flag).

## Lesson

Device automation fails from *environment drift*, not from missing features. The fix is always:
re-observe immediately before acting, act atomically, verify against a state model, and make every
failure a retry path instead of a question.
