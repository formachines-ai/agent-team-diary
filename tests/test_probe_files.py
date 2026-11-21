import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


class ProbeFilesTest(unittest.TestCase):
    def run_check(self, remove=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for n in build.PROBE_FILES:
                (root / n).write_bytes(b"x")
            if remove:
                (root / remove).unlink()
            with mock.patch.object(build, "PUBLIC_DIR", root):
                return build.check_probe_files()["missing"]

    def test_removed_file_reported(self):
        self.assertEqual(self.run_check("favicon.ico"), ["favicon.ico"])

    def test_full_build_empty(self):
        self.assertEqual(self.run_check(), [])


if __name__ == "__main__":
    unittest.main()
