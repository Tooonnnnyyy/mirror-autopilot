"""Gate + Jobscan-style score, evidence-only.

Weights (Tony's tracker rules): hard skills 40 > education 20 > title 20 > soft skills 10 > keywords 10.
A skill counts only if the master CV (evidence file) contains it; a JD skill with no CV evidence is a gap.
75+ strong, 65+ viable (apply-pack), below -> discovered only.
"""
from __future__ import annotations

import re

STUDENT = re.compile(r"\b(intern(ship)?s?|co-?op|student|new grad|university grad|summer 202[67])\b", re.I)
CANADA = re.compile(r"canada|toronto|ottawa|montr[eé]al|vancouver|waterloo|calgary|ontario|qu[eé]bec|british columbia|alberta|kanata|remote.{0,20}(canada|north america|americas)", re.I)

# Hard skills vocabulary (JD side). Each maps to regexes; CV evidence is checked with the same patterns.
HARD = {
    "user research": r"user research|ux research|research(er)? (methods|studies)",
    "usability testing": r"usability test",
    "heuristic evaluation": r"heuristic",
    "journey mapping": r"journey map",
    "wireframing": r"wirefram",
    "prototyping": r"prototyp",
    "information architecture": r"information architecture",
    "design systems": r"design system",
    "accessibility": r"accessib|wcag|aoda",
    "a/b testing": r"a/b test|experimentation|split test",
    "figma": r"\bfigma\b",
    "interaction design": r"interaction design",
    "visual design": r"visual design",
    "content design": r"content design|ux writing|content strateg",
    "user interviews": r"user interview|interviewing users|interviews",
    "surveys": r"\bsurvey",
    "personas": r"\bpersonas\b|user persona",
    "python": r"\bpython\b",
    "r": r"(?-i:\bR\b)(?! ?&)",
    "sql": r"\bsql\b",
    "excel": r"\bexcel\b|spreadsheet",
    "tableau/looker": r"tableau|looker|power ?bi",
    "data visualization": r"data visuali[sz]|dashboards?",
    "statistics": r"statistic",
    "machine learning": r"machine learning|\bml\b",
    "ga4/analytics": r"google analytics|\bga4\b|web analytics",
    "html/css": r"\bhtml\b|\bcss\b",
    "javascript/typescript": r"javascript|typescript",
    "react": r"\breact\b",
    "git": r"\bgit\b|github",
    "cms": r"\bcms\b",
    "adobe creative": r"adobe|photoshop|illustrator|after effects|premiere",
    "video editing": r"video edit|video production",
    "shopify/e-commerce": r"shopify|e-?commerce",
    "paid ads": r"google ads|meta ads|paid (social|media|search)",
    "ai tools": r"generative ai|genai|\bllm|ai tools|\bagents?\b|agentic",
    "java/c++/go": r"\bjava\b|c\+\+|\bgolang\b",
    "distributed systems": r"distributed system",
}
SOFT = {
    "communication": r"communicat",
    "collaboration": r"collaborat|cross-functional",
    "stakeholder management": r"stakeholder",
    "storytelling": r"storytell|narrative",
    "problem solving": r"problem[- ]solv",
    "ownership": r"ownership|self-starter|autonom",
    "curiosity": r"curio",
    "detail": r"detail-oriented|attention to detail",
}
LANES = {
    "ux": r"\b(ux|user experience|product design|content design|interaction design|ui/ux|ui)",
    "product": r"\b(product manag|apm|product owner|product ops|program manag|product)",
    "data": r"\b(data analy|business analy|analytics|bi analyst|insights|business systems)",
    "ops": r"\b(operations|bizops|people team|strategy)",
    "content": r"\b(content|marketing|social media|communications|brand)",
}
OFF_LANE = r"algorithms|software engineer|machine learning|data engineer|hardware|industrialization|test automation|scientist|backend|fullstack|forward deployed|research internship"


def clean_cv(cv: str) -> str:
    """Drop HTML comments (open questions) so they never count as evidence."""
    return re.sub(r"<!--.*?-->", " ", cv, flags=re.S)


def evidence_hits(cv: str) -> set[str]:
    cv = clean_cv(cv)
    return {k for k, p in {**HARD, **SOFT}.items() if re.search(p, cv, re.I)}


def gate(role: dict) -> list[str]:
    """Hard gates; returns failures (each with a quote)."""
    t, jd, loc = role["title"], role["jd_text"], role.get("location", "")
    fails = []

    def quote(m):
        s = max(0, m.start() - 60)
        return jd[s:m.end() + 60].replace("\n", " ").strip()

    if not STUDENT.search(t) and not re.search(r"\bintern|co-?op\b", jd[:400], re.I):
        fails.append("not a student role (title)")
    if not CANADA.search(loc):
        fails.append(f"location: {loc[:80]}")
    m = re.search(r"\b(winter|january|jan\.?|february)\s*(term\s*)?2027\b", t + " " + jd, re.I)
    if m and not re.search(r"summer 2027|may 2027", t + " " + jd, re.I):
        fails.append(f"term: Jan/Feb 2027 start -> {m.group(0)}")
    m = re.search(r"\bph\.?d\b", t, re.I)
    if m:
        fails.append("degree: PhD-only title")
    m = re.search(r"(fluen\w+|bilingual|proficien\w+)[^.\n]{0,40}french|french[^.\n]{0,30}(required|mandatory|is a must)", jd, re.I)
    if m and not re.search(r"(asset|nice to have|bonus|plus)", quote(m), re.I):
        fails.append(f"french: {quote(m)}")
    m = re.search(r"(graduat\w+|completing)[^.\n]{0,40}\b(december|dec|spring|may|june)?\s*(2026|2027)\b", jd, re.I)
    if m and not re.search(r"2028|or later|after", quote(m), re.I):
        fails.append(f"grad window: {quote(m)}")
    m = re.search(r"(must|need to|required to)[^.\n]{0,40}(canadian citizen|citizenship|security clearance)", jd, re.I)
    if m:
        fails.append(f"status: {quote(m)}")
    return fails


