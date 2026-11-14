"""Stable ids and near-duplicate merging (spec 2 and 5)."""

from __future__ import annotations

import unittest

from helpers import future, op

from radar.dedupe import canonical_url, dedupe, make_id, similar


class IdTests(unittest.TestCase):
    def test_tracking_parameters_do_not_change_the_id(self):
        self.assertEqual(
            make_id("luma", "https://luma.com/e1?utm_source=x&utm_medium=y", "Ottawa AI Night"),
            make_id("luma", "https://luma.com/e1", "Ottawa AI Night"),
        )

    def test_id_is_namespaced_by_source(self):
        self.assertTrue(make_id("meetup", "https://x/1", "T").startswith("meetup_"))
        self.assertNotEqual(make_id("luma", "https://x/1", "T"), make_id("meetup", "https://x/1", "T"))

    def test_canonical_url(self):
        self.assertEqual(
            canonical_url("https://Example.com/a/b/?utm_source=x&id=2#frag"),
            "https://example.com/a/b?id=2",
        )


class DedupeTests(unittest.TestCase):
    def test_same_id_is_kept_once(self):
        rows = [op(id="luma_a", url="https://luma.com/a"), op(id="luma_a", url="https://luma.com/a")]
        self.assertEqual(len(dedupe(rows)), 1)

    def test_near_identical_titles_merge(self):
        left = op(id="eventbrite_a", title="Ottawa AI Builders Night", org="A", url="https://a/1")
        right = op(id="meetup_b", title="Ottawa AI Builders Night!", org="B", url="https://b/2")
        self.assertTrue(similar(left, right))
        self.assertEqual(len(dedupe([left, right])), 1)

    def test_same_org_and_day_merge(self):
        left = op(id="eventbrite_a", title="Founder Soiree", org="99 The Agency", url="https://a/1", date=future(5))
        right = op(id="meetup_b", title="Founders' Soiree 2026", org="99 The Agency", url="https://b/2", date=future(5))
        self.assertTrue(similar(left, right))

    def test_different_events_stay(self):
        left = op(id="a", title="Ottawa AI Builders Night", org="A", url="https://a/1")
        right = op(id="b", title="Winter Choir Concert", org="B", url="https://b/2")
        self.assertFalse(similar(left, right))
        self.assertEqual(len(dedupe([left, right])), 2)

    def test_missing_required_fields_raise(self):
        with self.assertRaises(ValueError):
            dedupe([op(id="")])


if __name__ == "__main__":
    unittest.main()
