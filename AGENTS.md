# AGENTS.md — mirror-autopilot

Closed-loop autonomous iPhone Mirroring control. Read CONTEXT.md (current state + pending) then DESIGN.md before touching code.

Hard rules:
- The ONLY irreversible action is the 立即沟通 click: it must stay behind the policy gate
  (score >= threshold, daily cap, --contact flag). Never bypass.
- Matching uses window-level OCR + geometric band only; never grep full-display text (terminal
  contamination caused wrong-target clicks — see POSTMORTEM.md).
- Every click is atomic (capture → relocalize → double-click) and state-verified.
- Never ask a human to take over; extend go_back()/retry budgets instead.
- events.jsonl is the audit trail; log every action with result.

Verify: `python3 src/autopilot.py` (read-only browse), `--contact` enables sends.
