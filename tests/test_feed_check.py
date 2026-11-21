import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build

B = build.SITE_BASE


def feed(*items):
    body = "".join(f"<item><link>{l}</link><guid>{g}</guid><pubDate>Thu, 19 Nov 2026 07:00:00 +0000</pubDate></item>" for l, g in items)
    return f"<rss><channel>{body}</channel></rss>"


class FeedCheck(unittest.TestCase):
    def test_duplicate_guid_reported(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "about").mkdir()
            (Path(d) / "about" / "index.html").write_text("x")
            r = build.feed_lists(feed((B + "/about/", "g1"), (B + "/about/", "g1")), public=Path(d))
        self.assertEqual(r["duplicate_guids"], ["g1"])
        self.assertEqual(r["bad_links"], [])

    def test_missing_page_link_reported(self):
        with tempfile.TemporaryDirectory() as d:
            r = build.feed_lists(feed((B + "/nope/?src=rss", "g1")), public=Path(d))
        self.assertEqual(r["bad_links"], [B + "/nope/?src=rss"])
        self.assertEqual(r["missing_page"], [B + "/nope/?src=rss"])
        self.assertEqual(r["bad_link_form"], [])

    def test_relative_link_only_in_form(self):
        with tempfile.TemporaryDirectory() as d:
            r = build.feed_lists(feed(("/about/", "g1")), public=Path(d))
        self.assertEqual(r["bad_link_form"], ["/about/"])
        self.assertEqual(r["missing_page"], [])
        self.assertEqual(r["bad_links"], ["/about/"])

    def test_both_kinds_in_union(self):
        with tempfile.TemporaryDirectory() as d:
            r = build.feed_lists(feed(("/about/", "g1"), (B + "/nope/", "g2")), public=Path(d))
        self.assertEqual(r["bad_link_form"], ["/about/"])
        self.assertEqual(r["missing_page"], [B + "/nope/"])
        self.assertEqual(r["bad_links"], ["/about/", B + "/nope/"])

    def test_full_build_gives_empty(self):
        r = build.check_feed()
        for k in ("invalid", "bad_links", "bad_link_form", "missing_page", "duplicate_guids", "bad_dates"):
            self.assertEqual(r[k], [])


if __name__ == "__main__":
    unittest.main()
