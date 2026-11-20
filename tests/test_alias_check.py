import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


def write(root, day, esc_total, count):
    d = root / "day" / day
    d.mkdir(parents=True)
    items = [{"id": f"T-{i}"} for i in range(esc_total)]
    (d / "index.json").write_text(json.dumps({
        "escaped": {"total": esc_total, "items": items},
        "escaped_after_accept": {"count": count, "tasks": [f"T-{i}" for i in range(count)]}}))


class AliasCheckTest(unittest.TestCase):
    def test_differing_day_reported(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            write(root, "2026-11-01", 1, 1)
            write(root, "2026-11-02", 2, 1)
            with mock.patch.object(build, "PUBLIC_DIR", root):
                m = build.check_alias()["mismatches"]
            self.assertEqual([x["day"] for x in m], ["2026-11-02"])

    def test_full_build_empty(self):
        bj = json.loads((Path(build.PUBLIC_DIR) / "build.json").read_text())
        self.assertEqual(bj["alias_check"]["mismatches"], [])
        self.assertEqual(build.check_alias()["mismatches"], [])
