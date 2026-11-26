import gzip, re, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build

HEADROOM = 35400
DAY = "2026-11-22"


class DayHeadroom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        with mock.patch.object(build, "PUBLIC_DIR", cls.out):
            model = build.load_data()
            model["built"] = build.iso(build.utcnow())
            model["errors"] = []
            build.write_site(model)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_day_page_within_headroom(self):
        pages = list(self.out.glob("day/*/index.html")) + list(self.out.glob("day/*/*/index.html"))
        self.assertTrue(pages)
        over = {str(p.relative_to(self.out)): n for p in pages
                if (n := len(gzip.compress(p.read_bytes(), compresslevel=build.GZIP_LEVEL, mtime=0))) > HEADROOM}
        self.assertEqual(over, {})

    def test_day_keeps_canonical_footer_and_sections(self):
        f = self.out / "day" / DAY / "index.html"
        if not f.exists():
            self.skipTest("no day file for " + DAY)
        h = f.read_text(encoding="utf-8")
        canon = re.findall(r'<link[^>]*rel="canonical"[^>]*>', h)
        self.assertEqual(len(canon), 1)
        self.assertIn(f"/day/{DAY}/", canon[0])
        self.assertIn(build.FOOTER_LINE, h)
        for i in ("day-lead", "what-broke", "not-to-plan", "broke", "artifact-line", "sha-line", "work-vs-people",
                  "work-vs-people-h", "day-stuck", "day-spend", "day-baseline-h", "day-external-h"):
            self.assertIn(f'id="{i}"', h, i)


if __name__ == "__main__":
    unittest.main()
