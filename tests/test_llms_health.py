import json, sys, tempfile, unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build

DAY = "2026-11-16"


def make_site(root: Path, documented, task_keys):
    (root / "day" / DAY).mkdir(parents=True)
    task = {k: 1 for k in task_keys}
    task["history"] = [{"to": "done"}]
    (root / "day" / DAY / "index.json").write_text(
        json.dumps({"products": {"p": {"tasks": [task], "reviews": []}}}), encoding="utf-8")
    lines = "".join(f"- `products.<slug>.tasks[].{f}` x\n" for f in documented)
    (root / "llms.txt").write_text(f"## Audit trail per day\n{lines}\n## Next\n", encoding="utf-8")
    (root / "today.json").write_text("{}", encoding="utf-8")
    (root / "about").mkdir()
    (root / "about" / "index.html").write_text(
        f'<h2 id="audit-trail"></h2><a href="/day/{DAY}/index.json">i</a><a href="/llms.txt">l</a><h2>', encoding="utf-8")


class LlmsCheckTest(unittest.TestCase):
    def run_check(self, documented, task_keys):
        with tempfile.TemporaryDirectory() as d:
            make_site(Path(d), documented, task_keys)
            with mock.patch.object(build, "PUBLIC_DIR", Path(d)):
                return build.check_llms()

    def test_documented_field_missing_from_index(self):
        r = self.run_check(["id", "ghost_field"], ["id"])
        self.assertEqual(r["missing_fields"], ["ghost_field"])

    def test_all_documented_fields_present(self):
        r = self.run_check(["id", "state"], ["id", "state"])
        self.assertEqual(r["fields_named"], 2)
        self.assertEqual(r["missing_fields"], [])


class HealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.today = json.loads((ROOT / "public" / "today.json").read_text(encoding="utf-8"))
        cls.bj = json.loads((ROOT / "public" / "build.json").read_text(encoding="utf-8"))
        cls.h = cls.today["health"]

    @staticmethod
    def t(s):
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")

    def test_times_valid_and_ordered(self):
        self.assertGreater(self.t(self.h["stale_after"]), self.t(self.h["built_at"]))

    def test_last_export_date_is_latest_day_with_records(self):
        days = sorted(p.stem[len("day-"):] for p in (ROOT / "data" / "public").glob("*/day-*.json"))
        self.assertEqual(self.h["last_export_date"], days[-1])

    def test_fixture_days_match_build_json(self):
        self.assertEqual(self.h["fixture_days"], self.bj["fixture_days"])


if __name__ == "__main__":
    unittest.main()
