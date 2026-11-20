import re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def first_p(page):
    main = page[page.index("<main"):]
    return re.search(r"<p[ >].*?</p>", main, re.S).group(0)


def model(with_day):
    days = {"2026-11-18": {"tasks": [], "reviews": []}} if with_day else {}
    return {"products": {"p": {"product": {"slug": "p", "name": "P"}, "days": days}}, "dates": ["2026-11-18"],
            "built": "2026-11-19T00:00:00Z"}


class DayIntroTest(unittest.TestCase):
    def test_intro_names_task_records_and_links_about(self):
        p = first_p(build.render_day("2026-11-18", model(True)))
        self.assertIn("task records", p)
        self.assertIn('href="/about/"', p)
        self.assertIn('href="/try/"', p)

    def test_empty_day_claims_no_activity(self):
        page = build.render_day("2026-11-18", model(False))
        self.assertIn("no activity recorded", page)
        p = first_p(page)
        self.assertIn("no task records exist", p)
        self.assertNotIn("generated from its own task records", p)


if __name__ == "__main__":
    unittest.main()
