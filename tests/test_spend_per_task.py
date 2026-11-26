import gzip, json, re, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

DAY = "2026-11-20"


def task(i):
    return {"id": f"T-{i}", "title": f"t{i}", "history": [{"to": "done", "by": "po", "at": f"{DAY}T10:00:00+00:00", "note": "ok"}]}


def day(spend, n):
    d = {"date": DAY, "tasks": [task(i) for i in range(n)], "reviews": [], "posts": []}
    if spend is not None:
        d["spend_usd"] = spend
    return d


class SpendPerTaskTest(unittest.TestCase):
    def build_page(self, days):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            data, pub = t / "data", t / "public"
            for slug, d in days.items():
                (data / slug).mkdir(parents=True)
                (data / slug / "product.json").write_text(json.dumps({"slug": slug, "name": slug, "site": "https://x.example/", "goals": []}))
                (data / slug / f"day-{DAY}.json").write_text(json.dumps(d))
            with mock.patch.object(build, "DATA_DIR", data), mock.patch.object(build, "PUBLIC_DIR", pub):
                model = build.load_data()
                model["built"] = build.iso(build.utcnow())
                model["errors"] = []
                build.write_site(model)
            return (pub / "day" / DAY / "index.html").read_text(encoding="utf-8")

    def block(self, html, slug):
        m = re.search(rf'<p[^>]*id="spend-per-task-{slug}"[^>]*>(.*?)</p>', html, re.S)
        self.assertIsNotNone(m, slug)
        return m.group(1)

    def test_all(self):
        html = self.build_page({"prod-a": day(3.0, 2), "prod-b": day(2.0, 0), "prod-c": day(None, 1)})
        self.assertIn("1.50", self.block(html, "prod-a"))
        self.assertIn("150 cents", self.block(html, "prod-a"))
        self.assertIn("no accepted task", self.block(html, "prod-b"))
        self.assertIn("no spend data", self.block(html, "prod-c"))
        self.assertLessEqual(len(gzip.compress(html.encode(), compresslevel=build.GZIP_LEVEL, mtime=0)), 36000)
        self.assertEqual(html.count('rel="canonical"'), 1)
        self.assertIn("Written by the agent team itself from its own task records, no human editing", html)


if __name__ == "__main__":
    unittest.main()
