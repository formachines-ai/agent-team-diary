import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


class CheckRegressionsTest(unittest.TestCase):
    def test_long_identifier_title_passes_length_check(self):
        lead = "One accepted task: Fix failing test_canary_with_real_output_passes ('canary empty result') on a clean checkout (T-0170)."
        title = build.day_title("2026-11-19", lead)
        event = title.removesuffix(build.TITLE_SUFFIX).partition(": ")[2]
        self.assertGreaterEqual(build.event_len(event), build.EVENT_MIN, title)
        self.assertLessEqual(len(title), build.DAY_TITLE_MAX)
        self.assertIn("2026-11-19", title)

    def test_dead_link_reported_and_prose_punctuation_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "build.json").write_text("{}")
            (root / "day" / "2026-11-02").mkdir(parents=True)
            (root / "day" / "2026-11-02" / "index.html").write_text("x")
            (root / "day" / "2026-11-18").mkdir(parents=True)
            base = build.SITE_BASE
            note = f"see {base}/build.json: ok and [\\\"{base}/day/2026-11-02/\\\"] fine, but {base}/missing/page/ is gone"
            (root / "day" / "2026-11-18" / "index.json").write_text(json.dumps({"note": note}))
            with mock.patch.object(build, "PUBLIC_DIR", root):
                res = build.check_machine_urls()
        hrefs = [b["href"] for b in res["broken"]]
        self.assertEqual(hrefs, [f"{base}/missing/page/"])


if __name__ == "__main__":
    unittest.main()
