from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import perfect_pixel_gui as gui
from pixel_core import process_file, path_key


class GuiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.settings_patch = patch.object(gui, "SETTINGS", self.root / "settings.json")
        self.settings_patch.start()
        self.app = gui.App()
        self.app.withdraw()
        self.app.update()
        self.app.set_size(4)
        self.app.scale.set("不导出")

    def tearDown(self):
        if self.app.worker and self.app.worker.is_alive():
            self.app.cancel_event.set()
            self.app.worker.join(timeout=5)
        try:
            self.app.destroy()
        except gui.tk.TclError:
            pass
        self.app.preview_pool.shutdown(wait=True, cancel_futures=True)
        self.settings_patch.stop()
        self.temp.cleanup()

    def image(self, name):
        path = self.root / name
        ok, encoded = cv2.imencode(".png", np.full((16, 16, 4), [10, 40, 90, 128], np.uint8))
        self.assertTrue(ok)
        encoded.tofile(path)
        return path

    def pump_until(self, predicate):
        deadline = time.monotonic() + 8
        while not predicate() and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.01)
        self.assertTrue(predicate(), "GUI did not complete within 8 seconds")

    def test_batch_continues_after_corrupt_file_and_preview_loads(self):
        good = self.image("透明.png")
        bad = self.root / "损坏.png"
        bad.write_bytes(b"broken")
        self.app.append_files([bad, good, good])
        self.assertEqual(len(self.app.files), 2)
        self.app.start()
        self.assertTrue(all(str(widget.cget("state")) == "disabled" for widget, _ in self.app.controls))
        self.pump_until(lambda: not self.app.busy)
        self.assertEqual(self.app.tree.item(path_key(bad))["values"][1], "失败")
        self.assertEqual(self.app.tree.item(path_key(good))["values"][2], "4×4")
        self.app.tree.selection_set(path_key(good))
        self.app.show_selection()
        self.pump_until(lambda: len(self.app.photos) == 2)
        self.assertIn("4 × 4", self.app.output_caption.cget("text"))

    def test_cancel_finishes_current_image_and_marks_remaining(self):
        files = [self.image(f"{n}.png") for n in range(3)]
        self.app.append_files(files)
        entered, release = threading.Event(), threading.Event()
        def delayed(path, options):
            entered.set()
            self.assertTrue(release.wait(5))
            return process_file(path, options)
        with patch.object(gui, "process_file", side_effect=delayed):
            self.app.start()
            self.assertTrue(entered.wait(5))
            self.app.cancel()
            release.set()
            self.pump_until(lambda: not self.app.busy)
        self.assertEqual(self.app.tree.item(path_key(files[0]))["values"][1], "成功")
        self.assertEqual(self.app.tree.item(path_key(files[1]))["values"][1], "已取消")
        self.assertIn("未处理 2 张", self.app.status.cget("text"))

    def test_close_waits_for_current_save_without_tk_calls_from_worker(self):
        path = self.image("关闭.png")
        self.app.append_files([path])
        entered, release = threading.Event(), threading.Event()
        saved = []
        def delayed(source, options):
            entered.set()
            self.assertTrue(release.wait(5))
            result = process_file(source, options)
            saved.append(result.output)
            return result
        with patch.object(gui, "process_file", side_effect=delayed):
            self.app.start()
            self.assertTrue(entered.wait(5))
            self.app.close()
            self.assertTrue(self.app.winfo_exists())
            self.assertTrue(self.app.cancel_event.is_set())
            release.set()
            self.app.worker.join(timeout=5)
            self.app.poll()
        self.assertTrue(saved[0].is_file())
        with self.assertRaises(gui.tk.TclError):
            self.app.winfo_exists()

    def test_settings_reload_and_invalid_json(self):
        self.app.method.set("中位数 · 去噪")
        self.app.set_size(64)
        self.app.scale.set("4 倍")
        self.app.layout.set("主体不缩放 · 改画布")
        self.app.canvas_width.set("42")
        self.app.canvas_height.set("40")
        self.app.resample.set("平滑缩小 · 面积平均")
        self.app.palette.set("16 色")
        self.app.detail.set("较强")
        self.app.save_settings()
        settings = gui.load_settings()
        self.assertEqual(settings["width"], 64)
        self.assertEqual(settings["method"], "中位数 · 去噪")
        self.assertEqual(settings["layout"], "主体不缩放 · 改画布")
        self.assertEqual((settings["canvas_width"], settings["canvas_height"]), (42, 40))
        self.assertEqual(settings["resample"], "平滑缩小 · 面积平均")
        self.assertEqual((settings["palette"], settings["detail"]), ("16 色", "较强"))
        gui.SETTINGS.write_text("broken json", encoding="utf-8")
        self.assertEqual(gui.load_settings(), {})

    def test_live_preview_before_save_and_updates_from_parameter_traces(self):
        path = self.image("实时.png")
        original = path.read_bytes()
        self.app.append_files([path])
        self.pump_until(lambda: "4 × 4" in self.app.output_caption.cget("text"))
        self.assertEqual(len(self.app.photos), 2)
        self.assertFalse((self.root / "perfect_pixel_output").exists())
        self.app.set_size(8)
        self.app.method.set("中位数 · 去噪")
        self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
        self.assertIn(("median", (8, 8), False, False), self.app.preview_renderer.outputs)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / "perfect_pixel_output").exists())

    def test_invalid_live_size_is_inline_and_recovers(self):
        path = self.image("参数.png")
        self.app.append_files([path])
        self.app.width.set("")
        with patch.object(gui.messagebox, "showerror") as popup:
            self.pump_until(lambda: "参数有误" in self.app.output_view.cget("text"))
            self.assertFalse(popup.called)
        self.app.width.set("8")
        self.pump_until(lambda: "8 × 4" in self.app.output_caption.cget("text"))

    def test_rapid_changes_compute_only_final_options_and_ignore_stale_events(self):
        path = self.image("连续.png")
        with patch.object(gui, "prepare_image", wraps=gui.prepare_image) as compute:
            self.app.append_files([path])
            for size in (3, 6, 8):
                self.app.set_size(size)
            self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
            self.assertEqual(compute.call_count, 1)
        caption = self.app.output_caption.cget("text")
        self.app.handle_event(("preview", self.app.preview_token - 1, "old", "old", "old"))
        self.assertEqual(self.app.output_caption.cget("text"), caption)
        self.assertNotEqual(self.app.output_view.cget("text"), "old")

    def test_cancel_pending_preview_when_clearing_list(self):
        path = self.image("清空.png")
        self.app.append_files([path])
        self.app.show_selection()
        self.app.clear()
        self.assertIsNone(self.app.preview_after_id)
        self.assertEqual(self.app.output_view.cget("text"), "选择图片后自动预览")

    def test_k_centroid_selection_settings_preview_and_export(self):
        path = self.image("k-centroid.png")
        self.app.append_files([path])
        self.app.mode.set("原图直接转换")
        self.app.layout.set("主体等比例缩放 · 改画布")
        self.app.set_canvas_size(8)
        label = "k-centroid · 局部主色"
        self.app.resample.set(label)
        self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
        self.assertEqual(self.app.get_options().resample, "k-centroid")
        self.assertEqual(str(self.app.resample_input.cget("state")), "readonly")
        self.assertEqual(str(self.app.palette_input.cget("state")), "disabled")
        self.assertEqual(str(self.app.detail_input.cget("state")), "disabled")
        self.app.save_settings()
        self.assertEqual(gui.load_settings()["resample"], label)
        live = gui.image_thumbnail(gui.layout_image(gui.read_image(path), self.app.get_options()))
        self.app.start()
        self.pump_until(lambda: not self.app.busy)
        result = self.app.results[path_key(path)]
        self.assertEqual((result.width, result.height), (8, 8))
        self.assertEqual(gui.thumbnail(result.output), live)
        self.app.resample.set("目标像素 · 结构保护")
        self.app.update_grid_state()
        self.assertEqual(str(self.app.palette_input.cget("state")), "readonly")

    def test_subject_canvas_controls_minimum_and_inline_error_recovery(self):
        path = self.root / "主体.png"
        image = np.zeros((16, 16, 4), np.uint8)
        image[3:13, 5:11] = [10, 40, 90, 255]
        cv2.imencode(".png", image)[1].tofile(path)
        self.app.set_size(16)
        self.app.append_files([path])
        self.pump_until(lambda: self.app.current_info is not None)
        self.assertIn("主体 6×10", self.app.subject_caption.cget("text"))
        self.app.use_subject_canvas()
        self.pump_until(lambda: "6 × 10" in self.app.output_caption.cget("text"))
        self.assertEqual(self.app.get_options().canvas, (6, 10))
        self.app.canvas_height.set("9")
        self.pump_until(lambda: "至少为 6×10" in self.app.output_view.cget("text"))
        self.assertIn("主体 6×10", self.app.subject_caption.cget("text"))
        self.assertEqual(str(self.app.subject_canvas_button.cget("state")), "normal")
        self.app.use_grid_canvas()
        self.pump_until(lambda: "16 × 16" in self.app.output_caption.cget("text"))
        self.assertEqual(self.app.get_options().canvas, (16, 16))
        self.app.layout.set("只裁透明边 · 最小画布")
        self.pump_until(lambda: "6 × 10" in self.app.output_caption.cget("text"))
        self.app.layout.set("主体等比例缩放 · 改画布")
        self.app.set_canvas_size(8)
        self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
        self.assertEqual(self.app.get_options().resample, "pixel")
        self.assertEqual(str(self.app.resample_input.cget("state")), "readonly")
        self.app.resample.set("平滑缩小 · 面积平均")
        self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
        self.assertEqual(self.app.get_options().resample, "area")
        self.app.start()
        self.assertEqual(str(self.app.subject_canvas_button.cget("state")), "disabled")
        self.pump_until(lambda: not self.app.busy)
        result = self.app.results[path_key(path)]
        self.assertEqual((result.width, result.height), (8, 8))
        self.assertEqual(result.info.subject, (6, 10))

    def test_full_canvas_fit_controls_preview_export_and_saved_setting(self):
        path = self.root / "整图.png"
        image = np.zeros((12, 8, 4), np.uint8)
        image[2:6, 2:4] = [10, 40, 200, 255]
        cv2.imencode(".png", image)[1].tofile(path)
        original = path.read_bytes()
        self.app.append_files([path])
        self.app.mode.set("原图直接转换")
        label = "整图等比例缩放 · 保留原留白"
        self.app.layout.set(label)
        self.app.canvas_width.set("10")
        self.app.canvas_height.set("6")
        self.pump_until(lambda: "10 × 6" in self.app.output_caption.cget("text"))
        options = self.app.get_options()
        self.assertEqual((options.layout, options.canvas, options.resample),
                         ("canvas_fit", (10, 6), "pixel"))
        for widget in (self.app.canvas_width_input, self.app.canvas_height_input):
            self.assertEqual(str(widget.cget("state")), "normal")
        for widget in (self.app.resample_input, self.app.palette_input, self.app.detail_input):
            self.assertEqual(str(widget.cget("state")), "readonly")
        self.app.use_grid_canvas()
        self.assertEqual(self.app.layout.get(), label)
        self.assertEqual(self.app.get_options().canvas, (8, 12))
        self.app.canvas_width.set("10")
        self.app.canvas_height.set("6")
        self.app.resample.set("像素硬边 · 最近邻")
        self.app.save_settings()
        self.assertEqual(gui.load_settings()["layout"], label)
        self.app.start()
        self.pump_until(lambda: not self.app.busy)
        result = self.app.results[path_key(path)]
        output = gui.read_image(result.output)
        self.assertEqual(output.shape, (6, 10, 4))
        expected = np.zeros((6, 10, 4), np.uint8)
        expected[1:3, 4:5] = [10, 40, 200, 255]
        np.testing.assert_array_equal(output, expected)
        self.assertEqual(path.read_bytes(), original)

    def test_target_pixel_controls_and_block_direct_conversion(self):
        path = self.image("方块.png")
        self.app.append_files([path])
        self.app.layout.set("方块铺满 · 改尺寸")
        self.app.set_canvas_size(8)
        self.app.palette.set("8 色")
        self.app.detail.set("较强")
        self.app.mode.set("原图直接转换")
        self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
        options = self.app.get_options()
        self.assertEqual((options.layout, options.direct, options.palette_size, options.detail),
                         ("stretch", True, 8, 2))
        self.assertEqual(str(self.app.palette_input.cget("state")), "readonly")
        self.assertIn("原图 16×16", self.app.subject_caption.cget("text"))
        self.app.start()
        self.pump_until(lambda: not self.app.busy)
        result = self.app.results[path_key(path)]
        self.assertEqual((result.width, result.height), (8, 8))
        self.assertEqual(result.info.recovery, "direct")


