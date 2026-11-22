import unittest

from jobs.apply_pack import numbers_not_in_cv
from jobs.score import clean_cv, evidence_hits, gate, score

CV = """Skills: Figma, usability testing, information architecture, accessibility, SQL, Python.
Reached 22K+ organic views. <!-- personas? ask Tony -->"""


def role(**kw):
    r = {"company": "Acme", "title": "Product Design Intern (Summer 2027)", "location": "Toronto, Canada",
         "jd_text": "You will use Figma for prototyping, run usability testing and build personas. Strong communication."}
    r.update(kw)
    return r


class T(unittest.TestCase):
    def test_comments_are_not_evidence(self):
        self.assertNotIn("personas", evidence_hits(CV))
        self.assertNotIn("ask Tony", clean_cv(CV))

    def test_gate_location_and_term(self):
        self.assertEqual(gate(role()), [])
        self.assertTrue(any("location" in f for f in gate(role(location="New York, NY"))))
        self.assertTrue(any("term" in f for f in gate(role(title="Design Intern (Winter 2027)"))))
        self.assertTrue(any("french" in f for f in gate(role(jd_text="Bilingual English and French required."))))

    def test_gap_is_not_matched(self):
        s = score(role(), CV, evidence_hits(CV))
        self.assertIn("personas", s["gaps"])
        self.assertIn("figma", s["matched"])
        self.assertEqual(s["lane"], "ux")

    def test_off_lane_capped(self):
        s = score(role(title="Software Engineer Intern", jd_text="Python SQL Figma accessibility usability testing communication"), CV, evidence_hits(CV))
        self.assertLessEqual(s["fit_score"], 60)

    def test_numbers_check(self):
        self.assertEqual(numbers_not_in_cv("reached 22K+ views", CV), [])
        self.assertIn("40%", " ".join(numbers_not_in_cv("grew signups 40%", CV)))


if __name__ == "__main__":
    unittest.main()
