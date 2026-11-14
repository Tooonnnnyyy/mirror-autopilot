"""The scan gate (spec 4.1): it decides who can attend, not who is interesting."""

from __future__ import annotations

import unittest

from helpers import future, op, past, PROFILE

from radar import gate
from radar.schema import Gate


class CityTests(unittest.TestCase):
    def test_another_city_is_blocked(self):
        row = gate.evaluate(op(city="Toronto"), PROFILE)
        self.assertFalse(row.gate.passed)
        self.assertEqual(row.status, "blocked")
        self.assertEqual(row.status_reason, "gate_failed")

    def test_unknown_city_is_blocked(self):
        row = gate.evaluate(op(city=""), PROFILE)
        self.assertFalse(row.gate.passed)
        self.assertIn("city: 未标明", row.gate.failed)

    def test_online_is_fine(self):
        row = gate.evaluate(op(city="Online"), PROFILE)
        self.assertTrue(row.gate.passed)


class DateTests(unittest.TestCase):
    def test_past_event_is_blocked(self):
        row = gate.evaluate(op(date=past(2)), PROFILE)
        self.assertFalse(row.gate.passed)

    def test_far_future_is_blocked(self):
        row = gate.evaluate(op(date=future(60)), PROFILE)
        self.assertFalse(row.gate.passed)
        self.assertTrue(any("超过 45 天" in reason for reason in row.gate.failed))

    def test_running_window_still_open_passes(self):
        # uOttawa lists "Sep 1 to Dec 18" events: started, but still happening.
        row = gate.evaluate(op(date=past(30), deadline=future(20)), PROFILE)
        self.assertTrue(row.gate.passed)

    def test_absent_date_is_blocked(self):
        row = gate.evaluate(op(date=None), PROFILE)
        self.assertFalse(row.gate.passed)


class EligibilityTests(unittest.TestCase):
    def test_invite_only_is_blocked(self):
        row = gate.evaluate(op(raw_text="This is an invite only dinner for members."), PROFILE)
        self.assertFalse(row.gate.passed)
        self.assertTrue(any("非公开" in reason for reason in row.gate.failed))

    def test_job_language_gate(self):
        row = gate.evaluate(
            op(type="job", title="Analyst", raw_text="French is required for this role."), PROFILE
        )
        self.assertFalse(row.gate.passed)
        self.assertTrue(any("language" in reason for reason in row.gate.failed))

    def test_job_identity_gate_respects_sponsorship(self):
        blocked = gate.evaluate(op(type="job", raw_text="Must be a Canadian citizen."), PROFILE)
        self.assertFalse(blocked.gate.passed)
        allowed = gate.evaluate(
            op(type="job", raw_text="Must be a Canadian citizen, we sponsor work permits."), PROFILE
        )
        self.assertTrue(allowed.gate.passed)

    def test_fresh_row_starts_with_an_empty_gate(self):
        self.assertTrue(Gate().passed)


if __name__ == "__main__":
    unittest.main()
