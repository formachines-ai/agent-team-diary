import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

DATE = "2026-11-18"


def task(tid, *states):
    return {"id": tid, "history": [{"to": s, "actor": "a", "note": "n"} for s in states]}


def model(*tasks):
    return {"products": {"p": {"days": {DATE: {"tasks": list(tasks)}}}}}


class EscapedTest(unittest.TestCase):
    def test_accepted_then_moved_is_counted(self):
        for first in ("accepted", "done"):
            e = build.escaped_tasks(DATE, model(task("T-1", "ready", first, "ready")))
            self.assertEqual(e["total"], 1)
            self.assertEqual([i["id"] for i in e["items"]], ["T-1"])

    def test_accepted_never_moved_not_counted(self):
        e = build.escaped_tasks(DATE, model(task("T-2", "ready", "accepted"), task("T-3", "ready", "done", "measured")))
        self.assertEqual(e, {"total": 0, "items": []})

    def test_no_transition_empty_note(self):
        m = model(task("T-4", "ready", "in_progress"))
        self.assertEqual(build.escaped_tasks(DATE, m)["total"], 0)
        self.assertIn("no reopened tasks recorded", build.day_escaped_block(DATE, m))

    def check(self, m, tamper=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            day = root / "day" / DATE
            day.mkdir(parents=True)
            e = build.escaped_tasks(DATE, m)
            (day / "index.json").write_text(json.dumps({"escaped": tamper(e) if tamper else e}), encoding="utf-8")
            (day / "index.html").write_text("<html>" + build.day_escaped_block(DATE, m) + "</html>", encoding="utf-8")
            with mock.patch.object(build, "PUBLIC_DIR", root):
                return build.check_escaped()

    def test_consistent_passes(self):
        m = model(task("T-1", "accepted", "ready"))
        self.assertEqual(self.check(m)["mismatches"], [])
        self.assertEqual(self.check(model(task("T-4", "ready")))["mismatches"], [])

    def test_total_mismatch_detected(self):
        m = model(task("T-1", "accepted", "ready"))
        r = self.check(m, lambda e: {"total": 2, "items": e["items"] * 2})
        self.assertTrue(r["mismatches"])
        self.assertEqual(r["mismatches"][0]["issue"], "total differs")


if __name__ == "__main__":
    unittest.main()
