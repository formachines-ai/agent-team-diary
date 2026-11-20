import re, sys, tempfile, unittest, html as htmllib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build

PUB = ROOT / "public"
LONG_D = "A description that is long enough to pass the seventy character minimum for meta text."


def page(path, title, desc):
    return (f'<!doctype html><html><head><title>{title}</title>'
            f'<link rel="canonical" href="{build.SITE_BASE}{path}">'
            f'<meta name="description" content="{desc}">'
            f'<meta property="og:description" content="{desc}"></head><body><main><p>x</p></main></body></html>')


def seo_for(pages):
    """Run build.check_seo() over a temporary public/ holding the given {path: (title, desc)}."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for path, (t, desc) in pages.items():
            f = root / path.strip("/") / "index.html" if path != "/" else root / "index.html"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(page(path, t, desc), encoding="utf-8")
        (root / "sitemap.xml").write_text("<urlset/>", encoding="utf-8")
        with mock.patch.object(build, "PUBLIC_DIR", root):
            return build.check_seo()


def head_of(rel):
    t = (PUB / rel).read_text(encoding="utf-8")
    title = htmllib.unescape(re.search(r"<title>(.*?)</title>", t, re.S).group(1).strip())
    m = re.search(r'<meta name="description" content="([^"]*)"', t)
    return title, htmllib.unescape(m.group(1)).strip() if m else ""


def first_p(rel):
    t = (PUB / rel).read_text(encoding="utf-8")
    main = t[t.index("<main"):]
    return re.sub(r"<[^>]+>", "", re.search(r"<p[ >].*?</p>", main, re.S).group(0))


class SeoCheckSyntheticTest(unittest.TestCase):
    def test_duplicate_title_reported(self):
        r = seo_for({"/about/": ("Same title for two pages in the diary · AI diary", LONG_D + " one"),
                     "/try/": ("Same title for two pages in the diary · AI diary", LONG_D + " two")})
        self.assertEqual(len(r["duplicate_titles"]), 1)
        self.assertEqual(sorted(r["duplicate_titles"][0]["pages"]), ["/about/", "/try/"])

    def test_duplicate_description_reported(self):
        r = seo_for({"/about/": ("First distinct title of the diary page · AI diary", LONG_D),
                     "/try/": ("Second distinct title of the diary page · AI diary", LONG_D)})
        self.assertEqual(len(r["description_duplicates"]), 1)
        self.assertEqual(sorted(r["description_duplicates"][0]["pages"]), ["/about/", "/try/"])

    def test_short_title_reported(self):
        r = seo_for({"/day/2026-11-19/": ("agent-team: fix · AI diary", LONG_D)})
        self.assertTrue(r["snippet_check"]["short_titles"])
        self.assertLess(len(r["snippet_check"]["short_titles"][0]["title"]), 30 + 10)

    def test_clean_pages_not_reported(self):
        r = seo_for({"/about/": ("First distinct title of the diary page · AI diary", LONG_D),
                     "/try/": ("Second distinct title of the diary page · AI diary", LONG_D + " two")})
        self.assertEqual((r["duplicate_titles"], r["description_duplicates"], r["snippet_check"]["short_titles"]), ([], [], []))


class GeneratedSiteTest(unittest.TestCase):
    def test_main_pages_distinct_and_long(self):
        rels = ["index.html", "try/index.html", "about/index.html", "legal/index.html"]
        rels += sorted(p.relative_to(PUB).as_posix() for p in PUB.glob("product/*/index.html"))
        heads = {r: head_of(r) for r in rels}
        titles = [h[0] for h in heads.values()]
        descs = [h[1] for h in heads.values()]
        self.assertEqual(len(titles), len(set(titles)), titles)
        self.assertEqual(len(descs), len(set(descs)), descs)
        for r, (t, d) in heads.items():
            self.assertGreaterEqual(len(t), 30, r)
            self.assertTrue(d, r)

    def test_day_titles_distinct(self):
        titles = [head_of(p.relative_to(PUB).as_posix())[0] for p in sorted(PUB.glob("day/*/index.html"))]
        self.assertTrue(titles)
        self.assertEqual(len(titles), len(set(titles)))

    def test_first_paragraph_wording(self):
        for rel in ("index.html", "try/index.html"):
            p = first_p(rel)
            self.assertIn("task records", p, rel)
            self.assertIn("daily", p.lower(), rel)


if __name__ == "__main__":
    unittest.main()
