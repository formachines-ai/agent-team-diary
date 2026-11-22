import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build


class DayCta(unittest.TestCase):
    def test_links_before_day_lead(self):
        model = build.load_data()
        model["built"] = build.iso(build.utcnow())
        model["errors"] = []
        html = build.render_day(model["dates"][-1], model)
        lead = html.find('id="day-lead"')
        self.assertGreater(lead, 0)
        for href in ("/try/", "/go/github/"):
            i = html.find(f'href="{href}"')
            self.assertTrue(0 <= i < lead, href)

    def test_full_build_within_size_check(self):
        public = ROOT / "public"
        r = build.check_size()
        self.assertEqual(r["over_budget"], [])
        self.assertTrue(list(public.glob("day/*/index.html")))
