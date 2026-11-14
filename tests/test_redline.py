"""The red lines that code can check (spec 6): quiet hours and credentials on disk."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from helpers import PROFILE, ROOT

from radar import redline
from radar.schema import TORONTO


class QuietHoursTests(unittest.TestCase):
    def test_three_in_the_morning_is_refused(self):
        with self.assertRaises(redline.RedLineError):
            redline.check_night((0, 7), datetime(2026, 11, 14, 3, 0, tzinfo=TORONTO))

    def test_daytime_is_fine(self):
        redline.check_night((0, 7), datetime(2026, 11, 14, 9, 30, tzinfo=TORONTO))


class SecretTests(unittest.TestCase):
    def test_a_credential_field_stops_the_run(self):
        bad = dict(PROFILE, api_key="sk-this-should-not-be-here")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(redline.RedLineError):
                redline.check_no_secrets(path, bad)

    def test_the_real_profile_is_clean(self):
        redline.check_no_secrets(ROOT / "radar" / "profile.json", PROFILE)

    def test_profile_shape_is_required(self):
        with self.assertRaises(redline.RedLineError):
            redline.check_profile_shape({"threshold": 60})


if __name__ == "__main__":
    unittest.main()
