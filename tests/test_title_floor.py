import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build
from tests.test_seo_unique import seo_for, LONG_D


class TitleFloor(unittest.TestCase):
    def test_short_title_reported(self):
        r = seo_for({"/brand/": ("A" * 20, LONG_D), "/legal/": ("B" * 40, LONG_D)})
        self.assertEqual([d["page"] for d in r["title_too_short"]], ["/brand/index.html"])
        self.assertEqual(r["title_too_short"][0]["length"], 20)

    def test_full_build_reports_none(self):
        r = build.check_seo()
        self.assertEqual(r["title_too_short"], [])


if __name__ == "__main__":
    unittest.main()
