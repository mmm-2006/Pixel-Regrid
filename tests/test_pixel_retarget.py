from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import pixel_core as core
from pixel_retarget import target_pixels


class TargetPixelTests(unittest.TestCase):
    def test_protected_thin_line_survives_when_nearest_and_plain_vote_drop_it(self):
        image = np.full((8, 8, 4), [20, 20, 20, 255], np.uint8)
        image[:, 1] = [250, 250, 250, 255]
        nearest = cv2.resize(image, (2, 2), interpolation=cv2.INTER_NEAREST_EXACT)
        plain = target_pixels(image, (2, 2), palette_size=0, detail=0)
        protected = target_pixels(image, (2, 2), palette_size=0, detail=1)
        self.assertTrue(np.all(nearest[..., 0] == 20))
        self.assertTrue(np.all(plain[..., 0] == 20))
        np.testing.assert_array_equal(protected[..., 0], [[250, 20], [250, 20]])
        self.assertEqual(set(np.unique(protected[..., 3])), {255})

    def test_thin_silhouette_tip_is_kept_without_filling_uncovered_cells(self):
        image = np.zeros((8, 8, 4), np.uint8)
        image[2:7, 2:6] = [20, 40, 200, 255]
        image[1, 2] = [20, 40, 200, 255]
        nearest = cv2.resize(image, (4, 4), interpolation=cv2.INTER_NEAREST_EXACT)
        protected = target_pixels(image, (4, 4), palette_size=0, detail=1)
        self.assertEqual(nearest[0, 1, 3], 0)
        self.assertEqual(protected[0, 1, 3], 255)
        self.assertTrue(np.all(protected[:, 0] == 0))
        self.assertTrue(np.all(protected[:, 3] == 0))

    def test_palette_is_bounded_deterministic_and_uses_only_source_colors(self):
        rng = np.random.default_rng(19)
        image = rng.integers(0, 256, (35, 20, 4), dtype=np.uint8)
        image[..., 3] = 255
        image[:, :2, 3] = 0
        options = dict(palette_size=8, detail=1)
        out = target_pixels(image, (12, 20), **options)
        np.testing.assert_array_equal(out, target_pixels(image, (12, 20), **options))
        used = {tuple(color) for color in out[out[..., 3] > 0, :3]}
        source = {tuple(color) for color in image[image[..., 3] > 0, :3]}
        self.assertLessEqual(len(used), 8)
        self.assertTrue(used <= source)
        self.assertEqual(set(np.unique(out[..., 3])), {0, 255})

    def test_semitransparent_opacity_is_not_averaged_and_hidden_colors_do_not_pollute(self):
        image = np.full((8, 8, 4), [0, 255, 0, 0], np.uint8)
        image[1:7, 1:7] = [10, 30, 200, 128]
        out = target_pixels(image, (4, 4), palette_size=8)
        self.assertTrue(set(np.unique(out[..., 3])) <= {0, 128})
        visible = out[..., 3] > 0
        np.testing.assert_array_equal(out[visible, :3], np.tile([10, 30, 200], (visible.sum(), 1)))

    def test_block_conversion_uses_full_extent_and_has_no_added_transparent_border(self):
        image = np.full((4, 6, 3), [30, 50, 80], np.uint8)
        image[:, :3] = [200, 30, 20]
        options = core.Options(grid=(6, 4), layout="stretch", canvas=(8, 8),
                               resample="pixel", palette_size=0)
        out = core.refine_image(image, options)
        self.assertEqual(out.shape, (8, 8, 4))
        self.assertTrue(np.all(out[..., 3] == 255))
        np.testing.assert_array_equal(out[0, 0, :3], image[0, 0])
        np.testing.assert_array_equal(out[-1, -1, :3], image[-1, -1])

    def test_direct_and_auto_fallback_are_explicit_and_other_errors_are_not_hidden(self):
        image = np.full((32, 32, 3), [40, 80, 120], np.uint8)
        options = core.Options(layout="fit", canvas=(16, 16), resample="pixel")
        with patch.object(core, "detect_grid_scale", return_value=(None, None)):
            prepared, info = core.prepare_image(image, options)
            self.assertIs(prepared, image)
            self.assertEqual(info.recovery, "fallback")
            out = core.refine_image(image, options)
            self.assertEqual(out.shape, (16, 16, 4))
            with self.assertRaises(core.GridDetectionError):
                core.refine_image(image, core.Options(layout="fit", canvas=(16, 16)))
        with patch.object(core, "detect_grid_scale") as detect:
            _, info = core.prepare_image(image, core.Options(direct=True))
            self.assertEqual(info.recovery, "direct")
            detect.assert_not_called()
        with self.assertRaisesRegex(ValueError, "大于原图"):
            core.refine_image(image, core.Options(grid=(64, 64), layout="fit", canvas=(16, 16), resample="pixel"))

    def test_export_matches_conversion_and_invalid_parameters_are_rejected(self):
        image = np.full((24, 24, 4), [10, 30, 200, 255], np.uint8)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.png"
            cv2.imencode(".png", image)[1].tofile(path)
            options = core.Options(direct=True, layout="fit", canvas=(16, 16), resample="pixel", preview_scale=2)
            result = core.process_file(path, options)
            np.testing.assert_array_equal(core.read_image(result.output), core.refine_image(image, options))
            self.assertEqual(result.info.recovery, "direct")
            self.assertEqual((result.width, result.height), (16, 16))
        for options in (core.Options(detail=3), core.Options(palette_size=7), core.Options(direct=1)):
            with self.assertRaises(ValueError):
                options.validate()

    def test_conversion_can_cancel_between_rows(self):
        class CancelAfterChecks:
            calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls >= 4
        image = np.full((32, 32, 4), [40, 80, 120, 255], np.uint8)
        with self.assertRaises(InterruptedError):
            target_pixels(image, (16, 16), cancel=CancelAfterChecks())


if __name__ == "__main__":
    unittest.main()
