import base64
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import pixel_desktop as desktop
from pixel_core import process_file, read_image


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.api = desktop.DesktopApi(self.root / "settings.json")
        self.image = np.zeros((24, 24, 4), np.uint8)
        self.image[4:20, 8:16] = [30, 70, 150, 255]
        self.image[3, 7] = [0, 0, 0, 1]
        self.path = self.root / "像素图.png"
        cv2.imencode(".png", self.image)[1].tofile(self.path)
        self.api._append([self.path])
        self.key = desktop.path_key(self.path)
        self.options = dict(desktop.DEFAULTS, direct=True, layout="fit", width=16, height=16)

    def tearDown(self):
        if self.api._worker:
            self.api._cancel.set()
            self.api._worker.join(5)
        self.temp.cleanup()

    def test_migrate_old_and_reload_web_settings(self):
        old = dict(mode="指定尺寸", width=40, height=48, method="多数色 · 较慢")
        migrated = desktop.migrate_settings(old)
        self.assertEqual((migrated["width"], migrated["height"]), (40, 48))
        self.assertEqual(migrated["layout"], "canvas_fit")
        self.assertEqual(migrated["method"], "majority")
        self.assertFalse(migrated["direct"])
        self.assertTrue(self.api.configure(self.options)["ok"])
        loaded = desktop.DesktopApi(self.root / "settings.json")
        self.assertEqual(loaded.bootstrap()["options"], self.options)
        self.assertEqual(desktop.migrate_settings({"web_options": {"width": "bad"}}), desktop.DEFAULTS)

    def test_strict_parameters_and_inline_error(self):
        for invalid in (dict(width=""), dict(width=1.5), dict(width=True), dict(detail=3),
                        dict(alpha_threshold=255), dict(layout="unknown"), dict(direct="false")):
            self.assertFalse(self.api.configure(self.options | invalid)["ok"])
        self.assertTrue(self.api.configure(self.options | dict(layout="keep", width=2048))["ok"])
        self.assertFalse(self.api.configure(self.options | dict(width=2048))["ok"])

    def test_preview_retains_alpha_and_exactly_matches_export(self):
        for layout in ("original", "keep", "fit", "canvas_fit", "stretch"):
            for method in ("nearest", "pixel", "k-centroid"):
                with self.subTest(layout=layout, resample=method):
                    data = self.options | dict(layout=layout, width=24, height=24, resample=method)
                    preview = self.api.preview(self.key, data)
                    self.assertTrue(preview["ok"])
                    self.assertIsNone(preview["error"])
                    blob = base64.b64decode(preview["output"]["src"].split(",", 1)[1])
                    image = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_UNCHANGED)
                    options, _ = desktop.parse_options(data)
                    result = process_file(self.path, options)
                    np.testing.assert_array_equal(image, read_image(result.output))
                    self.assertEqual(preview["info"]["subject"], (8, 16))
                    self.assertEqual(image.shape[2], 4)

    def test_preview_reuses_preparation_and_invalid_layout_keeps_original(self):
        with patch.object(desktop, "prepare_image", wraps=desktop.prepare_image) as prepare:
            self.api.preview(self.key, self.options)
            self.api.preview(self.key, self.options | dict(width=32, resample="k-centroid"))
            self.assertEqual(prepare.call_count, 1)
        invalid = self.api.preview(self.key, self.options | dict(layout="keep", width=2, height=2))
        self.assertTrue(invalid["ok"])
        self.assertIsNotNone(invalid["original"])
        self.assertIsNone(invalid["output"])
        self.assertIn("画布至少", invalid["error"])
        self.assertEqual(invalid["info"]["subject"], (8, 16))

    def test_batch_continues_on_error_and_reserves_unique_output_names(self):
        bad = self.root / "损坏.png"
        bad.write_bytes(b"bad")
        self.api._append([bad, self.path])
        bad_key = desktop.path_key(bad)
        keys = [bad_key, self.key]
        with self.assertLogs(level="ERROR"):
            result = self.api.start_export(keys, self.options)
            self.assertTrue(result["ok"])
            self.api._worker.join(5)
        state = self.api.get_state()
        self.assertFalse(state["busy"])
        self.assertEqual([file["status"] for file in state["files"]], ["success", "error"])
        self.assertEqual(state["progress"], dict(done=2, total=2))
        first = Path(state["files"][0]["output"])
        self.api.start_export([self.key], self.options)
        self.api._worker.join(5)
        second = Path(self.api.get_state()["files"][0]["output"])
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertNotEqual(first, second)

    def test_cancel_and_close_wait_for_current_save(self):
        second = self.root / "second.png"
        cv2.imencode(".png", self.image)[1].tofile(second)
        self.api._append([second])
        entered, release = threading.Event(), threading.Event()
        def blocked(path, options):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test worker timeout")
            return process_file(path, options)
        with patch.object(desktop, "process_file", side_effect=blocked):
            self.api.start_export([self.key, desktop.path_key(second)], self.options)
            self.assertTrue(entered.wait(3))
            self.assertFalse(self.api.configure(self.options)["ok"])
            self.assertFalse(self.api.remove_files([self.key])["ok"])
            self.assertFalse(self.api.start_export([self.key], self.options)["ok"])
            self.assertFalse(self.api._on_closing())
            release.set()
            self.api._worker.join(5)
        state = self.api.get_state()
        self.assertEqual([file["status"] for file in state["files"]], ["success", "cancelled"])
        self.assertTrue(Path(state["files"][0]["output"]).is_file())

    def test_only_imported_files_can_be_read_or_exported(self):
        self.assertFalse(self.api.preview(str(self.root / "secret.png"), self.options)["ok"])
        self.assertFalse(self.api.thumbnail(str(self.root / "secret.png"))["ok"])
        self.assertFalse(self.api.start_export([str(self.root / "secret.png")], self.options)["ok"])
        revision = self.api.get_state()["revision"]
        self.assertEqual(self.api.get_state(revision), dict(ok=True, unchanged=True))

    def test_scan_skips_output_folders_and_handles_cancellation(self):
        output = self.root / "perfect_pixel_output"
        output.mkdir()
        cv2.imencode(".png", self.image)[1].tofile(output / "output.png")
        self.api._start_scan(self.root)
        self.api._worker.join(5)
        self.assertEqual(len(self.api.get_state()["files"]), 1)
        self.assertFalse(self.api.get_state()["busy"])

    def test_new_preview_cancels_obsolete_work(self):
        entered, release = threading.Event(), threading.Event()
        responses = []
        original = self.api._renderer.render
        def blocked(path, options, cancel):
            entered.set()
            release.wait(3)
            return original(path, options, cancel)
        with patch.object(self.api._renderer, "render", side_effect=blocked):
            worker = threading.Thread(target=lambda: responses.append(self.api.preview(self.key, self.options)))
            worker.start()
            self.assertTrue(entered.wait(2))
            self.api.cancel_preview()
            release.set()
            worker.join(5)
        self.assertEqual(responses, [dict(ok=False, cancelled=True)])
        self.assertTrue(self.api.preview(self.key, self.options)["ok"])


if __name__ == "__main__":
    unittest.main()
