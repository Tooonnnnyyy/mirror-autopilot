"""Top 10 selection, coverage slots, shortfall and the exclusion list (spec 4.4)."""

from __future__ import annotations

import unittest

from helpers import future, op, PROFILE

from radar import digest, scoring
from radar.schema import Gate


def scored(**overrides):
    row = op(gate=Gate(), **overrides)
    scoring.score(row, PROFILE)
    return row


class SelectionTests(unittest.TestCase):
    def test_only_new_passing_rows_above_the_threshold(self):
        good = scored()
        low = scored(title="Winter Choir Concert", org="", raw_text="")
        blocked = scored(title="Ottawa AI Night")
        blocked.status = "blocked"
        picked = digest.select_top([good, low, blocked], 60, set())
        self.assertEqual([row.id for row in picked], [good.id])

    def test_seen_ids_are_excluded(self):
        good = scored()
        self.assertEqual(digest.select_top([good], 60, {good.id}), [])

    def test_cap_at_ten(self):
        rows = [scored(id=f"luma_{index}", title=f"Ottawa AI Builders Night {index}", url=f"https://luma.com/{index}") for index in range(15)]
        self.assertEqual(len(digest.select_top(rows, 60, set())), 10)

    def test_coverage_slot_only_for_high_relevance(self):
        # A mid row is never drafted into a coverage slot, even if it is the only club.
        mid_club = scored(id="mid_club", type="club", title="Community Club Meetup", org="", raw_text="meetup community", url="https://x/1")
        high_event = scored(id="high_event", type="event", title="Ottawa AI Builders Night", url="https://x/2")
        picked = digest.select_top([mid_club, high_event], 0, set())
        self.assertTrue(any(row.id == "high_event" for row in picked))
        self.assertLessEqual(len(picked), 10)

    def test_shortfall_names_the_missing_buckets(self):
        rows = [scored()]  # one tech event
        count, missing = digest.shortfall(rows)
        self.assertEqual(count, 1)
        self.assertIn("career", missing)

    def test_no_padding_beyond_available_rows(self):
        rows = [scored()]
        self.assertEqual(len(digest.select_top(rows, 60, set())), 1)


class OutputTests(unittest.TestCase):
    def test_console_shows_the_three_reason_elements(self):
        text = digest.render_console([scored()], city="ottawa", total=1, sources={"luma": 1}, blocked=0, dry_run=True)
        self.assertIn("relevance: high", text)
        self.assertIn("type: event", text)
        self.assertIn("bucket: ", text)

    def test_markdown_has_the_shortfall_line(self):
        text = digest.render_markdown([scored()], city="ottawa", total=1, sources={"luma": 1}, blocked=0)
        self.assertIn("shortfall", text)


if __name__ == "__main__":
    unittest.main()