class PreviewRendererTests(unittest.TestCase):
    def test_cache_reuse_and_live_matches_export_for_all_methods(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.png"
            rng = np.random.default_rng(42)
            image = rng.integers(0, 256, (64, 64, 4), dtype=np.uint8)
            cv2.imencode(".png", image)[1].tofile(path)
            renderer = gui.PreviewRenderer()
            cancel = threading.Event()
            with patch.object(gui, "read_image", wraps=gui.read_image) as read:
                with patch.object(gui, "prepare_image", wraps=gui.prepare_image) as compute:
                    for method in ("center", "median", "majority"):
                        options = gui.Options(method=method, grid=(4, 4), preview_scale=0)
                        _, preview, info = renderer.render(path, options, 80, 80, cancel)
                        saved = process_file(path, options)
                        self.assertEqual(preview, gui.thumbnail(saved.output, 80, 80))
                    calls = compute.call_count
                    renderer.render(path, options, 160, 160, cancel)
                    self.assertEqual(compute.call_count, calls)
                self.assertEqual(read.call_count, 4)  # One source decode + three exported thumbnails.
            cv2.imencode(".png", np.zeros((16, 16, 4), np.uint8))[1].tofile(path)
            original, _, info = renderer.render(path, options, 80, 80, cancel)
            self.assertEqual(original[1], "16 × 16")
            self.assertEqual(len(renderer.outputs), 1)

    def test_layout_change_reuses_grid_and_matches_export(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.png"
            image = np.zeros((16, 16, 4), np.uint8)
            image[3:13, 5:11] = [10, 40, 90, 255]
            cv2.imencode(".png", image)[1].tofile(path)
            renderer = gui.PreviewRenderer()
            with patch.object(gui, "prepare_image", wraps=gui.prepare_image) as compute:
                for layout, canvas, resample in (("original", None, "nearest"), ("crop", None, "nearest"),
                                       ("keep", (12, 14), "nearest"), ("fit", (8, 8), "nearest"),
                                       ("fit", (8, 8), "area"), ("fit", (8, 8), "pixel"),
                                       ("canvas_fit", (12, 8), "nearest"),
                                       ("canvas_fit", (8, 12), "area"),
                                       ("canvas_fit", (12, 8), "pixel"),
                                       ("stretch", (8, 8), "pixel"),
                                       ("fit", (8, 8), "k-centroid"),
                                       ("canvas_fit", (12, 8), "k-centroid"),
                                       ("stretch", (8, 12), "k-centroid")):
                    options = gui.Options(grid=(16, 16), layout=layout, canvas=canvas,
                                          resample=resample, preview_scale=0)
                    _, preview, info = renderer.render(path, options, 80, 80, threading.Event())
                    self.assertEqual(info.subject, (6, 10))
                    result = process_file(path, options)
                    self.assertEqual(preview, gui.thumbnail(result.output, 80, 80))
                self.assertEqual(compute.call_count, 2)

    def test_cancelled_preview_does_not_read_source(self):
        renderer = gui.PreviewRenderer()
        cancel = threading.Event()
        cancel.set()
        with patch.object(gui, "read_image") as read:
            self.assertIsNone(renderer.render(Path("missing.png"), gui.Options(), 80, 80, cancel))
            self.assertFalse(read.called)


if __name__ == "__main__":
    unittest.main()
