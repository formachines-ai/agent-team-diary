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
        return model, build.check_day_nav(model)


class DayNavTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "static").mkdir()
        shutil.copy(ROOT / "static" / "style.css", self.root / "static" / "style.css")
        make_data(self.root, ["2026-11-02", "2026-11-03", "2026-11-04"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_build_is_clean(self):
        model, res = run_build(self.root)
        self.assertEqual(res["missing_prev"], [])
        self.assertEqual(res["missing_next"], [])
        self.assertEqual(res["days"], 3)

    def test_removed_prev_link_is_reported(self):
        run_build(self.root)
        page = self.root / "public" / "day" / "2026-11-03" / "index.html"
        page.write_text(page.read_text(encoding="utf-8").replace('rel="prev"', 'rel="x"'), encoding="utf-8")
        with mock.patch.object(build, "PUBLIC_DIR", self.root / "public"):
            res = build.check_day_nav({"dates": ["2026-11-02", "2026-11-03", "2026-11-04"]})
        self.assertEqual(res["missing_prev"], ["2026-11-03"])
        self.assertEqual(res["missing_next"], [])


if __name__ == "__main__":
    unittest.main()
