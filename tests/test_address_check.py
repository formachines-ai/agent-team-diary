import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

MODEL = {"products": {"p": {"days": {}}}, "dates": ["2026-11-18"]}


def populate(root):
    for a in build.fixed_addresses(MODEL):
        f = root / a.lstrip("/") / "index.html" if a.endswith("/") else root / a.lstrip("/")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    (root / "sitemap.xml").write_text("<urlset><url><loc>https://example.org/about/</loc></url></urlset>", encoding="utf-8")


class AddressTest(unittest.TestCase):
    def run_check(self, remove=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            populate(root)
            if remove:
                (root / remove).unlink()
            with mock.patch.object(build, "PUBLIC_DIR", root):
                return build.check_address(MODEL)

    def test_removed_address_reported(self):
        r = self.run_check("product/p/index.html")
        self.assertEqual(r["missing"], ["/product/p/"])

    def test_complete_build_has_no_missing(self):
        r = self.run_check()
        self.assertEqual(r["missing"], [])
        self.assertTrue(r["expected"])


if __name__ == "__main__":
    unittest.main()
