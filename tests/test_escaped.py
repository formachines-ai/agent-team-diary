import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def task(tid, *steps):
    return {"id": tid, "history": [{"ts": ts, "to": to, "actor": "a", "note": "n"} for ts, to in steps]}


def model(days):
    return {"products": {"p": {"days": days}}}


class EscapedAfterAcceptTest(unittest.TestCase):
    def test_accepted_to_ready_counted_across_days(self):
        m = model({
            "2026-11-18": {"tasks": [task("T-1", ("2026-11-18T08:00:00+00:00", "ready"), ("2026-11-18T09:00:00+00:00", "accepted"))]},
            "2026-11-19": {"tasks": [task("T-1", ("2026-11-18T08:00:00+00:00", "ready"), ("2026-11-18T09:00:00+00:00", "accepted"),
                                          ("2026-11-19T10:00:00+00:00", "ready"))]},
        })
        self.assertEqual(build.escaped_after_accept("2026-11-19", m), {"count": 1, "tasks": ["T-1"]})
        self.assertEqual(build.escaped_after_accept("2026-11-18", m)["count"], 0)

    def test_ready_to_accepted_not_counted(self):
        m = model({"2026-11-19": {"tasks": [task("T-2", ("2026-11-19T08:00:00+00:00", "ready"), ("2026-11-19T09:00:00+00:00", "accepted"),
                                                  ("2026-11-19T10:00:00+00:00", "measured"))]}})
        self.assertEqual(build.escaped_after_accept("2026-11-19", m), {"count": 0, "tasks": []})

    def test_no_record_day_claims_no_activity(self):
        m = model({"2026-11-19": {"tasks": []}})
        block = build.day_escaped_block("2026-11-20", m)
        self.assertEqual(build.escaped_after_accept("2026-11-20", m)["count"], 0)
        self.assertIn("no activity recorded", block)
        self.assertNotIn("no accepted or done task reopened", block)


if __name__ == "__main__":
    unittest.main()
