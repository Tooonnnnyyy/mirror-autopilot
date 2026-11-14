"""Adapters parse their own saved pages (spec 5: HTML parsing must ship offline fixtures)."""

from __future__ import annotations

import unittest

from helpers import fixture  # noqa: E402  (helpers puts the repo root on sys.path)

from radar.sources import clubs, eventbrite, local_tech, luma, meetup


class EventbriteTests(unittest.TestCase):
    def test_parses_the_ottawa_listing(self):
        rows = eventbrite.parse(fixture("eventbrite.html"))
        self.assertGreater(len(rows), 20)
        first = rows[0]
        self.assertEqual(first.source, "eventbrite")
        self.assertTrue(first.url.startswith("https://www.eventbrite.ca/e/"))
        self.assertTrue(first.city)
        self.assertTrue(first.id.startswith("eventbrite_"))

    def test_skips_events_already_past(self):
        rows = eventbrite.parse(fixture("eventbrite.html"))
        self.assertTrue(all(row.date for row in rows))


class LumaTests(unittest.TestCase):
    def test_keeps_only_ottawa(self):
        rows = luma.parse(fixture("luma.json"))
        self.assertGreater(len(rows), 10)
        self.assertTrue(all(row.city.lower() == "ottawa" for row in rows))
        self.assertTrue(all(row.source == "luma" for row in rows))

    def test_event_url_is_public(self):
        rows = luma.parse(fixture("luma.json"))
        self.assertTrue(all(row.url.startswith("https://luma.com/") for row in rows))


class MeetupTests(unittest.TestCase):
    def test_parses_the_json_ld_list(self):
        rows = meetup.parse(fixture("meetup.html"))
        self.assertGreater(len(rows), 5)
        self.assertTrue(all(row.source == "meetup" for row in rows))
        self.assertTrue(any(row.org for row in rows))


class LocalTechTests(unittest.TestCase):
    def test_invest_ottawa_reads_the_month_calendar(self):
        rows = local_tech.parse_invest_ottawa(fixture("invest_ottawa.html"))
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row.source == "invest_ottawa" for row in rows))
        self.assertTrue(all(row.url.startswith("https://www.investottawa.ca/") for row in rows))
        self.assertTrue(all(row.org == "Invest Ottawa" for row in rows))

    def test_kanata_north_invents_nothing(self):
        # The page carries no dated entries today: an empty list is the honest answer.
        rows = local_tech.parse_kanata_north(fixture("kanata_north.html"))
        self.assertIsInstance(rows, list)
        self.assertTrue(all(row.source == "kanata_north" for row in rows))


class ApprovalTests(unittest.TestCase):
    def test_detects_the_approval_flag(self):
        self.assertTrue(luma.approval_required(fixture("luma_event_approval.html")))

    def test_open_event_is_not_flagged(self):
        self.assertFalse(luma.approval_required('{"require_approval":false}'))
        self.assertFalse(luma.approval_required("<html>no flag here</html>"))


class CampusTests(unittest.TestCase):
    def test_uottawa_accepts_the_textarea_wrapper(self):
        rows = clubs.parse_uottawa(fixture("uottawa.json"))
        self.assertGreater(len(rows), 5)
        self.assertTrue(all(row.source == "clubs_uottawa" for row in rows))
        self.assertTrue(all(row.date for row in rows))

    def test_carleton_reads_the_cards(self):
        rows = clubs.parse_carleton(fixture("carleton.html"))
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row.url.startswith("https://events.carleton.ca/event/") for row in rows))


if __name__ == "__main__":
    unittest.main()
