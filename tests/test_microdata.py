import re, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

DATE = "2026-11-16"
BUILT = "2026-11-17T07:30:00Z"
ORG = '<div itemprop="publisher" itemscope itemtype="https://schema.org/Organization"></div>'


def day_html(itemtype="Article", published=DATE, modified=BUILT, foot=BUILT):
    return (f'<html><body><main itemscope itemtype="https://schema.org/{itemtype}">'
            f'<h1 itemprop="headline">T</h1><meta itemprop="datePublished" content="{published}">'
            f'<time itemprop="dateModified" datetime="{modified}">x</time>{ORG}</main>'
            f'<footer>updated <time datetime="{foot}">{foot}</time> UTC</footer></body></html>')


class MicrodataCheckTest(unittest.TestCase):
    def run_check(self, html_text):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            f = root / "day" / DATE / "index.html"
            f.parent.mkdir(parents=True)
            f.write_text(html_text, encoding="utf-8")
            with mock.patch.object(build, "PUBLIC_DIR", root):
                return build.check_microdata()

    def test_valid_page_passes(self):
        r = self.run_check(day_html())
        self.assertEqual((r["pages_checked"], r["missing"], r["date_mismatches"]), (1, [], []))

    def test_missing_itemtype_reported(self):
        r = self.run_check(day_html(itemtype="Thing"))
        self.assertIn({"page": f"/day/{DATE}/", "issue": 'itemtype="https://schema.org/Article"'}, r["missing"])

    def test_wrong_date_modified_reported(self):
        r = self.run_check(day_html(modified="2026-11-16T00:00:00Z"))
        self.assertEqual(r["missing"], [])
        self.assertEqual(r["date_mismatches"], [{"page": f"/day/{DATE}/", "issue": "dateModified != footer build time"}])

    def test_wrong_date_published_reported(self):
        r = self.run_check(day_html(published="2026-11-15"))
        self.assertEqual(r["date_mismatches"], [{"page": f"/day/{DATE}/", "issue": "datePublished != page date"}])

    def test_script_reported(self):
        r = self.run_check(day_html().replace("</body>", "<script>1</script></body>"))
        self.assertIn("no <script", [i["issue"] for i in r["missing"]])


class GeneratedSiteTest(unittest.TestCase):
    def test_day_pages_are_articles_with_own_date(self):
        pages = sorted((build.PUBLIC_DIR / "day").glob("*/index.html"))
        self.assertTrue(pages)
        for f in pages:
            t = f.read_text(encoding="utf-8")
            self.assertIn('itemtype="https://schema.org/Article"', t, f)
            m = re.search(r'<meta itemprop="datePublished" content="([^"]*)"', t)
            self.assertEqual(m and m.group(1), f.parent.name, f)

    def test_no_script_in_generated_html(self):
        files = list(build.PUBLIC_DIR.glob("**/*.html"))
        self.assertTrue(files)
        for f in files:
            self.assertNotIn("<script", f.read_text(encoding="utf-8").lower(), f)

    def test_real_site_microdata_clean(self):
        r = build.check_microdata()
        self.assertEqual((r["missing"], r["date_mismatches"]), ([], []))


if __name__ == "__main__":
    unittest.main()