def score(role: dict, cv: str, cv_hits: set[str]) -> dict:
    t, jd = role["title"], role["jd_text"]
    text = t + "\n" + jd
    jd_hard = [k for k, p in HARD.items() if re.search(p, text, re.I)]
    jd_soft = [k for k, p in SOFT.items() if re.search(p, text, re.I)]
    matched = [k for k in jd_hard if k in cv_hits]
    gaps = [k for k in jd_hard if k not in cv_hits]
    hard = 40 * (len(matched) / max(len(jd_hard), 4))  # <4 recognised skills = low confidence, no free credit
    # education: Tony = MDTI (UX) master's in progress (2028) + BMOS (business).
    edu, edu_note = 20, "enrolled master's student (MDTI, UX) -> meets student requirement"
    if re.search(r"(computer science|software engineering|electrical|mathematics|statistics|physics)[^.\n]{0,40}(degree|major|program)|(degree|major|pursuing)[^.\n]{0,60}(computer science|engineering|mathematics|statistics)", jd, re.I) and not re.search(r"design|hci|human-computer|business|related field|equivalent", jd, re.I):
        edu, edu_note = 8, "JD asks for CS/eng/math degree; Tony's degrees are UX/business"
    elif re.search(r"(computer science|engineering|statistics|mathematics)", jd, re.I) and re.search(r"related field|or similar|equivalent", jd, re.I):
        edu, edu_note = 14, "JD prefers technical field 'or related'; UX/business is adjacent"
    lane = next((k for k, p in LANES.items() if re.search(p, t, re.I)), None)
    if re.search(OFF_LANE, t, re.I):
        title, lane = 4, lane or "off-lane"
    elif lane in ("ux", "data", "product"):
        title = 20
    elif lane:
        title = 14
    else:
        title = 8
    soft_m = [k for k in jd_soft if k in cv_hits or k in ("communication", "collaboration")]  # CV shows cross-team work
    soft = 10 * (len(soft_m) / len(jd_soft)) if jd_soft else 6
    # keywords: share of JD's capitalised tool-like tokens that appear in the CV
    toks = {w for w in re.findall(r"\b[A-Z][A-Za-z0-9+#./-]{2,}\b", jd) if w.lower() not in STOP}
    kw_hit = [w for w in toks if re.search(r"\b" + re.escape(w) + r"\b", clean_cv(cv), re.I)]
    kw = 10 * (len(kw_hit) / len(toks)) if toks else 5
    total = round(hard + edu + title + soft + kw)
    capped = False
    if title <= 4 and total > 60:  # off-lane (SWE/ML/hardware): CV has no production-engineering evidence -> never auto-viable
        total, capped = 60, True
    variant = {"ux": "ux-product-design", "content": "ux-product-design", "data": "data-analytics"}.get(lane or "", "product-ops")
    return {
        "fit_score": total, "lane": lane, "resume_variant": variant,
        "breakdown": {"hard_skills": round(hard, 1), "education": edu, "title": title, "soft_skills": round(soft, 1), "keywords": round(kw, 1)},
        "matched": matched[:8], "gaps": gaps[:8], "keyword_coverage": round(100 * len(kw_hit) / len(toks)) if toks else None,
        "score_notes": [
            f"hard skills {len(matched)}/{len(jd_hard)} evidenced: {', '.join(matched[:8]) or '-'}",
            f"gaps (no CV evidence): {', '.join(gaps[:8]) or '-'}",
            f"education: {edu_note}",
            f"title lane: {lane or 'unknown'} ({title}/20)" + (" — off-lane, capped at 60" if capped else ""),
        ],
        "tier": "strong" if total >= 75 else "viable" if total >= 65 else "low",
    }


STOP = set("""The This That With And For You Your Our We Are Will Who What How Why When Where About Join Team Teams Role Work
Working Experience Requirements Responsibilities Qualifications Benefits Summer Winter Intern Internship Canada Toronto
Ontario Montreal Vancouver United States Remote Hybrid Office Please Equal Opportunity Employer Apply Location Salary
Compensation Base Pay Range Annual Hourly All Some Help Build Lead Own Partner Learn You'll We're It's They Their Its
Here Life Day Week Month Year Years Ability Strong Nice Have Bonus Plus Preferred Minimum Must Should Can May Also Into
From Over Across Within Each Every New Our More Most Such Other Any One Two Three Including Applicants Candidates
Accommodation Accommodations Disability Privacy Policy Notice Information Learn More Check Out Read Know Need Want Like
""".split())
