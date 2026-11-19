import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def model(*states):
    hist = [{"to": s, "ts": f"2026-11-18T1{i}:00:00Z", "actor": "a", "note": ""} for i, s in enumerate(states)]
    d = {"tasks": [{"id": "T-1", "title": "x", "history": hist}], "reviews": [{"task": "T-1", "verdict": "fail"}]}
    return {"products": {"p": {"product": {"name": "P"}, "days": {"2026-11-18": d}}}, "dates": ["2026-11-18"]}


class LeadStateTest(unittest.TestCase):
    def test_rejected_not_worded_open(self):
        o = build.task_outcome("2026-11-18", model("ready", "rejected"), "p", "T-1")
        self.assertNotIn("open", o["text"])
        self.assertIn("rejected (closed)", o["text"])
        o = build.task_outcome("2026-11-18", model("ready", "failed"), "p", "T-1")
        self.assertIn("still open", o["text"])

    def test_check_flags_open_not_listed(self):
        txt = "Failed: Title (T-169), failed review, still open at end of day (final state: rejected)."
        m = build.lead_state_mismatches("/", txt, set())
        self.assertEqual([x["task"] for x in m], ["T-169"])

    def test_listed_open_passes(self):
        txt = "Failed: Title (T-169), failed review, still open at end of day (final state: failed)."
        self.assertEqual(build.lead_state_mismatches("/", txt, {"T-169"}), [])
        self.assertEqual(build.lead_state_mismatches("/", "Failed: X (T-169), failed review, then rejected (closed) (final state: rejected).", set()), [])


if __name__ == "__main__":
    unittest.main()
