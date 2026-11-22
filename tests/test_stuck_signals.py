import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def task(tid, *states):
    return {"id": tid, "history": [{"ts": f"2026-11-20T{i:02d}:00:00+00:00", "to": s, "actor": "a", "note": "n"} for i, s in enumerate(states)]}


def model(tasks):
    return {"products": {"p": {"product": {"name": "P"}, "days": {"2026-11-20": {"tasks": tasks, "reviews": []}}}}}


class StuckSignalsTest(unittest.TestCase):
    def test_one_blocked_one_failed_twice(self):
        m = model([task("T-1", "in_progress", "blocked"),
                   task("T-2", "review", "ready", "review", "in_progress"), task("T-3", "review", "ready")])
        s = build.stuck_signals(m["products"]["p"]["days"]["2026-11-20"])
        self.assertEqual(s, {"blocked": 1, "blocked_tasks": ["T-1"], "repeat_fails": 1, "repeat_fail_tasks": ["T-2"]})
        html = build.day_stuck_block("2026-11-20", m)
        self.assertIn('id="day-stuck"', html)
        self.assertIn("P: blocked 1", html)
        self.assertIn('<a href="#p-T-1">T-1</a>', html)
        self.assertIn('<a href="#p-T-2">T-2</a>', html)
        self.assertNotIn("T-3", html)

    def test_none(self):
        self.assertIn("no stuck signal recorded", build.day_stuck_block("2026-11-20", model([task("T-9", "review", "accepted")])))

    def test_build_size_budget(self):
        bj = json.loads((Path(build.PUBLIC_DIR) / "build.json").read_text(encoding="utf-8"))
        self.assertLessEqual(bj["size_check"]["max_bytes"], 35400)
        self.assertEqual(bj["size_check"]["over_budget"], [])


if __name__ == "__main__":
    unittest.main()
