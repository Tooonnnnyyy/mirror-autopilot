"""The red lines from spec section 6 that can be checked in code, checked on every run.

A violation stops the run with exit 1 and produces no digest — the point is that a rule nobody can
break silently is worth more than a rule in a README.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .schema import TORONTO

SECRET_KEYS = re.compile(r"(password|passwd|api[_-]?key|secret|token|cookie|session)", re.I)
SECRET_VALUES = re.compile(r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{20,})")


class RedLineError(RuntimeError):
    """A red line would be crossed. The run stops, exit 1, no digest."""


def check_night(quiet_hours: tuple[int, int] = (0, 7), now: datetime | None = None) -> None:
    """Rule 2: no fetching between 00:00 and 07:00 Ottawa time."""
    now = now or datetime.now(TORONTO)
    start, end = quiet_hours
    if start <= now.hour < end:
        raise RedLineError(
            f"现在 {now.strftime('%H:%M')} 在安静时段 {start:02d}:00–{end:02d}:00 内，不抓取（spec 6.2）"
        )


def check_no_secrets(profile_path: Path, profile: dict[str, Any]) -> None:
    """Rule 5: no credentials on disk. A profile that carries one is a mistake to fix, not to run."""
    text = profile_path.read_text(encoding="utf-8") if profile_path.exists() else json.dumps(profile, ensure_ascii=False)
    for match in SECRET_VALUES.finditer(text):
        raise RedLineError(f"profile 里有像密钥的值（spec 6.5）: …{match.group(0)[-6:]}")
    for key, value in _walk(profile):
        if SECRET_KEYS.search(key) and isinstance(value, str) and len(value) >= 8:
            raise RedLineError(f"profile 里有凭证字段 {key!r}（spec 6.5）；密钥只从环境变量读，不落盘")


def _walk(node: Any, prefix: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                yield from _walk(value, f"{prefix}{key}.")
            else:
                yield f"{prefix}{key}", value
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (dict, list)):
                yield from _walk(value, f"{prefix}{index}.")


def check_profile_shape(profile: dict[str, Any]) -> None:
    """A profile that cannot drive the run should say so before any request is made."""
    for key in ("threshold", "allowed_cities", "scoring"):
        if key not in profile:
            raise RedLineError(f"profile 缺少 {key!r}：权重和门槛必须是数据（spec 4.2）")
