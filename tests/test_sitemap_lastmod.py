import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build

B = "2026-11-20"
U = build.SITE_BASE + "/about/"


class SitemapLastmod(unittest.TestCase):
    def test_missing_reported(self):
        r = build.lastmod_check({U: "", build.SITE_BASE + "/try/": "2026-11-01"}, B)
        self.assertEqual(r["missing_lastmod"], [U])

    def test_future_reported(self):
        r = build.lastmod_check({U: "2026-11-21"}, B)
        self.assertEqual(r["future"], [U])
        self.assertEqual(r["invalid"], [])

    def test_full_build_gives_empty(self):
        r = build.check_robots_sitemap(build.json.loads((build.PUBLIC_DIR / "build.json").read_text())["built"])[1]
        for k in ("missing_lastmod", "invalid", "future"):
            self.assertEqual(r[k], [])
        self.assertGreaterEqual(r["urls"], 28)


if __name__ == "__main__":
    unittest.main()
