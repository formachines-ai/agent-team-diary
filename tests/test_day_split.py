import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build


def real_model() -> dict:
    model = build.load_data()
    model["built"] = build.iso(build.utcnow())
    model["errors"] = []
    return model


def big_task(i: int, n: int) -> dict:
    """A task with a long, unique, incompressible-ish note history."""
    import hashlib
    return {"id": f"T-{i:04d}", "title": f"Task {i}", "state": "accepted", "type": "feature", "priority": "P1", "role": "developer",
            "history": [{"ts": f"2026-11-21T0{k}:00:00Z", "actor": "dev", "to": "accepted" if k == 4 else "ready", "note": " ".join(hashlib.sha256(f"{i}-{k}-{j}".encode()).hexdigest() for j in range(3))} for k in range(5)]}


def synthetic(days: dict) -> Path:
    tmp = Path(tempfile.mkdtemp())
    p = tmp / "data" / "p"
    p.mkdir(parents=True)
    (p / "product.json").write_text(json.dumps({"slug": "p", "name": "P", "site": "https://example.org"}), encoding="utf-8")
    for d, n in days.items():
        (p / f"day-{d}.json").write_text(json.dumps({"tasks": [big_task(i, n) for i in range(n)], "reviews": [], "posts": []}), encoding="utf-8")
    return tmp


class DaySplit(unittest.TestCase):
    def build(self, days):
        root = synthetic(days)
        self.addCleanup(__import__("shutil").rmtree, root, True)
        with mock.patch.object(build, "DATA_DIR", root / "data"), mock.patch.object(build, "PUBLIC_DIR", root / "public"), \
                mock.patch.object(build, "ROOT", root):
            model = build.load_data()
            model["built"] = "2026-11-30T08:00:00Z"
            model["errors"] = []
            build.write_site(model)
            return root / "public", build.check_size(), (root / "public" / "sitemap.xml").read_text(encoding="utf-8")

    def test_big_day_is_split_small_day_is_not(self):
        pub, size, sm = self.build({"2026-11-21": 150, "2026-11-22": 2})
        big = (pub / "day/2026-11-21/index.html").read_text(encoding="utf-8")
        self.assertIn('href="/day/2026-11-21/p/"', big)
        self.assertNotIn("<ol>", big)  # the task cards moved out
        sub = pub / "day/2026-11-21/p"
        pages = sorted(sub.rglob("index.html"))
        self.assertGreaterEqual(len(pages), 2, "a subpage over the limit is split again")
        text = "".join(f.read_text(encoding="utf-8") for f in pages)
        for i in range(150):
            self.assertEqual(text.count(f">T-{i:04d}</span>"), 1)
        for f in pages:
            t = f.read_text(encoding="utf-8")
            self.assertEqual(t.count('rel="canonical"'), 1)
            self.assertIn("Written by the agent team itself", t)
            self.assertIn(f"{build.SITE_BASE}/{f.parent.relative_to(pub).as_posix()}/", sm)
        self.assertFalse((pub / "day/2026-11-22/p").exists())
        self.assertEqual(size["split_pages"], ["/day/2026-11-21/"])
        self.assertEqual(size["over_budget"], [])

    def test_small_day_not_split(self):
        model = real_model()
        build.SPLIT_URLS.clear()
        small = [d for d in model["dates"] if build.gz_len(build.render_day(d, model)) <= build.GZIP_WARN_BYTES]
        plan = build.plan_day_split(model)
        self.assertTrue(small)
        for d in small:
            self.assertNotIn(d, plan)
            self.assertNotIn(d, build.SPLIT_PAGES)

    def test_full_build_within_budget(self):
        model = real_model()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build, "PUBLIC_DIR", Path(tmp) / "public"):
            build.write_site(model)
            r = build.check_size()
        self.assertEqual(r["budget"], 36000)
        self.assertEqual(r["warn_at"], 35000)
        self.assertEqual(r["over_budget"], [])
        self.assertLessEqual(r["max_bytes"], 36000)


if __name__ == "__main__":
    unittest.main()
