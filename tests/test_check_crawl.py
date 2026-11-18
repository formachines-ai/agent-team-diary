import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def page(*hrefs):
    return "<html><body>" + "".join(f'<a href="{h}">x</a>' for h in hrefs) + "</body></html>"


class CheckCrawlTest(unittest.TestCase):
    def crawl(self, pages, sitemap_paths):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for p, html in pages.items():
                f = root / p.strip("/") / "index.html"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(html, encoding="utf-8")
            urls = "".join(f"<url><loc>{build.SITE_BASE}{p}</loc></url>" for p in sitemap_paths)
            (root / "sitemap.xml").write_text(
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>", encoding="utf-8")
            with mock.patch.object(build, "PUBLIC_DIR", root):
                return build.check_crawl("2026-11-18T00:00:00Z")

    def test_fragment_resolves_to_page(self):
        r = self.crawl({"/": page("/a/#sec"), "/a/": page()}, ["/", "/a/"])
        self.assertEqual(r["unreachable"], [])
        self.assertEqual(r["depths"][build.SITE_BASE + "/a/"], 1)

    def test_bare_fragment_adds_no_page(self):
        r = self.crawl({"/": page("#x", "/a/"), "/a/": page("#y")}, ["/", "/a/"])
        self.assertEqual(r["unreachable"], [])
        self.assertEqual(r["max_depth"], 1)
        self.assertEqual(len(r["depths"]), 2)

    def test_query_and_fragment_same_page(self):
        r = self.crawl({"/": page("/a/?q=1#z", "/a/"), "/a/": page()}, ["/", "/a/"])
        self.assertEqual(r["unreachable"], [])
        self.assertEqual(r["depths"][build.SITE_BASE + "/a/"], 1)

    def test_fragment_only_link_reachable_within_3(self):
        pages = {"/": page("/a/#s"), "/a/": page("/b/#s"), "/b/": page("/c/?x=1#s"), "/c/": page()}
        r = self.crawl(pages, ["/", "/a/", "/b/", "/c/"])
        self.assertEqual(r["unreachable"], [])
        self.assertLessEqual(r["max_depth"], 3)
        self.assertEqual(r["depths"][build.SITE_BASE + "/c/"], 3)


if __name__ == "__main__":
    unittest.main()
