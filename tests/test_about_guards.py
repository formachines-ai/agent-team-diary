import re, sys, tempfile, unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


class Guards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = None; self.stack = []; self.lis = 0; self.hrefs = []; self.text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.depth is None and a.get("id") == "guards":
            self.depth = 0
        if self.depth is not None:
            self.depth += 1
            if tag == "li": self.lis += 1
            if tag == "a": self.hrefs.append(a.get("href", ""))

    def handle_endtag(self, tag):
        if self.depth is not None:
            self.depth -= 1


class AboutGuardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        with mock.patch.object(build, "PUBLIC_DIR", root):
            model = build.load_data()
            model["built"] = build.iso(build.utcnow())
            model["errors"] = []
            build.write_site(model)
        cls.html = (root / "about" / "index.html").read_text(encoding="utf-8")
        # the section runs from h2#guards to the next h2
        cls.section = cls.html.split('id="guards"', 1)[1].split("<h2", 1)[0]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_heading_and_items(self):
        self.assertIn('<h2 id="guards">Guards</h2>', self.html)
        items = re.findall(r"<li>(.*?)</li>", self.section, re.S)
        self.assertGreaterEqual(len(items), 5)
        joined = " ".join(items)
        for needle in ("without Bash", "data/public/", "STOP", "$20", "Reviewer separate"):
            self.assertIn(needle, joined)

    def test_links(self):
        hrefs = re.findall(r'href="([^"]+)"', self.section)
        self.assertTrue(hrefs)
        for h in hrefs:
            if h.startswith("/legal/"):
                continue
            self.assertTrue(h == "/go/github/" or h.startswith("https://github.com/OOuph/agent-team/"), h)

    def test_page_invariants(self):
        canon = re.findall(r'<link rel="canonical" href="([^"]+)"', self.html)
        self.assertEqual(canon, [build.SITE_BASE + "/about/"])
        self.assertIn(build.FOOTER_LINE, self.html)
        for sid in ("what", "roles", "cycle", "policies", "failure-modes", "method", "audit-trail", "this-site"):
            self.assertIn(f'id="{sid}"', self.html)
        self.assertNotIn("<script", self.html)


if __name__ == "__main__":
    unittest.main()
