#!/usr/bin/env python3
"""mirror-autopilot: closed-loop autonomous control of iPhone Mirroring.

Loop: detect state -> decide -> act atomically (capture->anchor->click) -> verify -> log -> repeat.
Human enters only via profile.json (background + threshold + caps) and the --contact flag.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
OPS = Path.home() / ".local/share/mirror-autopilot"
WINDOW_ID = "w-27069"          # live mirror view window id
DW, DH = 1440.0, 900.0         # primary display, points
MAX_ITERS = 100
MAX_RETRY = 3

# Feed tab-bar anchors: (label, window-normalized x); y fixed at 0.912.
BOTTOM_NAV = [("职位", 0.236), ("发现", 0.412), ("消息", 0.588), ("我", 0.763)]
LAST_KNOWN = (0.257, 0.849, 0.7058, 0.0809)  # sx, sy, ox, oy — fallback map


def sh(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def log(entry: dict) -> None:
    OPS.mkdir(parents=True, exist_ok=True)
    entry["ts"] = time.time()
    with open(OPS / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def ocr(path: str) -> list[dict]:
    out = sh(["swift", str(TOOLS / "ocr.swift"), str(path)], timeout=180).stdout
    rows = []
    for ln in out.splitlines():
        p = ln.split("\t")
        if len(p) == 5:
            rows.append({"x": float(p[0]), "y": float(p[1]), "w": float(p[2]), "h": float(p[3]), "t": p[4]})
    return rows


def win_shot() -> list[dict]:
    sh(["agent-desktop", "screenshot", "--window-id", WINDOW_ID, "/tmp/ap_win.png"])
    return ocr("/tmp/ap_win.png")


def disp_ocr() -> list[dict]:
    sh(["agent-desktop", "screenshot", "--screen", "0", "/tmp/ap_disp.png"])
    return ocr("/tmp/ap_disp.png")


def frontmost() -> str:
    return sh(["osascript", "-e",
               'tell application "System Events" to get name of first application process whose frontmost is true']).stdout.strip()


def key(expr: str) -> None:  # expr = 'keystroke "[" using command down' etc.
    if frontmost() != "iPhone Mirroring":
        raise RuntimeError("frontmost is not iPhone Mirroring")
    sh(["osascript", "-e", f'tell application "System Events" to {expr}'])


@dataclass
class Map:
    sx: float; sy: float; ox: float; oy: float

    @staticmethod
    def fallback() -> "Map":
        return Map(*LAST_KNOWN)

    def to_disp(self, wx: float, wy: float) -> tuple[float, float]:
        return (self.ox + self.sx * wx) * DW, (self.oy + self.sy * wy) * DH


def relocalize() -> Map | None:
    """Solve display<-window affine from the feed tab bar. None when not on the feed/display."""
    pts = []
    for name, wx in BOTTOM_NAV:
        hits = [r for r in disp_ocr() if r["t"] == name and r["y"] > 0.80]
        if hits:
            pts.append((wx, 0.912, hits[0]["x"], hits[0]["y"]))
    if len(pts) < 2:
        return None
    (x1, y1, X1, Y1), (x2, y2, X2, Y2) = pts[0], pts[-1]
    sx = (X2 - X1) / (x2 - x1) if abs(x2 - x1) > 1e-6 else 1.0
    sy = (Y2 - Y1) / (y2 - y1) if abs(y2 - y1) > 1e-6 else 1.0
    return Map(sx, sy, X1 - sx * x1, Y1 - sy * y1)


def click(wx: float, wy: float, times: int = 2) -> tuple[float, float]:
    m = relocalize() or Map.fallback()
    x, y = m.to_disp(wx, wy)
    for _ in range(times):
        sh(["agent-desktop", "mouse-click", "--headed", f"--xy={x},{y}"])
        time.sleep(0.45)
    return x, y


def detect_state(rows: list[dict]) -> str:
    text = " ".join(r["t"] for r in rows)
    if any(r["t"] in ("职位描述", "职位详情") for r in rows):
        return "detail"
    if "换电话" in text or "由你发起沟通" in text:
        return "chat"
    nav = {r["t"] for r in rows} & {"职位", "发现", "消息"}
    if nav and ("推荐" in text or "最新" in text):
        return "feed"
    if text.count("Search") >= 1 and len(rows) <= 5:
        return "lock_or_spotlight"
    return "unknown"


def go_back() -> bool:
    for _ in range(3):
        if frontmost() == "iPhone Mirroring":
            try:
                key('keystroke "[" using command down')
            except RuntimeError:
                pass
        else:
            m = relocalize() or Map.fallback()
            x1, y = m.to_disp(0.02, 0.50)
            x2, _ = m.to_disp(0.60, 0.50)
            sh(["agent-desktop", "drag", "--headed", f"--from-xy={x1},{y}", f"--to-xy={x2},{y}"])
        time.sleep(1.4)
        if detect_state(win_shot()) == "feed":
            return True
        click(0.05, 0.14)
        time.sleep(1.2)
        if detect_state(win_shot()) == "feed":
            return True
    return False


def scroll() -> None:
    m = relocalize() or Map.fallback()
    x, y1 = m.to_disp(0.50, 0.75)
    _, y2 = m.to_disp(0.50, 0.30)
    sh(["agent-desktop", "drag", "--headed", f"--from-xy={x},{y1}", f"--to-xy={x},{y2}"])
    time.sleep(1.2)


# ---------------------------------------------------------------- policy
def load_profile() -> dict:
    p = OPS / "profile.json"
    if not p.exists():
        raise SystemExit("profile.json missing — copy ops/profile.example.json to "
                         f"{p} and fill in your background.")
    return json.loads(p.read_text(encoding="utf-8"))


def job_titles(rows: list[dict]) -> list[dict]:
    """Card titles: text lines that are not chips/metadata. Heuristic: y in card band, no digits-only."""
    out = []
    for r in rows:
        t = r["t"].strip()
        if 0.25 < r["y"] < 0.90 and len(t) >= 4 and not re.fullmatch(r"[\d.万-]+", t):
            out.append(r)
    return out


def is_target_title(title: str, profile: dict) -> bool:
    return any(k in title for k in profile.get("target_keywords", []))


def score_jd(profile: dict, jd: str) -> dict:
    jdl = jd.lower()
    skills = [s.lower() for s in profile.get("skills", [])]
    hits = [s for s in skills if s in jdl]
    reasons, score = [], 0
    score += min(35, 12 * len(hits))
    reasons.append(f"skills {len(hits)}/{len(skills)}: {', '.join(hits) or '-'}")
    if any(t in jd for t in profile.get("target_roles", [])):
        score += 15
        reasons.append("target role")
    for want in profile.get("must_words", []):
        if want.lower() in jdl:
            score += 10
            reasons.append(f"has '{want}'")
        else:
            score -= 5
            reasons.append(f"missing '{want}'")
    if any(w in jdl for w in profile.get("boost_words", [])):
        score += 5
        reasons.append("boost word")
    score = max(0, min(100, score))
    decision = "contact" if score >= profile.get("threshold", 60) else "skip"
    return {"score": score, "reasons": "; ".join(reasons), "decision": decision}


def daily_contacts() -> int:
    st = OPS / "state.json"
    if not st.exists():
        return 0
    d = json.loads(st.read_text())
    return d.get("contacts", 0) if time.time() - d.get("day", 0) < 86400 else 0


def bump_contacts() -> None:
    st = OPS / "state.json"
    d = json.loads(st.read_text()) if st.exists() else {}
    d.update(day=int(time.time() // 86400), contacts=daily_contacts() + 1)
    st.write_text(json.dumps(d))


# ---------------------------------------------------------------- closed loop
def run(contact_enabled: bool) -> None:
    profile = load_profile()
    cap = int(profile.get("max_daily_contacts", 3))
    contacted, seen_titles = daily_contacts(), set()
    for it in range(MAX_ITERS):
        rows = win_shot()
        state = detect_state(rows)
        log({"state": state, "iter": it})

        if state == "lock_or_spotlight":
            log({"action": "pause", "result": "lock_or_spotlight"})
            print("phone locked or spotlight; pausing loop")
            time.sleep(20)
            continue
        if state in ("detail", "chat"):
            go_back()
            continue
        if state != "feed":
            time.sleep(3)
            continue

        for t in job_titles(rows):
            title = t["t"]
            if title in seen_titles or not is_target_title(title, profile):
                continue
            seen_titles.add(title)
            log({"action": "open", "title": title})
            click(t["x"], t["y"])
            time.sleep(2.0)
            d_rows = win_shot()
            if detect_state(d_rows) != "detail":
                log({"action": "open", "result": "not detail", "title": title})
                go_back()
                continue
            jd = " ".join(r["t"] for r in d_rows)
            verdict = score_jd(profile, jd)
            log({"action": "score", "title": title, **verdict})
            print(f"[{it}] {title} -> {verdict['score']}/100 {verdict['decision']} ({verdict['reasons']})")
            if verdict["decision"] == "contact" and contact_enabled and contacted < cap:
                # find 立即沟通 on the detail page (bottom bar) and double-click
                btn = next((r for r in d_rows if r["t"] == "立即沟通" and r["y"] > 0.80), None)
                if btn:
                    click(btn["x"], btn["y"])
                    time.sleep(2.5)
                    if detect_state(win_shot()) == "chat":
                        contacted += 1
                        bump_contacts()
                        log({"action": "contact", "title": title, "result": "sent"})
                        print(f"    → 已发起沟通 #{contacted}/{cap}")
                    else:
                        log({"action": "contact", "title": title, "result": "unverified"})
            if not go_back():
                log({"action": "back", "result": "failed"})
                break

        if contacted >= cap:
            print("daily contact cap reached; run complete")
            break
        scroll()

    print("loop finished")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--contact", action="store_true", help="allow auto-contact for scores >= threshold")
    args = ap.parse_args()
    run(args.contact)
