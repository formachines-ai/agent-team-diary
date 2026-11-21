import re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def task(tid, *states):
    return {"id": tid, "history": [{"ts": f"2026-11-20T0{i}:00:00+00:00", "to": s, "actor": "a", "note": "n"} for i, s in enumerate(states)]}


def model(tasks):
    day = {"tasks": tasks, "reviews": []}
    return {"products": {"p": {"product": {"name": "P"}, "days": {"2026-11-20": day}}}}


class ReviewCaughtTest(unittest.TestCase):
    def test_two_fails_one_accept(self):
        m = model([task("T-1", "review", "ready"), task("T-2", "review", "in_progress"), task("T-3", "review", "accepted")])
        rc = build.review_caught(m["products"]["p"]["days"]["2026-11-20"])
        self.assertEqual(rc, {"accepted": 1, "sent_back": 2, "sent_back_tasks": ["T-1", "T-2"]})
        html = build.day_review_caught_block("2026-11-20", m)
        self.assertIn('id="day-review-caught"', html)
        self.assertIn("P: accepted 1, sent back 2: ", html)
        for t in ("T-1", "T-2"):
            self.assertIn(f'<a href="#p-{t}">{t}</a>', html)

    def test_no_review_recorded(self):
        m = model([task("T-9", "in_progress")])
        self.assertIsNone(build.review_caught(m["products"]["p"]["days"]["2026-11-20"]))
        self.assertIn("no review recorded", build.day_review_caught_block("2026-11-20", m))

    def test_build_size_budget(self):
        import json
        bj = json.loads((Path(build.PUBLIC_DIR) / "build.json").read_text(encoding="utf-8"))
        self.assertLessEqual(bj["size_check"]["max_bytes"], 35400)
        self.assertEqual(bj["size_check"]["over_budget"], [])


if __name__ == "__main__":
    unittest.main()
