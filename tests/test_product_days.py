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
        return model, build.check_product_days(model)


class ProductDaysTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "static").mkdir()
        shutil.copy(ROOT / "static" / "style.css", self.root / "static" / "style.css")

    def tearDown(self):
        self.tmp.cleanup()

    def page(self):
        return (self.root / "public" / "product" / "p" / "index.html").read_text(encoding="utf-8")

    def test_kept_day_stays_linked(self):
        make_data(self.root, ["2026-11-02", "2026-11-03"])
        run_build(self.root)
        (self.root / "data" / "p" / "day-2026-11-02.json").unlink()
        model, res = run_build(self.root)
        self.assertIn("2026-11-02", model["kept"])
        self.assertEqual(res["missing"], [])
        self.assertIn('href="/day/2026-11-02/#p"', self.page())
        # and the check is not a no-op: a page without the link is reported
        (self.root / "public" / "product" / "p" / "index.html").write_text("<html></html>", encoding="utf-8")
        self.assertIn(["p", "2026-11-02"], self._check_with(model)["missing"])

    def _check_with(self, model):
        with mock.patch.object(build, "PUBLIC_DIR", self.root / "public"):
            return build.check_product_days(model)

    def test_full_build_has_no_missing(self):
        make_data(self.root, ["2026-11-02", "2026-11-03"])
        _, res = run_build(self.root)
        self.assertEqual(res["missing"], [])
        self.assertIn('href="/day/2026-11-03/#p"', self.page())


if __name__ == "__main__":
    unittest.main()
