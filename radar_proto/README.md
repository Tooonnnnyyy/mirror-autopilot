# radar_proto — P0-fixed events radar (stdlib, single file)

Copied from the DSH workspace (`projects/opportunity-radar/`) on 2026-11-17 so the code lives in git.
This is the version that passed the supervisor P0 acceptance (see `SUPERVISOR-FEEDBACK.md` in the workspace):
≥10 real Ottawa events, scored with reasons, URLs 200, deduped, 10/10 tech/career/builder in the Top 10.

    python3 radar_proto/radar.py --city ottawa --dry-run     # do NOT add --allow-night for daily use (00:00–07:00 quiet window)
    python3 radar_proto/check_sources.py

The `radar/` package in this repo is the earlier v1 (five adapters). Consolidating the two is a pending decision for Tony.
