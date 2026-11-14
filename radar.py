#!/usr/bin/env python3
"""机会雷达 — the same CLI as `python -m radar`, for a plain `python radar.py`.

Usage: python radar.py --city ottawa --dry-run
"""

from radar.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
