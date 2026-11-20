import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def page(*hrefs):
    return "<html><body>" + "".join(f'<a href="{h}">x</a>' for h in hrefs) + "</body></html>"


class DiscoveryCheckTest(unittest.TestCase):
    def discover(self, pages, sitemap_paths):
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
                return build.check_discovery()

    def test_unlinked_and_too_deep_reported(self):
        pages = {"/": page("/a/"), "/a/": page("/b/"), "/b/": page("/c/"), "/c/": page(), "/lonely/": page()}
        r = self.discover(pages, ["/", "/a/", "/b/", "/c/", "/lonely/"])
        self.assertEqual(r["max_depth"], 2)
        self.assertEqual(r["unreachable"], [build.SITE_BASE + "/c/", build.SITE_BASE + "/lonely/"])

    def test_full_build_gives_empty(self):
        r = build.check_discovery()
        self.assertEqual(r["unreachable"], [])
        self.assertEqual(r["max_depth"], 2)


if __name__ == "__main__":
    unittest.main()
