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
        self.app.mode.set("原图直接转换")
        self.app.set_canvas_size(4)

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
        self.app.set_canvas_size(64)
        self.app.layout.set("主体不缩放 · 改画布")
        self.app.canvas_width.set("42")
        self.app.canvas_height.set("40")
        self.app.resample.set("像素硬边 · 最近邻")
        self.app.palette.set("16 色")
        self.app.detail.set("较强")
        self.app.save_settings()
        settings = gui.load_settings()
        self.assertNotIn("width", settings)
        self.assertNotIn("height", settings)
        self.assertNotIn("scale", settings)
        self.assertEqual(settings["method"], "中位数 · 去噪")
        self.assertEqual(settings["layout"], "主体不缩放 · 改画布")
        self.assertEqual((settings["canvas_width"], settings["canvas_height"]), (42, 40))
        self.assertEqual(settings["resample"], "像素硬边 · 最近邻")
        self.assertEqual((settings["palette"], settings["detail"]), ("16 色", "较强"))
        # A saved selection of the removed mode must recover on startup.
        gui.SETTINGS.write_text(gui.json.dumps({**settings, "resample": "平滑缩小 · 面积平均",
                                               "scale": "16 倍", "layout": "只裁透明边 · 最小画布"}),
                                encoding="utf-8")
        migrated = gui.App()
        try:
            migrated.withdraw()
            self.assertEqual(migrated.resample.get(), "目标像素 · 结构保护")
            self.assertNotIn("平滑缩小 · 面积平均", migrated.resample_input.cget("values"))
            self.assertNotIn("只裁透明边 · 最小画布", gui.LAYOUTS)
            self.assertEqual(migrated.layout.get(), "保持原画布")
            self.assertFalse(hasattr(migrated, "scale"))
            migrated.save_settings()
            self.assertNotIn("scale", gui.load_settings())
            self.assertEqual(gui.load_settings()["layout"], "保持原画布")
        finally:
            migrated.destroy()
            migrated.preview_pool.shutdown(wait=True, cancel_futures=True)
        gui.SETTINGS.write_text("broken json", encoding="utf-8")
        self.assertEqual(gui.load_settings(), {})

    def test_live_preview_before_save_and_updates_from_parameter_traces(self):
        path = self.image("实时.png")
        original = path.read_bytes()
        self.app.append_files([path])
        self.pump_until(lambda: "4 × 4" in self.app.output_caption.cget("text"))
        self.assertEqual(len(self.app.photos), 2)
        self.assertFalse((self.root / "perfect_pixel_output").exists())
        self.app.set_canvas_size(8)
        self.app.method.set("中位数 · 去噪")
        self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
        self.assertIn(("median", None, True, True), self.app.preview_renderer.outputs)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / "perfect_pixel_output").exists())

    def test_invalid_live_size_is_inline_and_recovers(self):
        path = self.image("参数.png")
        self.app.append_files([path])
        self.app.canvas_width.set("")
        with patch.object(gui.messagebox, "showerror") as popup:
            self.pump_until(lambda: "参数有误" in self.app.output_view.cget("text"))
            self.assertFalse(popup.called)
        self.app.canvas_width.set("8")
        self.pump_until(lambda: "8 × 4" in self.app.output_caption.cget("text"))

    def test_rapid_changes_compute_only_final_options_and_ignore_stale_events(self):
        path = self.image("连续.png")
        with patch.object(gui, "prepare_image", wraps=gui.prepare_image) as compute:
            self.app.append_files([path])
            for size in (3, 6, 8):
                self.app.set_canvas_size(size)
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
        self.assertEqual(list(result.output.parent.iterdir()), [result.output])
        self.app.resample.set("目标像素 · 结构保护")
        self.app.update_grid_state()
        self.assertEqual(str(self.app.palette_input.cget("state")), "readonly")

    def test_subject_canvas_controls_minimum_and_inline_error_recovery(self):
        path = self.root / "主体.png"
        image = np.zeros((16, 16, 4), np.uint8)
        image[3:13, 5:11] = [10, 40, 90, 255]
        cv2.imencode(".png", image)[1].tofile(path)
        self.app.set_canvas_size(16)
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
        self.app.use_subject_canvas()
        self.pump_until(lambda: "6 × 10" in self.app.output_caption.cget("text"))
        self.app.layout.set("主体等比例缩放 · 改画布")
        self.app.set_canvas_size(8)
        self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
        self.assertEqual(self.app.get_options().resample, "pixel")
        self.assertEqual(str(self.app.resample_input.cget("state")), "readonly")
        self.app.resample.set("像素硬边 · 最近邻")
        self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
        self.assertEqual(self.app.get_options().resample, "nearest")
        self.app.start()
        self.assertEqual(str(self.app.subject_canvas_button.cget("state")), "disabled")
        self.pump_until(lambda: not self.app.busy)
        result = self.app.results[path_key(path)]
        self.assertEqual((result.width, result.height), (8, 8))
        self.assertEqual(result.info.subject, (6, 10))

    def test_direct_large_canvas_crop_input_size_and_settings_roundtrip(self):
        path = self.root / "大主体.png"
        image = np.zeros((1254, 1254, 4), np.uint8)
        image[100:1151, 300:907] = [10, 40, 90, 128]
        cv2.imencode(".png", image)[1].tofile(path)
        self.app.layout.set("保持原画布")
        self.app.append_files([path])
        self.pump_until(lambda: self.app.current_info is not None)
        self.app.use_subject_canvas()
        self.pump_until(lambda: "607 × 1051" in self.app.output_caption.cget("text"))
        self.assertEqual(self.app.get_options().canvas, (607, 1051))
        self.assertEqual(float(self.app.canvas_height_input.cget("to")), 8192)
        self.app.use_grid_canvas()
        self.pump_until(lambda: "1254 × 1254" in self.app.output_caption.cget("text"))
        self.app.save_settings()
        reopened = gui.App()
        try:
            reopened.withdraw()
            self.assertEqual(reopened.get_options().canvas, (1254, 1254))
            self.assertEqual(float(reopened.canvas_width_input.cget("to")), 8192)
            reopened.layout.set("主体等比例缩放 · 改画布")
            self.assertEqual(float(reopened.canvas_width_input.cget("to")), 1024)
            with self.assertRaisesRegex(ValueError, "1024"):
                reopened.get_options()
        finally:
            reopened.destroy()
            reopened.preview_pool.shutdown(wait=True, cancel_futures=True)

    def test_alpha_threshold_live_boundary_cache_crop_export_and_settings(self):
        path = self.root / "透明杂点.png"
        image = np.zeros((16, 16, 4), np.uint8)
        image[3:13, 5:11] = [10, 40, 90, 128]
        image[0, 0] = image[15, 15] = [20, 30, 40, 1]
        image[6, 7] = [50, 60, 70, 1]
        cv2.imencode(".png", image)[1].tofile(path)
        self.app.layout.set("保持原画布")
        with patch.object(gui, "prepare_image", wraps=gui.prepare_image) as compute:
            self.app.append_files([path])
            self.pump_until(lambda: self.app.current_info is not None)
            self.assertEqual(self.app.current_info.subject, (6, 10))
            self.app.alpha_threshold.set("0")
            self.pump_until(lambda: self.app.current_info is not None and self.app.current_info.subject == (16, 16))
            self.app.alpha_threshold.set("")
            self.pump_until(lambda: "透明噪点阈值" in self.app.output_view.cget("text"))
            self.app.alpha_threshold.set("1")
            self.pump_until(lambda: self.app.current_info is not None and self.app.current_info.subject == (6, 10))
            self.app.use_subject_canvas()
            self.pump_until(lambda: "6 × 10" in self.app.output_caption.cget("text"))
            self.assertEqual(compute.call_count, 1)
        self.app.alpha_threshold.set("16")
        self.app.save_settings()
        self.assertEqual(gui.load_settings()["alpha_threshold"], 16)
        reopened = gui.App()
        try:
            reopened.withdraw()
            self.assertEqual(reopened.get_options().alpha_threshold, 16)
        finally:
            reopened.destroy()
            reopened.preview_pool.shutdown(wait=True, cancel_futures=True)
        self.app.alpha_threshold.set("1")
        self.app.start()
        self.assertEqual(str(self.app.alpha_threshold_input.cget("state")), "disabled")
        self.pump_until(lambda: not self.app.busy)
        result = self.app.results[path_key(path)]
        np.testing.assert_array_equal(gui.read_image(result.output), image[3:13, 5:11])
        self.assertEqual(result.info.subject, (6, 10))

    def test_scale_notice_updates_for_subject_full_canvas_and_direct_input(self):
        import pixel_core as core
        path = self.root / "网格.png"
        image = np.zeros((42, 42, 4), np.uint8)
        image[4:39, 11:31] = [30, 80, 200, 255]
        cv2.imencode(".png", image)[1].tofile(path)
        self.app.mode.set("自动识别")
        self.app.set_canvas_size(32)
        with patch.object(core, "_refine_grid_image", return_value=image):
            self.app.append_files([path])
            self.pump_until(lambda: "主体 20×35 → 18×32" in self.app.scale_caption.cget("text"))
            self.assertIn("宽缩小 10.0%", self.app.scale_caption.cget("text"))
            self.assertIn("在 10% 以内", self.app.scale_caption.cget("text"))
            self.assertEqual(str(self.app.scale_caption.cget("foreground")), "#555")
            self.app.layout.set("整图等比例缩放 · 保留原留白")
            self.pump_until(lambda: "整图 42×42 → 32×32" in self.app.scale_caption.cget("text"))
            self.assertIn("宽缩小 23.8%", self.app.scale_caption.cget("text"))
            self.assertIn("超过 10%", self.app.scale_caption.cget("text"))
            self.assertEqual(str(self.app.scale_caption.cget("foreground")), "#9b4f00")
            self.app.layout.set("主体不缩放 · 改画布")
            self.app.set_canvas_size(42)
            self.pump_until(lambda: "主体未缩放" in self.app.scale_caption.cget("text"))
            self.app.mode.set("原图直接转换")
            self.app.layout.set("主体等比例缩放 · 改画布")
            self.app.set_canvas_size(32)
            self.pump_until(lambda: "不套用 10%" in self.app.scale_caption.cget("text"))

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

    def test_source_choices_use_auto_grid_or_direct_without_manual_size(self):
        self.assertEqual([button.cget("value") for button in self.app.source_buttons],
                         ["自动识别", "原图直接转换"])
        self.assertFalse(hasattr(self.app, "width_input"))
        path = self.image("输入方式.png")
        self.app.layout.set("保持原画布")
        self.app.mode.set("自动识别")
        cuts = np.arange(0, 17, 4)
        with patch("pixel_core.detect_grid_scale", return_value=(4, 4)) as detect, \
             patch("pixel_core.refine_grids", return_value=(cuts, cuts)):
            self.app.append_files([path])
            self.pump_until(lambda: "4 × 4" in self.app.output_caption.cget("text"))
            self.assertIn("网格 4×4", self.app.subject_caption.cget("text"))
            self.assertEqual(str(self.app.method_input.cget("state")), "readonly")
            self.assertIsNone(self.app.get_options().grid)
            calls = detect.call_count
            self.app.mode.set("原图直接转换")
            self.pump_until(lambda: "16 × 16" in self.app.output_caption.cget("text"))
            self.assertEqual(detect.call_count, calls)
            self.assertEqual(str(self.app.method_input.cget("state")), "disabled")
            self.assertTrue(self.app.get_options().direct)
        self.assertEqual(self.app.algorithm_step.winfo_manager(), "")
        self.app.set_canvas_size(32)
        self.assertEqual(self.app.get_options().layout, "fit")
        self.assertEqual(self.app.mode.get(), "原图直接转换")
        self.assertEqual(self.app.algorithm_step.winfo_manager(), "pack")
        self.app.resample.set("k-centroid · 局部主色")
        self.assertEqual(self.app.pixel_row.winfo_manager(), "")
        self.app.resample.set("目标像素 · 结构保护")
        self.assertEqual(self.app.pixel_row.winfo_manager(), "pack")

    def test_delete_edits_size_without_removing_the_selected_image(self):
        path = self.image("快捷键.png")
        self.app.append_files([path])
        self.app.tree.selection_set(path_key(path))
        self.app.deiconify()
        self.app.update()
        self.app.canvas_width.set("32")
        entry = self.app.canvas_width_input
        entry.focus_force()
        entry.selection_range(0, 1)
        entry.event_generate("<Delete>")
        self.app.update()
        self.assertEqual(self.app.canvas_width.get(), "2")
        self.assertEqual(self.app.files, [path.resolve()])
        self.app.tree.focus_force()
        self.app.tree.event_generate("<Delete>")
        self.app.update()
        self.assertEqual(self.app.files, [])
        self.assertTrue(path.exists())

    def test_old_manual_size_migrates_to_auto_and_target_canvas(self):
        gui.SETTINGS.write_text(gui.json.dumps({"mode": "指定尺寸", "width": 32, "height": 16}),
                                encoding="utf-8")
        migrated = gui.App()
        try:
            migrated.withdraw()
            options = migrated.get_options()
            self.assertEqual(migrated.mode.get(), "自动识别")
            self.assertIsNone(options.grid)
            self.assertEqual((options.layout, options.canvas), ("canvas_fit", (32, 16)))
            migrated.save_settings()
            self.assertNotIn("width", gui.load_settings())
            self.assertNotIn("height", gui.load_settings())
        finally:
            migrated.destroy()
            migrated.preview_pool.shutdown(wait=True, cancel_futures=True)

    def test_target_pixel_controls_and_full_canvas_direct_conversion(self):
        path = self.image("方块.png")
        self.app.append_files([path])
        self.app.layout.set("整图等比例缩放 · 保留原留白")
        self.app.set_canvas_size(8)
        self.app.palette.set("8 色")
        self.app.detail.set("较强")
        self.app.mode.set("原图直接转换")
        self.pump_until(lambda: "8 × 8" in self.app.output_caption.cget("text"))
        options = self.app.get_options()
        self.assertEqual((options.layout, options.direct, options.palette_size, options.detail),
                         ("canvas_fit", True, 8, 2))
        self.assertEqual(str(self.app.palette_input.cget("state")), "readonly")
        self.assertIn("原图 16×16", self.app.subject_caption.cget("text"))
        self.app.start()
        self.pump_until(lambda: not self.app.busy)
        result = self.app.results[path_key(path)]
        self.assertEqual((result.width, result.height), (8, 8))
        self.assertEqual(result.info.recovery, "direct")


