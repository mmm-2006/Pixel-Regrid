from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import pixel_core as core


class PixelCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, image):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        ok, encoded = cv2.imencode(path.suffix, image)
        self.assertTrue(ok)
        encoded.tofile(path)
        return path

    def test_unicode_path_exports_only_one_target_size_png(self):
        image = np.arange(8 * 12 * 3, dtype=np.uint8).reshape(8, 12, 3)
        path = self.write("中文 文件夹/贴图.png", image)
        original = path.read_bytes()
        result = core.process_file(path, core.Options(grid=(6, 4)))
        self.assertEqual((result.width, result.height), (6, 4))
        out = core.read_image(result.output)
        self.assertEqual(out.shape, (4, 6, 3))
        self.assertEqual(list(result.output.parent.iterdir()), [result.output])
        self.assertEqual(path.read_bytes(), original)

    def test_manual_grid_full_extent_all_methods(self):
        cells = np.array([[[20, 80, 200], [200, 80, 20], [1, 2, 3]],
                          [[10, 30, 50], [255, 0, 0], [0, 255, 255]]], dtype=np.uint8)
        image = cells.repeat(6, axis=0).repeat(6, axis=1)
        for method in core.SAMPLERS:
            with self.subTest(method=method):
                out = core.refine_image(image, core.Options(method=method, grid=(3, 2)))
                np.testing.assert_array_equal(out, cells)

    def test_rgba_preserved_with_same_grid_for_all_methods(self):
        cells = np.array([[[12, 40, 200, 255], [200, 90, 12, 128]],
                          [[190, 120, 80, 0], [40, 50, 60, 64]]], dtype=np.uint8)
        image = cells.repeat(8, axis=0).repeat(8, axis=1)
        expected = cells.copy()
        expected[1, 0, :3] = 0
        for method in core.SAMPLERS:
            with self.subTest(method=method):
                out = core.refine_image(image, core.Options(method=method, grid=(2, 2)))
                np.testing.assert_array_equal(out, expected)
        path = self.write("透明.png", image)
        result = core.process_file(path, core.Options(grid=(2, 2)))
        np.testing.assert_array_equal(core.read_image(result.output), expected)
        self.assertEqual(core.read_image(result.output).shape[2], 4)

    def test_transparent_hidden_colors_do_not_pollute_visible_color(self):
        image = np.full((8, 8, 4), [255, 0, 0, 0], dtype=np.uint8)
        image[:6] = [0, 0, 200, 255]
        for method in ("median", "majority"):
            out = core.refine_image(image, core.Options(method=method, grid=(1, 1)))
            np.testing.assert_array_equal(out[0, 0], [0, 0, 200, 255])

    def test_same_stem_different_extensions_and_repeat_never_overwrite(self):
        image = np.full((8, 8, 3), 120, np.uint8)
        png = self.write("test.png", image)
        bmp = self.write("test.bmp", image)
        first = core.process_file(png, core.Options(grid=(4, 4)))
        old = first.output.read_bytes()
        second = core.process_file(bmp, core.Options(grid=(4, 4)))
        third = core.process_file(png, core.Options(grid=(4, 4)))
        self.assertEqual(len({first.output, second.output, third.output}), 3)
        self.assertEqual(old, first.output.read_bytes())
        self.assertIn("_2", second.output.stem)
        self.assertEqual(len(list(first.output.parent.iterdir())), 3)

    def test_existing_legacy_preview_is_preserved_without_blocking_output(self):
        dest = self.root / "out"
        dest.mkdir()
        existing = dest / "a_perfect_2x2_preview_8x.png"
        existing.write_bytes(b"keep me")
        main = core.save_output(dest, "a", np.zeros((2, 2, 3), np.uint8))
        self.assertEqual(main.name, "a_perfect_2x2.png")
        self.assertEqual(existing.read_bytes(), b"keep me")
        self.assertEqual(set(dest.iterdir()), {main, existing})

    def test_write_failure_removes_partial_outputs_and_temps(self):
        dest = self.root / "out"
        with patch.object(core.os, "replace", side_effect=OSError("模拟磁盘写入失败")):
            with self.assertRaisesRegex(OSError, "磁盘"):
                core.save_output(dest, "a", np.zeros((2, 2, 3), np.uint8))
        self.assertEqual(list(dest.iterdir()), [])

    def test_encode_failure_reports_no_success(self):
        with patch.object(core.cv2, "imencode", return_value=(False, None)):
            with self.assertRaisesRegex(OSError, "编码"):
                core.save_output(self.root / "out", "a", np.zeros((2, 2, 3), np.uint8))

    def test_scan_prunes_outputs_hidden_and_custom_folder(self):
        image = np.zeros((8, 8, 3), np.uint8)
        expected = [self.write("a.PNG", image), self.write("nested/b.png", image)]
        self.write("perfect_pixel_output/result.png", image)
        self.write("nested/Perfect_Pixel_Output/result.png", image)
        self.write(".hidden/result.png", image)
        self.write("custom/result.png", image)
        found, warnings = core.scan_folder(self.root, self.root / "custom")
        self.assertEqual(set(found), {p.resolve() for p in expected})
        self.assertEqual(warnings, [])
        cancelled = threading.Event()
        cancelled.set()
        self.assertEqual(core.scan_folder(self.root, cancel=cancelled)[0], [])

    def test_grayscale_and_16_bit_conversion(self):
        gray = self.write("gray.png", np.full((8, 8), 180, np.uint8))
        self.assertEqual(core.read_image(gray).shape, (8, 8, 3))
        path = self.write("16bit.png", np.array([[0, 32768, 65535]], dtype=np.uint16))
        np.testing.assert_array_equal(core.read_image(path)[0, :, 0], [0, 128, 255])

    def test_corrupt_and_empty_input(self):
        path = self.root / "broken.png"
        for content in (b"", b"not an image"):
            path.write_bytes(content)
            with self.assertRaises(ValueError):
                core.process_file(path, core.Options())
        self.assertFalse((self.root / core.OUTPUT_FOLDER).exists())

    def test_invalid_grid_is_rejected(self):
        for grid in ((0, 16), (16, -1), (1025, 16), (2.5, 3)):
            with self.assertRaises(ValueError):
                core.Options(grid=grid).validate()
        image = np.zeros((8, 8, 3), np.uint8)
        with self.assertRaisesRegex(ValueError, "大于原图"):
            core.refine_image(image, core.Options(grid=(16, 16)))

    def test_auto_failure_has_actionable_message(self):
        with patch.object(core, "detect_grid_scale", return_value=(None, None)):
            with self.assertRaisesRegex(ValueError, "原图直接转换"):
                core.refine_image(np.zeros((32, 32, 3), np.uint8), core.Options())

    def test_long_sampling_can_cancel_between_rows(self):
        image = np.zeros((64, 64, 3), np.uint8)
        cancel = threading.Event()
        calls = []
        def sample(values, xs, ys):
            calls.append(ys)
            cancel.set()
            return core.sample_median(values, xs, ys)
        with patch.dict(core.SAMPLERS, {"median": sample}):
            with self.assertRaises(InterruptedError):
                core.refine_image(image, core.Options(method="median", grid=(8, 8)), cancel)
        self.assertEqual(len(calls), 1)

    def test_subject_bounds_include_faint_edges_and_ignore_hidden_rgb(self):
        image = np.full((42, 42, 4), [200, 20, 10, 0], np.uint8)
        image[4:39, 11:31] = [30, 80, 200, 255]
        image[4, 11, 3] = 1
        info = core.image_info(image)
        self.assertEqual(info.grid, (42, 42))
        self.assertEqual(info.subject, (20, 35))
        self.assertEqual(core.subject_bounds(image), (11, 4, 31, 39))
        crop = core.layout_image(image, core.Options(layout="keep", canvas=info.subject))
        np.testing.assert_array_equal(crop, image[4:39, 11:31])

    def test_alpha_threshold_crop_discards_only_outside_bounds_and_preserves_rgba(self):
        image = np.zeros((20, 20, 4), np.uint8)
        image[5:15, 7:13] = [10, 30, 200, 64]
        image[1, 1] = image[18, 18] = [100, 120, 140, 1]
        image[8, 9] = [5, 15, 25, 1]
        image[9, 9] = [50, 60, 70, 0]
        path = self.write("透明杂点.png", image)
        result = core.process_file(path, core.Options(direct=True, layout="keep", canvas=(6, 10)))
        self.assertEqual(result.info.subject, (6, 10))
        np.testing.assert_array_equal(core.read_image(result.output), image[5:15, 7:13])
        self.assertEqual(core.image_info(image, alpha_threshold=0).subject, (18, 18))
        original = core.layout_image(image, core.Options(alpha_threshold=254))
        self.assertIs(original, image)
        for layout in ("canvas_fit", "stretch"):
            out = core.layout_image(image, core.Options(layout=layout, canvas=(20, 20), alpha_threshold=254))
            np.testing.assert_array_equal(out, image)

    def test_alpha_threshold_preserves_separate_parts_and_handles_faint_only_subject(self):
        image = np.zeros((10, 12, 4), np.uint8)
        image[2:4, 2:4] = [10, 20, 30, 64]
        image[6:8, 8:10] = [40, 50, 60, 64]
        self.assertEqual(core.image_info(image).subject, (8, 6))
        self.assertIsNone(core.image_info(image, alpha_threshold=64).subject)
        with self.assertRaisesRegex(ValueError, "降低阈值"):
            core.layout_image(image, core.Options(layout="keep", canvas=(12, 10), alpha_threshold=64))
        np.testing.assert_array_equal(
            core.layout_image(image, core.Options(layout="keep", canvas=(8, 6), alpha_threshold=0)),
            image[2:8, 2:10])
        opaque = np.full((3, 4, 3), 200, np.uint8)
        self.assertEqual(core.image_info(opaque, alpha_threshold=254).subject, (4, 3))
        for threshold in (-1, 255, True, 1.5, "1"):
            with self.assertRaisesRegex(ValueError, "透明噪点阈值"):
                core.Options(alpha_threshold=threshold).validate()

    def test_keep_subject_exact_pixels_minimum_canvas_and_centering(self):
        image = np.zeros((42, 42, 4), np.uint8)
        subject = np.random.default_rng(2).integers(1, 256, (35, 20, 4), dtype=np.uint8)
        image[4:39, 11:31] = subject
        for canvas in ((20, 35), (32, 40), (42, 42)):
            with self.subTest(canvas=canvas):
                out = core.refine_image(image, core.Options(grid=(42, 42), layout="keep", canvas=canvas))
                self.assertEqual(out.shape, (canvas[1], canvas[0], 4))
                left, top = (canvas[0] - 20) // 2, (canvas[1] - 35) // 2
                np.testing.assert_array_equal(out[top:top + 35, left:left + 20], subject)
                self.assertEqual(np.count_nonzero(out[..., 3]), 20 * 35)
        for canvas in ((19, 40), (32, 32), (42, 34)):
            with self.assertRaisesRegex(ValueError, "至少为 20×35"):
                core.layout_image(image, core.Options(layout="keep", canvas=canvas))

    def test_direct_large_subject_canvas_preserves_every_pixel_on_export(self):
        image = np.zeros((1254, 1254, 4), np.uint8)
        subject = np.random.default_rng(5).integers(1, 256, (1051, 607, 4), dtype=np.uint8)
        image[100:1151, 300:907] = subject
        path = self.write("大主体.png", image)
        for canvas in ((607, 1051), (1254, 1254), (2048, 1254)):
            with self.subTest(canvas=canvas):
                result = core.process_file(path, core.Options(direct=True, layout="keep", canvas=canvas))
                out = core.read_image(result.output)
                self.assertEqual(out.shape, (canvas[1], canvas[0], 4))
                left, top = (canvas[0] - 607) // 2, (canvas[1] - 1051) // 2
                np.testing.assert_array_equal(out[top:top + 1051, left:left + 607], subject)
                self.assertEqual(np.count_nonzero(out[..., 3]), 607 * 1051)

    def test_canvas_limits_reject_oversized_allocations_and_keep_scaling_bound(self):
        for canvas, message in (((8193, 1), "8192"), ((8192, 8192), "3200 万"),
                                ((0, 10), "8192")):
            with self.assertRaisesRegex(ValueError, message):
                core.Options(layout="keep", canvas=canvas).validate()
        for layout in ("fit", "canvas_fit", "stretch"):
            with self.assertRaisesRegex(ValueError, "1024"):
                core.Options(layout=layout, canvas=(1254, 1254)).validate()

    def test_fit_keeps_aspect_and_visible_colors(self):
        image = np.zeros((12, 12, 4), np.uint8)
        image[2:10, 3:9] = [10, 40, 200, 255]
        for canvas, expected in (((4, 4), (3, 4)), ((12, 12), (9, 12))):
            out = core.layout_image(image, core.Options(layout="fit", canvas=canvas))
            self.assertEqual(out.shape[:2], (canvas[1], canvas[0]))
            self.assertEqual(core.image_info(out).subject, expected)
            visible = out[out[..., 3] > 0]
            np.testing.assert_array_equal(visible[:, :3], np.tile([10, 40, 200], (len(visible), 1)))

    def test_default_pixel_scaling_adds_no_colors_or_transparency_levels(self):
        image = np.zeros((35, 20, 4), np.uint8)
        colors = np.array([[30, 40, 240, 255], [30, 220, 250, 255],
                           [200, 40, 20, 255]], np.uint8)
        yy, xx = np.indices(image.shape[:2])
        image[:] = colors[(xx + yy) % len(colors)]
        image[0, 0] = 0
        image[0, -1] = 0
        out = core.layout_image(image, core.Options(layout="fit", canvas=(32, 32)))
        self.assertEqual(out.shape, (32, 32, 4))
        original_values = {tuple(v) for v in image.reshape(-1, 4)}
        result_values = {tuple(v) for v in out.reshape(-1, 4)}
        self.assertTrue(result_values <= original_values)
        self.assertEqual(set(np.unique(out[..., 3])), {0, 255})

    def test_canvas_fit_preserves_original_margins_and_off_center_position(self):
        portrait = np.zeros((12, 8, 4), np.uint8)
        portrait[2:6, 2:4] = [10, 40, 200, 255]
        landscape = portrait.transpose(1, 0, 2).copy()
        square = np.zeros((8, 8, 4), np.uint8)
        square[2:4, 2:4] = [10, 40, 200, 255]
        cases = ((portrait, (10, 6), (4, 1, 5, 3)),
                 (landscape, (6, 10), (1, 4, 3, 5)),
                 (portrait, (16, 24), (4, 4, 8, 12)),
                 (square, (4, 4), (1, 1, 2, 2)))
        for image, canvas, bounds in cases:
            with self.subTest(canvas=canvas, source=image.shape):
                for resample in ("nearest", "pixel", "k-centroid"):
                    out = core.layout_image(image, core.Options(
                        layout="canvas_fit", canvas=canvas, resample=resample,
                        palette_size=0, detail=0))
                    expected = np.zeros((canvas[1], canvas[0], 4), np.uint8)
                    x0, y0, x1, y1 = bounds
                    expected[y0:y1, x0:x1] = [10, 40, 200, 255]
                    np.testing.assert_array_equal(out, expected)

    def test_canvas_fit_handles_opaque_and_fully_transparent_canvases(self):
        opaque = np.full((60, 40, 3), [30, 50, 80], np.uint8)
        out = core.layout_image(opaque, core.Options(layout="canvas_fit", canvas=(32, 32)))
        self.assertEqual(out.shape, (32, 32, 4))
        self.assertEqual(core.subject_bounds(out), (5, 0, 26, 32))
        self.assertTrue(np.all(out[:, 5:26, 3] == 255))
        self.assertTrue(np.all(out[:, :5] == 0))
        self.assertTrue(np.all(out[:, 26:] == 0))
        empty = np.zeros((12, 8, 4), np.uint8)
        for resample in ("nearest", "pixel", "k-centroid"):
            out = core.layout_image(empty, core.Options(
                layout="canvas_fit", canvas=(10, 6), resample=resample))
            np.testing.assert_array_equal(out, np.zeros((6, 10, 4), np.uint8))

    def test_empty_and_opaque_subjects_have_explicit_behavior(self):
        empty = np.zeros((4, 4, 4), np.uint8)
        self.assertIsNone(core.image_info(empty).subject)
        self.assertIs(core.layout_image(empty, core.Options()), empty)
        for layout in ("keep", "fit"):
            with self.assertRaisesRegex(ValueError, "完全透明"):
                core.layout_image(empty, core.Options(layout=layout, canvas=(4, 4)))
        opaque = np.full((3, 2, 3), [30, 50, 80], np.uint8)
        self.assertEqual(core.image_info(opaque).subject, (2, 3))
        padded = core.layout_image(opaque, core.Options(layout="keep", canvas=(4, 5)))
        np.testing.assert_array_equal(padded[1:4, 1:3, :3], opaque)
        self.assertTrue(np.all(padded[1:4, 1:3, 3] == 255))
        self.assertTrue(np.all(padded[0] == 0))

    def test_scale_notice_uses_actual_subject_size_and_ignores_padding(self):
        image = np.zeros((42, 42, 4), np.uint8)
        image[4:39, 11:31] = [30, 80, 200, 255]
        info = core.image_info(image)
        fit = core.Options(layout="fit", canvas=(32, 32))
        scale = core.scaling_info(info, fit)
        self.assertEqual((scale.source, scale.target), ((20, 35), (18, 32)))
        self.assertEqual(core.image_info(core.layout_image(image, fit)).subject, scale.target)
        self.assertFalse(scale.exceeds_threshold)  # Width changes by exactly 10%.
        whole = core.scaling_info(info, core.Options(layout="canvas_fit", canvas=(32, 32)))
        self.assertEqual((whole.source, whole.target), ((42, 42), (32, 32)))
        self.assertTrue(whole.exceeds_threshold)
        opaque = np.full((60, 30, 3), 120, np.uint8)
        options = core.Options(layout="canvas_fit", canvas=(100, 54))
        scale = core.scaling_info(core.image_info(opaque), options)
        self.assertEqual(scale.target, (27, 54))
        self.assertEqual(core.image_info(core.layout_image(opaque, options)).subject, scale.target)
        self.assertFalse(scale.exceeds_threshold)  # Wide transparent padding is not an enlargement.

    def test_scale_notice_threshold_direction_and_modes(self):
        info = core.ImageInfo((30, 30), (30, 30), True)
        for size, exceeds in ((27, False), (26, True), (32, False), (33, False), (34, True)):
            with self.subTest(size=size):
                scale = core.scaling_info(info, core.Options(layout="stretch", canvas=(size, size)))
                self.assertEqual(scale.exceeds_threshold, exceeds)
        for layout in ("original", "keep"):
            self.assertIsNone(core.scaling_info(info, core.Options(layout=layout, canvas=(64, 64))))
        for recovery in ("direct", "fallback"):
            info = core.ImageInfo((1254, 1254), (500, 924), True, recovery)
            self.assertIsNone(core.scaling_info(info, core.Options(layout="fit", canvas=(32, 32))))

    def test_canvas_validation_and_export_metadata(self):
        for options in (core.Options(layout="unknown"), core.Options(layout="keep"),
                        core.Options(layout="crop"),
                        core.Options(layout="canvas_fit"), core.Options(resample="bad"),
                        core.Options(resample="area"),
                        core.Options(canvas=(0, 2)), core.Options(canvas=(3, 1025)),
                        core.Options(canvas=(True, 2)), core.Options(canvas=(2.5, 2))):
            with self.assertRaises(ValueError):
                options.validate()
        image = np.zeros((8, 8, 4), np.uint8)
        image[2:6, 3:5] = [10, 30, 200, 128]
        path = self.write("画布.png", image)
        options = core.Options(grid=(8, 8), layout="keep", canvas=(6, 8))
        result = core.process_file(path, options)
        self.assertEqual(result.info.subject, (2, 4))
        self.assertEqual(result.info.grid, (8, 8))
        self.assertEqual((result.width, result.height), (6, 8))
        np.testing.assert_array_equal(core.read_image(result.output), core.refine_image(image, options))


if __name__ == "__main__":
    unittest.main()
