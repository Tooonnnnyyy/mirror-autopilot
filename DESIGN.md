# Design — the closed loop

## 1. Perception

- **Window screenshot** (agent-desktop `--window-id`) is the state source: works on any Space, no
  contamination. `src/ocr.swift` (Vision, zh-Hans+en-US) returns `(cx, cy, w, h, text)` in
  normalized top-left coordinates.
- **Display screenshot** is used *only* for relocalization (finding where the window sits on the
  display right now).

## 2. Relocalization (anchor affine)

The feed's bottom tab bar has four stable labels whose *window-normalized* positions are constants:

```
职位 (0.236, 0.912)   发现 (0.412, 0.912)   消息 (0.588, 0.912)   我 (0.763, 0.912)
```

Every action that needs display coordinates first finds ≥2 of these in the display OCR (anywhere,
filtered to `y > 0.8` band to dodge terminal text), then solves:

```
X = ox + sx·wx ,  Y = oy + sy·wy
```

with the widest-spaced pair. If the window moved/resized between actions, the next action
re-solves — coordinates are never trusted across captures.

## 3. Atomic act

`capture → ocr → relocalize → double-click → short settle → verify-by-state` runs inside one
function. Nothing is computed from a capture older than this action.

## 4. State machine

States: `feed` (tab bar + 推荐/最新), `detail` (职位详情), `chat` (换电话/由你发起沟通),
`lock` (clock + Search only), `spotlight` (Search only), `unknown`.

Transitions (all verified after acting):
- feed → (click card title) → detail
- feed → (drag up) → feed (new content hash)
- detail → (click 立即沟通 ×2) → chat
- detail/chat → (go_back) → feed
- any → lock → pause + notify once

`unknown` after an action ⇒ self-heal: re-observe, retry the intended action (budget 3), then log
and continue — never ask a human.

## 5. go_back (rotating strategies)

1. `⌘[` — only after atomic frontmost check == `iPhone Mirroring`.
2. Left-edge right-drag (iOS back gesture), inside the relocalized rect.
3. Re-anchored double-click on the back chevron (0.05, 0.14).

Round-robin, 3 rounds, state-verified each time.

## 6. Policy gate (the only irreversible act)

`立即沟通` sends a greeting + resume to a real recruiter. Gated three ways:

1. **Title filter** — only titles matching the profile's target keywords are ever opened.
2. **JD scoring** — deterministic rubric over the detail text vs `profile.json`:
   skills hit-rate (0-35), target-role match (0-15), experience/edu match (0-20), location/pay
   fit (0-15), competitiveness factors (0-15).
3. **Threshold + cap** — score ≥ `profile.threshold` (default 60) AND daily count <
   `profile.max_daily_contacts` AND `--contact` flag present.

Skip decisions are logged with the score breakdown so a human can audit the reasoning.

## 7. Audit & replay

`~/.local/share/mirror-autopilot/events.jsonl` — one line per action:
`{ts, state, action, target, decision, score?, result, screenshot}`. Runs are replayable and
diffable; the log itself contains no screen text (only decisions and coordinates).

## 8. Budgets (run never hangs)

Per run: max 100 loop iterations, 3 retries per action, 3 back-attempts, daily contact cap.
On budget exhaustion: log a structured summary and exit cleanly.