class PreviewRendererTests(unittest.TestCase):
    def test_scale_notice_distinguishes_enlargement_and_fallback(self):
        info = gui.image_info(np.full((30, 30, 4), 255, np.uint8))
        text, attention = gui.scaling_text(info, gui.Options(layout="stretch", canvas=(40, 40)))
        self.assertTrue(attention)
        self.assertIn("放大 33.3%", text)
        self.assertIn("放大不会补回细节", text)
        self.assertNotIn("丢失细线", text)
        info = gui.image_info(np.full((1254, 1254, 4), 255, np.uint8), "fallback")
        text, attention = gui.scaling_text(info, gui.Options(layout="stretch", canvas=(32, 32)))
        self.assertFalse(attention)
        self.assertIn("网格识别失败", text)
        self.assertIn("不套用 10%", text)

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
                        options = gui.Options(method=method, grid=(4, 4))
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
                for layout, canvas, resample in (("original", None, "nearest"),
                                       ("keep", (12, 14), "nearest"), ("fit", (8, 8), "nearest"),
                                       ("fit", (8, 8), "pixel"),
                                       ("canvas_fit", (12, 8), "nearest"),
                                       ("canvas_fit", (8, 12), "nearest"),
                                       ("canvas_fit", (12, 8), "pixel"),
                                       ("stretch", (8, 8), "pixel"),
                                       ("fit", (8, 8), "k-centroid"),
                                       ("canvas_fit", (12, 8), "k-centroid"),
                                       ("stretch", (8, 12), "k-centroid")):
                    options = gui.Options(grid=(16, 16), layout=layout, canvas=canvas,
                                          resample=resample)
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
