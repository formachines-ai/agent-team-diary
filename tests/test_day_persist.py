import sys, tempfile, unittest, shutil, json
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

ROOT = Path(__file__).resolve().parent.parent


def make_data(root, days):
    p = root / "data" / "p"
    p.mkdir(parents=True)
    (p / "product.json").write_text(json.dumps({"slug": "p", "name": "P", "site": "https://example.org"}), encoding="utf-8")
    for d in days:
        (p / f"day-{d}.json").write_text(json.dumps({"tasks": [], "reviews": [], "posts": []}), encoding="utf-8")


def run_build(root):
    with mock.patch.object(build, "DATA_DIR", root / "data"), mock.patch.object(build, "PUBLIC_DIR", root / "public"), \
            mock.patch.object(build, "ROOT", root):
        model = build.load_data()
        model["built"] = "2026-11-20T08:00:00Z"
        model["errors"] = []
        build.write_site(model)
        return model, build.check_day_persist(model)


class DayPersistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "static").mkdir()
        shutil.copy(ROOT / "static" / "style.css", self.root / "static" / "style.css")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dropped_day_survives(self):
        make_data(self.root, ["2026-11-02", "2026-11-03"])
        run_build(self.root)
        page = self.root / "public" / "day" / "2026-11-02" / "index.html"
        before = (page.read_text(encoding="utf-8"), (page.parent / "index.json").read_text(encoding="utf-8"))
        (self.root / "data" / "p" / "day-2026-11-02.json").unlink()
        model, res = run_build(self.root)
        self.assertEqual(res["missing"], [])
        self.assertIn("2026-11-02", res["published_before"])
        self.assertEqual(before, (page.read_text(encoding="utf-8"), (page.parent / "index.json").read_text(encoding="utf-8")))
        sm = (self.root / "public" / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn(f"<loc>{build.SITE_BASE}/day/2026-11-02/</loc>", sm)

    def test_full_build_has_no_missing(self):
        make_data(self.root, ["2026-11-02", "2026-11-03"])
        run_build(self.root)
        _, res = run_build(self.root)
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["published_before"], ["2026-11-02", "2026-11-03"])


if __name__ == "__main__":
    unittest.main()
