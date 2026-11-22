import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def prod(spends):
    return {"product": {"name": "P"}, "days": {f"2026-11-{i + 1:02d}": ({"spend_usd": s} if s is not None else {}) for i, s in enumerate(spends)}}


class SpendFlagTest(unittest.TestCase):
    def test_median_and_flag(self):
        p = prod([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 9.0, 8.0, 50.0])  # days 1..10
        v = build.spend_vs_typical("2026-11-10", p)  # earlier 7: days 3..9 -> 3,4,5,6,7,9,8 -> median 6
        self.assertEqual((v["spend_usd"], v["median_7d_usd"], v["days_in_median"], v["bad_day"]), (50.0, 6.0, 7, True))
        self.assertFalse(build.spend_vs_typical("2026-11-09", p)["bad_day"])  # 8 vs median 5
        m = {"products": {"p": p}}
        html = build.day_spend_block("2026-11-10", m)
        self.assertIn('id="day-spend"', html)
        self.assertIn("bad day", html)
        short = {"products": {"p": prod([1.0, 2.0, 9.0])}}
        v = build.spend_vs_typical("2026-11-03", short["products"]["p"])
        self.assertIsNone(v["median_7d_usd"])
        self.assertFalse(v["bad_day"])
        self.assertIn("not enough history", build.day_spend_block("2026-11-03", short))
        self.assertIn("no spend recorded", build.day_spend_block("2026-11-02", {"products": {"p": prod([1.0, None])}}))

    def test_build_size_budget(self):
        bj = json.loads((Path(build.PUBLIC_DIR) / "build.json").read_text(encoding="utf-8"))
        self.assertEqual(bj["size_check"]["over_budget"], [])
        self.assertLessEqual(bj["size_check"]["max_bytes"], build.GZIP_BUDGET_BYTES)
        idx = json.loads((Path(build.PUBLIC_DIR) / "day" / "2026-11-21" / "index.json").read_text(encoding="utf-8"))
        for v in idx["spend_vs_typical"].values():
            self.assertLessEqual(v["days_in_median"], 7)


if __name__ == "__main__":
    unittest.main()
