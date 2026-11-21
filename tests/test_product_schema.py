import sys, tempfile, unittest, shutil, json
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

ROOT = Path(__file__).resolve().parent.parent


class ProductSchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "static").mkdir()
        shutil.copy(ROOT / "static" / "style.css", self.root / "static" / "style.css")
        p = self.root / "data" / "p"
        p.mkdir(parents=True)
        (p / "product.json").write_text(json.dumps({"slug": "p", "name": "P", "site": "https://example.org"}), encoding="utf-8")
        (p / "day-2026-11-02.json").write_text(json.dumps({"tasks": [], "reviews": [], "posts": []}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        with mock.patch.object(build, "DATA_DIR", self.root / "data"), mock.patch.object(build, "PUBLIC_DIR", self.root / "public"), \
                mock.patch.object(build, "ROOT", self.root):
            model = build.load_data()
            model["built"] = "2026-11-20T08:00:00Z"
            model["errors"] = []
            build.write_site(model)
            return model

    def check(self, model):
        with mock.patch.object(build, "PUBLIC_DIR", self.root / "public"):
            return build.check_product_schema(model)

    def test_page_without_itemtype_is_reported(self):
        model = self.build()
        page = self.root / "public" / "product" / "p" / "index.html"
        page.write_text(page.read_text(encoding="utf-8").replace("https://schema.org/CollectionPage", "https://schema.org/WebPage"), encoding="utf-8")
        self.assertEqual(self.check(model), {"missing": ["p"]})

    def test_full_build_has_no_missing(self):
        self.assertEqual(self.check(self.build()), {"missing": []})


if __name__ == "__main__":
    unittest.main()
