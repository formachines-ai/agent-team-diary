import gzip, re, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

NOTE = "failed: " + "criterion not met " * 20  # > 160 chars


def task(tid, hist):
    return {"id": tid, "title": f"Task {tid}", "type": "feature", "state": "ready", "priority": "P2", "role": "developer",
            "created": "2026-11-20T00:00:00+00:00", "history": hist}


def day(tasks):
    return {"slug": "demo", "name": "Demo", "date": "", "tasks": tasks, "reviews": [], "posts": [], "metrics": {}, "spend_usd": 0.1}


class ReviewReturns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        with mock.patch.object(build, "PUBLIC_DIR", root):
            model = build.load_data()
            model["built"] = build.iso(build.utcnow())
            model["errors"] = []
            ret = day([task("T-9001", [
                {"ts": "2026-11-24T08:00:00+00:00", "actor": "dispatcher", "to": "review", "note": ""},
                {"ts": "2026-11-24T08:05:00+00:00", "actor": "reviewer", "to": "in_progress", "note": NOTE}])])
            ok = day([task("T-9002", [
                {"ts": "2026-11-25T08:00:00+00:00", "actor": "dispatcher", "to": "review", "note": ""},
                {"ts": "2026-11-25T08:05:00+00:00", "actor": "reviewer", "to": "accepted", "note": "ok"}])])
            ret["date"], ok["date"] = "2026-11-24", "2026-11-25"
            model["products"] = {"demo": {"product": {"slug": "demo", "name": "Demo"}, "days": {"2026-11-24": ret, "2026-11-25": ok}}}
            model["dates"] = ["2026-11-24", "2026-11-25"]
            build.write_site(model)
        cls.root = root
        rd = lambda p: (root / p / "index.html").read_text(encoding="utf-8")
        cls.ret, cls.ok, cls.about = rd("day/2026-11-24"), rd("day/2026-11-25"), rd("about")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_returned_listed(self):
        sec = self.ret.split('id="day-returned"', 1)[1].split("</section>", 1)[0]
        self.assertIn("T-9001", sec)
        notes = re.findall(r'<span class="note">(.*?)</span>', sec)
        self.assertEqual(len(notes), 1)
        self.assertLessEqual(len(notes[0]), 160)

    def test_none_returned(self):
        sec = self.ok.split('id="day-returned"', 1)[1].split("</section>", 1)[0]
        self.assertIn("no task returned by the reviewer", sec)
        self.assertNotIn("T-9002", sec)

    def test_about(self):
        sec = self.about.split('id="review-separation"', 1)[1].split("<h2", 1)[0]
        self.assertIn('href="#guards"', sec)
        self.assertIn('href="/go/github/"', sec)

    def test_budget_canonical_footer(self):
        for html in (self.ret, self.ok):
            self.assertLessEqual(len(gzip.compress(html.encode(), compresslevel=build.GZIP_LEVEL, mtime=0)), 36000)
            self.assertEqual(len(re.findall(r'<link rel="canonical"', html)), 1)
            self.assertIn("Written by the agent team itself", html)


if __name__ == "__main__":
    unittest.main()
