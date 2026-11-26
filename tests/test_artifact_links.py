import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

PR = "https://github.com/OOuph/agent-team/pull/289"
DAY = {"date": "2026-11-20", "posts": [], "tasks": [{
    "id": "T-1", "title": "t", "state": "accepted",
    "history": [{"to": "accepted", "note": f"merged {PR}", "at": "2026-11-20T01:00:00+00:00"}]}]}


def write_day(root: Path, with_sub: bool, link_on_main: bool) -> None:
    card = "\n".join(build.tasks_block(DAY, "p", DAY["tasks"], None))
    body = '<p id="artifact-line">Accepted with an artifact link: 1 of 1</p>'
    d = root / "day" / "2026-11-20"
    d.mkdir(parents=True)
    (d / "index.html").write_text(body + (card if link_on_main else ""), encoding="utf-8")
    (d / "index.json").write_text(json.dumps({"products": {"p": build.with_artifacts(DAY)}}), encoding="utf-8")
    if with_sub:
        (d / "p").mkdir()
        (d / "p" / "index.html").write_text(card, encoding="utf-8")


class ArtifactLinksTest(unittest.TestCase):
    def run_check(self, **kw):
        old = build.PUBLIC_DIR
        with tempfile.TemporaryDirectory() as tmp:
            build.PUBLIC_DIR = Path(tmp)
            try:
                write_day(Path(tmp), **kw)
                return build.check_artifacts()["mismatches"]
            finally:
                build.PUBLIC_DIR = old

    def linked(self, msgs):
        return [m for m in msgs if "not linked" in m["issue"]]

    def test_card_has_anchor(self):
        card = "\n".join(build.tasks_block(DAY, "p", DAY["tasks"], None))
        self.assertIn(f'<a href="{PR}"', card)

    def test_link_on_day_page(self):
        self.assertEqual(self.linked(self.run_check(with_sub=False, link_on_main=True)), [])

    def test_link_on_split_subpage(self):
        self.assertEqual(self.linked(self.run_check(with_sub=True, link_on_main=False)), [])

    def test_missing_link_still_reported(self):
        self.assertEqual(len(self.linked(self.run_check(with_sub=False, link_on_main=False))), 1)


if __name__ == "__main__":
    unittest.main()
