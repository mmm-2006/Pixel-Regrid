from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch
import logging
import logging.handlers

import pixel_paths


class ResourcePathsTests(unittest.TestCase):
    def test_original_launch_entry_reaches_python_desktop_without_opening_window(self):
        import pixel_desktop
        root = Path(__file__).resolve().parents[2]
        with patch.object(sys, "argv", [str(root / "launch.py")]), \
                patch.object(pixel_desktop, "run") as desktop_run, \
                patch.object(logging.handlers, "RotatingFileHandler", return_value=logging.NullHandler()), \
                self.assertRaises(SystemExit) as exited:
            runpy.run_path(str(root / "launch.py"), run_name="__main__")
        self.assertEqual(exited.exception.code, 0)
        desktop_run.assert_called_once_with()

    def test_original_legacy_flag_reaches_retained_tkinter_entry_without_opening_window(self):
        import perfect_pixel_gui
        root = Path(__file__).resolve().parents[2]
        with patch.object(sys, "argv", [str(root / "launch.py"), "--legacy"]), \
                patch.object(perfect_pixel_gui, "App") as legacy_app, \
                patch.object(logging.handlers, "RotatingFileHandler", return_value=logging.NullHandler()), \
                self.assertRaises(SystemExit) as exited:
            runpy.run_path(str(root / "launch.py"), run_name="__main__")
        self.assertEqual(exited.exception.code, 0)
        legacy_app.return_value.mainloop.assert_called_once_with()

    def test_source_uses_shared_frontend_and_existing_root_settings(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(pixel_paths.APP_HOME, root)
        self.assertEqual(pixel_paths.RESOURCE_ROOT, root)
        self.assertTrue((pixel_paths.RESOURCE_ROOT / "frontend/index.html").is_file())

    def test_frozen_resources_and_writable_settings_have_separate_locations(self):
        root = Path(__file__).resolve().parents[2]
        executable = root / "dist/PerfectPixel/PerfectPixel.exe"
        resources = executable.parent / "_internal"
        with patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "_MEIPASS", str(resources), create=True), \
                patch.object(sys, "executable", str(executable)):
            paths = runpy.run_path(pixel_paths.__file__)
        self.assertEqual(paths["APP_HOME"], executable.parent.resolve())
        self.assertEqual(paths["RESOURCE_ROOT"], resources)
