# jobs — 岗位雷达 + 投递材料包 (job radar + apply-pack)

**中文一句话**：从公司官方 ATS 公开岗位板（Greenhouse / Lever / Ashby）抓实习/co-op 岗 → 扫描门 → Jobscan 式证据打分 →
对 ≥65 分的岗用「蒸馏自己」skill 通过本机 `claude -p` 生成 cover letter + 常见简答 → 逐条对照 master CV 做证据核查。
**只出草稿，永不提交、永不发消息**；最后一步留给 Tony。

**English**: public ATS boards → student-role filter → hard gates → evidence-only score → for viable roles, a cover
letter + short answers in Tony's voice (distill skill via local `claude -p`) → every claim checked against the master CV.
Drafts only. Nothing is submitted or sent.

## Run / 怎么跑
```bash
jobs/run.sh                                   # scout + apply-packs (top 3 viable) into $TMPDIR/opportunity-radar-<ts>
python3 -m jobs.scout --out OUT               # scout only: OUT/roles.jsonl + OUT/jobs-digest.md (no LLM)
python3 -m jobs.apply_pack --roles OUT/roles.jsonl --out OUT/apply-packs --max 3 [--only lyft] [--model sonnet]
TONY_STYLE_SKILL=~/Downloads/tony-distill-v3/tony-writing-style jobs/run.sh   # swap skill v2 -> v3
```
Inputs: `~/.career-os/resume/master.md` (evidence; HTML comments = open questions, never counted) · skill dir with `SKILL.md`
(default `~/Downloads/tony-distill-v2/tony-writing-style`) · `jobs/watchlist.json` (add companies + ATS slug).
Output is small text. Upload to Google Drive `Cutie/opportunity-radar/` and delete the temp dir (Mac disk is tight).

## Score / 打分 (Tony's tracker rules)
hard skills 40 > education 20 > title 20 > soft skills 10 > keywords 10. Evidence-only: a JD skill counts only if the
master CV shows it; otherwise it is a **gap** and the writer is told never to claim it. 75+ strong · 65+ viable (gets an
apply-pack) · below = discovered. Off-lane titles (SWE / ML / hardware / algorithms) are capped at 60.
Gates (fail = blocked + quote): student role, Canada location, Jan/Feb 2027 start, PhD-only, French required,
graduation window 2026/2027, citizenship/clearance.

## Apply-pack folder / 每个岗位一个文件夹
`README.md` (DRAFT — NOT SUBMITTED, apply URL, score, résumé variant, [TONY: …] to fill) · `cover_letter.md` ·
`short_answers.md` · `evidence_check.md` (claim → CV quote table, up to 3 verify/fix rounds, plus a numbers-not-in-CV
check) · `jd.md`.
Never guessed (always `[TONY: …]`): work authorization/sponsorship, enrolment details, address, GPA/transcripts,
self-ID, salary, start date, references.

## Red lines / 红线
GET-only public APIs, honest UA, ≥1.5 s per host. No login, no forms, no submit, no messages, no LinkedIn automation.
`claude -p` runs with all tools disabled, no MCP, no saved session. No passwords or keys are read or stored.
Codex is not used (metered API key).
