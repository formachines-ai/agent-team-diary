import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build


class HomeCta(unittest.TestCase):
    def test_links_before_first_h2(self):
        html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        h2 = html.find("<h2")
        self.assertGreater(h2, 0)
        for href in ("/try/", "/go/github/"):
            i = html.find(f'href="{href}"')
            self.assertTrue(0 <= i < h2, href)

    def test_full_build_within_size_check(self):
        r = build.check_size()
        self.assertEqual(r["over_budget"], [])
        self.assertTrue(list((ROOT / "public").glob("day/*/index.html")))
