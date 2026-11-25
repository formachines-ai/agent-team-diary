import re, sys, unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build

NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _hrefs():
    return set(re.findall(r'<a\b[^>]*?\bhref="([^"]+)"', (build.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")))


class InternalLinks(unittest.TestCase):
    def test_home_links_products_and_latest_14_days(self):
        hrefs = _hrefs()
        slugs = [p.parent.name for p in build.PUBLIC_DIR.glob("product/*/index.html")]
        self.assertGreaterEqual(len(slugs), 5)
        for s in slugs:
            self.assertIn(f"/product/{s}/", hrefs)
        days = sorted(p.parent.name for p in build.PUBLIC_DIR.glob("day/*/index.html"))[-14:]
        self.assertEqual(len(days), 14)
        for d in days:
            self.assertIn(f"/day/{d}/", hrefs)

    def test_every_sitemap_url_has_valid_lastmod(self):
        urls = list(ET.parse(build.PUBLIC_DIR / "sitemap.xml").getroot())
        self.assertGreater(len(urls), 20)
        for u in urls:
            lm = u.findtext(NS + "lastmod")
            self.assertIsNotNone(lm, u.findtext(NS + "loc"))
            self.assertRegex(lm, r"^\d{4}-\d{2}-\d{2}$")
            date.fromisoformat(lm)
            loc = u.findtext(NS + "loc")
            m = re.search(r"/day/(\d{4}-\d{2}-\d{2})/$", loc)
            if m:
                self.assertEqual(lm, m.group(1))

    def test_full_build_within_size_check(self):
        sc = build.check_size()
        self.assertEqual(sc["over_budget"], [])
        self.assertLessEqual(sc["largest_gzip_bytes"], 36000)


if __name__ == "__main__":
    unittest.main()
