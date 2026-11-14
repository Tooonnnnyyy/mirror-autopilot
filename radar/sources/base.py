"""The transport every adapter sits on: GET only, human pace, robots.txt, and the red lines from
spec section 6 enforced in code rather than promised in a README.

Anything that breaks a red line raises RedLineError and fails the whole run (exit 1). A platform
telling us to go away raises SourceBlocked: that source is skipped for the day and the reason is
logged; the other sources keep working.
"""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from ..schema import Opportunity, TORONTO

# Rule 8: honest user agent with a project name and a contact.
USER_AGENT = (
    "opportunity-radar/0.1 (personal research; one request at a time, 3-8s apart; "
    "contact: github.com/Tooonnnnyyy/mirror-autopilot)"
)

BLOCK_STATUSES = {401, 403, 429, 451, 999}
NO_ROBOTS = "robots.txt unavailable — treated as forbidden (spec 6.3)"


class RedLineError(RuntimeError):
    """A red line would be broken. The run stops, exit 1, no digest."""


class SourceBlocked(RuntimeError):
    """This source cannot be read today: robots said no, a block page, or too many errors."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


@dataclass
class Stats:
    """Per-source counters, kept for the audit log and the stop rules."""

    requests: int = 0
    ok: int = 0
    errors: int = 0
    consecutive_errors: int = 0

    @property
    def error_rate(self) -> float:
        return self.errors / self.requests if self.requests else 0.0


class Http:
    """One GET at a time, per-host pacing, robots check, and the daily/nightly limits."""

    def __init__(
        self,
        *,
        min_delay: float = 3.0,
        max_delay: float = 8.0,
        timeout: float = 25.0,
        request_budget: int = 120,
        quiet_hours: tuple[int, int] = (0, 7),
        stop_after_errors: int = 3,
        stop_error_rate: float = 0.3,
        respect_robots: bool = True,
        clock: Any = None,
        sleep: Any = time.sleep,
        random_fn: Any = random.uniform,
    ) -> None:
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.request_budget = request_budget
        self.quiet_hours = quiet_hours
        self.stop_after_errors = stop_after_errors
        self.stop_error_rate = stop_error_rate
        self.respect_robots = respect_robots
        self.clock = clock or (lambda: datetime.now(TORONTO))
        self.sleep = sleep
        self.random_fn = random_fn
        self.stats: dict[str, Stats] = {}
        self.log: list[dict[str, Any]] = []
        self.requests_made = 0
        self._last_request_at: dict[str, float] = {}
        self._robots_cache: dict[str, RobotFileParser | None] = {}

    # -- rules 2 and 6: pace and quiet hours -----------------------------------------------
    def check_time(self) -> None:
        """Rule 2: no fetching between 00:00 and 07:00 Ottawa time."""
        hour = self.clock().hour
        start, end = self.quiet_hours
        if start <= hour < end:
            raise RedLineError(f"quiet hours {start:02d}:00-{end:02d}:00 — no fetching (spec 6.2)")

    def _pace(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is None:
            return
        wait = self.random_fn(self.min_delay, self.max_delay)
        elapsed = time.monotonic() - last
        if elapsed < wait:
            self.sleep(wait - elapsed)

    # -- rule 3: robots.txt ----------------------------------------------------------------
    def _robots_parser(self, url: str) -> RobotFileParser | None:
        origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if origin in self._robots_cache:
            return self._robots_cache[origin]
        try:
            body = self._get_raw(f"{origin}/robots.txt", "robots", origin, host=urlparse(origin).netloc)
            parser = RobotFileParser()
            parser.parse(body.splitlines())
        except (SourceBlocked, urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            # Rule 3: a robots.txt we could not read means forbidden, never "allowed".
            parser = None
        self._robots_cache[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parser = self._robots_parser(url)
        return bool(parser) and parser.can_fetch(USER_AGENT, url)

    # -- one request -----------------------------------------------------------------------
    def get(self, url: str, source: str, *, headers: dict[str, str] | None = None) -> str:
        """GET a URL read-only. Raises RedLineError / SourceBlocked, never retries a block."""
        self.check_time()
        if not self.allowed(url):
            raise SourceBlocked(source, f"robots.txt disallows {url}")
        return self._get_raw(url, source, url, headers=headers)

    def _get_raw(
        self, url: str, source: str, label: str, *, headers: dict[str, str] | None = None, host: str | None = None
    ) -> str:
        if self.requests_made >= self.request_budget:
            raise RedLineError(f"daily request budget spent ({self.request_budget}, spec 6.2)")
        host = host or urlparse(url).netloc
        self._pace(host)
        self.requests_made += 1
        stats = self.stats.setdefault(source, Stats())
        stats.requests += 1

        request = urllib.request.Request(url, method="GET", headers={  # rule 1: GET only
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-CA,en;q=0.9",
            "Cache-Control": "no-cache",
            **(headers or {}),
        })
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", "replace")
                status = response.status
        except urllib.error.HTTPError as err:
            self._note(host, source, label, err.code, time.monotonic() - started)
            stats.errors += 1
            stats.consecutive_errors += 1
            if err.code in BLOCK_STATUSES:
                raise SourceBlocked(source, f"HTTP {err.code} on {label} — stopped for today (spec 6.6)") from err
            if stats.consecutive_errors >= self.stop_after_errors:
                raise SourceBlocked(source, f"{stats.consecutive_errors} errors in a row (spec 6.10)") from err
            raise
        except (urllib.error.URLError, TimeoutError) as err:
            self._note(host, source, label, 0, time.monotonic() - started)
            stats.errors += 1
            stats.consecutive_errors += 1
            if stats.consecutive_errors >= self.stop_after_errors or stats.error_rate > self.stop_error_rate:
                raise SourceBlocked(source, f"errors {stats.errors}/{stats.requests} (spec 6.10)") from err
            raise

        stats.ok += 1
        stats.consecutive_errors = 0
        self._note(host, source, label, status, time.monotonic() - started, len(body))
        return body

    def _note(self, host: str, source: str, label: str, status: int, seconds: float, size: int = 0) -> None:
        self._last_request_at[host] = time.monotonic()
        self.log.append(
            {
                "at": self.clock().isoformat(timespec="seconds"),
                "source": source,
                "url": label,
                "status": status,
                "seconds": round(seconds, 3),
                "bytes": size,
            }
        )


class Adapter(Protocol):
    """Every source implements this: an id and a fetch that returns rows or raises SourceBlocked."""

    id: str

    def fetch(self, http: Http, limit: int) -> list[Opportunity]: ...
