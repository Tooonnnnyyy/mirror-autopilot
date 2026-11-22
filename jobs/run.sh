#!/usr/bin/env bash
# One-shot: scout public ATS boards -> score -> apply-packs for viable roles. Drafts only, nothing submitted.
#   jobs/run.sh [OUT_DIR] [extra apply_pack args, e.g. --max 3 --only lyft]
# Skill swap: TONY_STYLE_SKILL=~/Downloads/tony-distill-v3/tony-writing-style jobs/run.sh
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-${TMPDIR:-/tmp}/opportunity-radar-$(date +%Y%m%d-%H%M)}"; shift || true
mkdir -p "$OUT"
python3 -m jobs.scout --out "$OUT"
python3 -m jobs.apply_pack --roles "$OUT/roles.jsonl" --out "$OUT/apply-packs" "$@"
echo "OUTPUT: $OUT  (small text files; upload to Drive 'Cutie/opportunity-radar' then delete)"
