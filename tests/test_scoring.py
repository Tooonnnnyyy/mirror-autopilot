"""Scoring (spec 4.2) and relevance (spec 4.3).

The job golden test is the important one: radar's job score must equal autopilot's score_jd for the
same JD and profile, or the two tools will disagree about the same job.
"""

from __future__ import annotations

import sys
import unittest

from helpers import PROFILE, ROOT, future, op, past

from radar import scoring
from radar.schema import Gate

sys.path.insert(0, str(ROOT / "src"))
import autopilot  # noqa: E402  (the real score_jd, imported on purpose)

JDS = [
    "AI agent 产品实习生，北京海淀，300-350元/天，熟悉 Python 和产品设计，有 AI 经验加分。",
    "Data analyst intern. SQL, Python, Excel. Remote hybrid. 实习 4 个月。",
    "Senior Backend Engineer. Go, Kubernetes, 5+ years. No internship.",
    "",
]


class JobGoldenTests(unittest.TestCase):
    def test_same_number_as_autopilot(self):
        profile = dict(PROFILE["job"])
        profile["threshold"] = PROFILE["threshold"]
        for jd in JDS:
            with self.subTest(jd=jd[:30]):
                expected = autopilot.score_jd(profile, jd)
                actual, _ = scoring.score_job(jd, PROFILE["job"])
                self.assertEqual(actual, expected["score"])

    def test_reasons_are_readable(self):
        _, reasons = scoring.score_job(JDS[0], PROFILE["job"])
        self.assertTrue(any(reason.startswith("skills ") for reason in reasons))


class RelevanceTests(unittest.TestCase):
    def test_high_on_a_tech_word_in_the_text(self):
        level, keyword, bucket = scoring.classify(op(title="Ottawa AI Builders Night"), PROFILE)
        self.assertEqual(level, "high")
        self.assertIn(bucket, ("tech", "builder"))
        self.assertTrue(keyword)

    def test_low_on_a_concert(self):
        level, keyword, _ = scoring.classify(op(title="Winter Choir Concert", org="", raw_text=""), PROFILE)
        self.assertEqual(level, "low")
        self.assertEqual(keyword, "concert")

    def test_no_evidence_is_mid_not_high(self):
        level, _, _ = scoring.classify(op(title="Quarterly Gathering", org="", raw_text=""), PROFILE)
        self.assertEqual(level, "mid")

    def test_a_strong_word_only_in_the_organizer_name_is_not_high(self):
        # "National Social Networking Group" runs mixers; that must not read as a tech event.
        level, _, _ = scoring.classify(
            op(title="Weekly Gathering", org="National Social Networking Group", raw_text=""),
            PROFILE,
        )
        self.assertEqual(level, "mid")

    def test_low_relevance_is_ignored_with_its_reason(self):
        row = op(title="Zumba Party", org="", raw_text="", gate=Gate())
        scoring.score(row, PROFILE)
        self.assertEqual(row.status, "ignored")
        self.assertEqual(row.status_reason, "relevance_low")
        self.assertEqual(row.score, 0)

    def test_close_date_does_not_push_a_low_row_up(self):
        soon = op(title="Community Soup Festival", org="", raw_text="soup, food", date=future(1), gate=Gate())
        far = op(title="Ottawa AI Builders Night", date=future(40), gate=Gate())
        scoring.score(soon, PROFILE)
        scoring.score(far, PROFILE)
        self.assertLess(soon.score, far.score)
        self.assertEqual(soon.status, "ignored")


class ReasonFormatTests(unittest.TestCase):
    def test_three_fixed_elements(self):
        row = op(gate=Gate())
        scoring.score(row, PROFILE)
        self.assertTrue(row.reasons[0].startswith("relevance: high (keyword: "))
        self.assertEqual(row.reasons[1], "type: event")
        self.assertTrue(row.reasons[2].startswith("bucket: "))

    def test_mid_rows_are_halved(self):
        base = op(title="Ottawa AI Builders Night", gate=Gate())
        scoring.score(base, PROFILE)
        mid = op(title="Community Meetup", org="Ottawa", raw_text="meetup community", gate=Gate())
        scoring.score(mid, PROFILE)
        self.assertEqual(scoring.classify(mid, PROFILE)[0], "mid")
        self.assertLess(mid.score, base.score)


if __name__ == "__main__":
    unittest.main()
