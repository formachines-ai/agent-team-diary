import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def page(root, rel, canon):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    tag = f'<link rel="canonical" href="{canon}">' if canon else ""
    f.write_text(f"<head>{tag}</head>", encoding="utf-8")


class CanonicalTest(unittest.TestCase):
    def run_check(self, day_canon):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            b = build.SITE_BASE
            page(root, "index.html", b + "/")
            page(root, "day/2026-11-19/index.html", day_canon)
            page(root, "404.html", "")
            (root / "sitemap.xml").write_text(f"<urlset><url><loc>{b}/</loc></url><url><loc>{b}/day/2026-11-19/</loc></url></urlset>", encoding="utf-8")
            with mock.patch.object(build, "PUBLIC_DIR", root):
                return build.check_canonical()

    def test_page_without_canonical_reported(self):
        r = self.run_check("")
        self.assertEqual(r["missing"], ["/day/2026-11-19/"])

    def test_wrong_canonical_reported(self):
        r = self.run_check(build.SITE_BASE + "/day/2026-11-19/?src=x")
        self.assertEqual(r["mismatched"], ["/day/2026-11-19/"])

    def test_complete_build_has_none(self):
        r = self.run_check(build.SITE_BASE + "/day/2026-11-19/")
        self.assertEqual(r, {"missing": [], "mismatched": []})


if __name__ == "__main__":
    unittest.main()
