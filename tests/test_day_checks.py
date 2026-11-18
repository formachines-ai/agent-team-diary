import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def idx(accepted, fails=0, spend=1.0):
    return {"counts": {"p": {"fixture": False}}, "totals": {"tasks_done_distinct": accepted, "spend_usd": spend},
            "broke_counts": {"review_fail": fails}}


def model(posts_by_date):
    return {"products": {"p": {"days": {d: {"posts": posts} for d, posts in posts_by_date.items()}}}}


class DayChecksTest(unittest.TestCase):
    def write_site(self, root, date, idx_by_date, posts, tamper=None):
        """Write public/day/<date>/ the way build.py does: page blocks and index.json from the same functions."""
        m = model({date: posts})
        base = build.day_baseline_block(date, m, idx_by_date)
        ext = build.day_external_block(date, m)
        if tamper:
            base, ext = tamper(base, ext)
        d = root / "day" / date
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(f'<div id="day-lead"></div>{ext}{base}', encoding="utf-8")
        j = {"baseline": build.baseline_json(date, idx_by_date), "external_actions": build.external_actions(date, m)}
        (d / "index.json").write_text(json.dumps(j), encoding="utf-8")
        for other in idx_by_date:  # earlier days: index.json only needs to exist for baseline_values
            if other != date:
                o = root / "day" / other
                o.mkdir(parents=True, exist_ok=True)
                (o / "index.json").write_text(json.dumps(idx_by_date[other]), encoding="utf-8")
        return j

    def run_check(self, fn, date, idx_by_date, posts=(), tamper=None):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            j = self.write_site(root, date, idx_by_date, list(posts), tamper)
            # the day's own index.json must carry the idx fields too, as the real one does
            p = root / "day" / date / "index.json"
            p.write_text(json.dumps({**idx_by_date[date], **j}), encoding="utf-8")
            with mock.patch.object(build, "PUBLIC_DIR", root):
                return fn()

    def history(self, n):
        h = {f"2026-11-{i:02d}": idx(2 + i % 3, 0, 1.0 + i) for i in range(1, n + 1)}
        h[f"2026-11-{n + 1:02d}"] = idx(4, 0, 3.0)
        return h, f"2026-11-{n + 1:02d}"

    def test_baseline_consistent_passes(self):
        h, d = self.history(5)
        r = self.run_check(build.check_baseline, d, h)
        self.assertEqual(r["mismatches"], [])
        self.assertEqual(r["too_few_days"], [])

    def test_baseline_mismatch_detected(self):
        h, d = self.history(5)
        tamper = lambda b, e: (b.replace('data-b="today">4<', 'data-b="today">9<', 1), e)
        r = self.run_check(build.check_baseline, d, h, tamper=tamper)
        self.assertTrue(any(m.get("cell") == "today" and m.get("html") == "9" for m in r["mismatches"]), r)

    def test_baseline_median_mismatch_detected(self):
        h, d = self.history(5)
        tamper = lambda b, e: (b.replace('data-b="median">', 'data-b="median">99', 1), e)
        r = self.run_check(build.check_baseline, d, h, tamper=tamper)
        self.assertTrue(any(m.get("cell") == "median" for m in r["mismatches"]), r)

    def test_baseline_not_enough_history(self):
        h, d = self.history(build.BASELINE_MIN - 1)
        with tempfile.TemporaryDirectory() as t:
            m = model({d: []})
            block = build.day_baseline_block(d, m, h)
            self.assertIn("not enough history", block)
            self.assertNotIn('data-b="median"', block)
            j = build.baseline_json(d, h)
            self.assertFalse(j["enough_history"])
            self.assertTrue(all("median" not in v for v in j["metrics"].values()))
        r = self.run_check(build.check_baseline, d, h)
        self.assertEqual(r["mismatches"], [])
        self.assertEqual(r["too_few_days"], [d])

    def test_baseline_few_days_but_median_shown_detected(self):
        h, d = self.history(build.BASELINE_MIN - 1)
        tamper = lambda b, e: (b.replace('</section>', '<td data-b="median">1</td></section>'), e)
        r = self.run_check(build.check_baseline, d, h, tamper=tamper)
        self.assertTrue(r["mismatches"])

    POSTS = [{"channel": "bluesky", "ts": "2026-11-05T08:00:00Z", "url": "https://example.org/a"},
             {"channel": "bluesky", "ts": "2026-11-05T09:00:00Z", "url": "https://example.org/b"},
             {"channel": "devto", "ts": "2026-11-05T10:00:00Z", "url": "https://example.org/c"}]

    def test_external_consistent_passes(self):
        h, d = self.history(4)
        r = self.run_check(build.check_external, d, h, self.POSTS)
        self.assertEqual(r["mismatches"], [])

    def test_external_total_mismatch_detected(self):
        h, d = self.history(4)
        tamper = lambda b, e: (b, e.replace('data-ext="total">3<', 'data-ext="total">4<'))
        r = self.run_check(build.check_external, d, h, self.POSTS, tamper)
        self.assertTrue(any(m["issue"] == "total differs" for m in r["mismatches"]), r)

    def test_external_channel_count_mismatch_detected(self):
        h, d = self.history(4)
        tamper = lambda b, e: (b, e.replace("bluesky 2", "bluesky 1"))
        r = self.run_check(build.check_external, d, h, self.POSTS, tamper)
        self.assertTrue(any(m["issue"] == "channel count differs" for m in r["mismatches"]), r)

    def test_no_posts_gives_zero_and_note(self):
        h, d = self.history(4)
        ea = build.external_actions(d, model({d: []}))
        self.assertEqual(ea, {"total": 0, "by_channel": {}, "items": []})
        self.assertIn("no external actions recorded", build.day_external_block(d, model({d: []})))
        r = self.run_check(build.check_external, d, h, [])
        self.assertEqual(r["mismatches"], [])

    def test_empty_day_without_note_detected(self):
        h, d = self.history(4)
        tamper = lambda b, e: (b, e.replace("no external actions recorded", "nothing"))
        r = self.run_check(build.check_external, d, h, [], tamper)
        self.assertTrue(any(m["issue"] == "empty day lacks the note" for m in r["mismatches"]), r)


if __name__ == "__main__":
    unittest.main()
