"""Run Python regression tests without creating desktop windows."""
from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "python/tests")]


def main():
    temporary_root = ROOT / ".test_tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="python-tests-", dir=temporary_root) as folder:
        os.environ["TEMP"] = os.environ["TMP"] = folder
        tempfile.tempdir = folder
        names = [p.stem for p in sorted((ROOT / "python/tests").glob("test_*.py"))
                 if p.stem != "test_gui"]
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
