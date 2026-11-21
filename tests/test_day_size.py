import copy, gzip, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build

DATE = "2026-11-20"


def doubled_model() -> dict:
    """The real model with every task history of DATE twice as long."""
    model = build.load_data()
    model["built"] = build.iso(build.utcnow())
    model["errors"] = []
    for p in model["products"].values():
        day = p["days"].get(DATE)
        if day:
            for t in day.get("tasks") or []:
                t["history"] = list(t.get("history") or []) * 2
    return model


class DaySize(unittest.TestCase):
    def test_double_transitions_under_budget_or_reported(self):
        model = doubled_model()
        html = build.render_day(DATE, model)
        gz = len(gzip.compress(html.encode(), compresslevel=build.GZIP_LEVEL, mtime=0))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "day" / DATE
            out.mkdir(parents=True)
            (out / "index.html").write_text(html, encoding="utf-8")
            with mock.patch.object(build, "PUBLIC_DIR", Path(tmp)):
                r = build.check_size()
        pages = [d["page"] for d in r["over_budget"]]
        if gz > build.GZIP_BUDGET_BYTES:
            self.assertEqual(pages, [f"/day/{DATE}/"], "an oversized page must be reported by the check")
        else:
            self.assertEqual(pages, [])

    def test_full_build_no_day_over_budget(self):
        r = build.check_size()
        days = [d for d in r["over_budget"] if d["page"].startswith("/day/")]
        self.assertEqual(days, [], "day pages over the gzip budget")
        self.assertTrue(any(p["page"].startswith("/day/") for p in r["pages"]))


if __name__ == "__main__":
    unittest.main()
