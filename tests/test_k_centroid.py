import threading
import unittest

import cv2
import numpy as np

import pixel_core as core
from pixel_k_centroid import k_centroid_pixels


class KCentroidTests(unittest.TestCase):
    def test_majority_color_is_kept_instead_of_averaging_across_color_groups(self):
        image = np.full((8, 8, 3), 20, np.uint8)
        image[:, 1] = 250
        out = k_centroid_pixels(image, (2, 2))
        np.testing.assert_array_equal(out, np.full((2, 2, 3), 20, np.uint8))
        self.assertGreater(cv2.resize(image, (2, 2), interpolation=cv2.INTER_AREA)[0, 0, 0], 20)

    def test_fractional_footprints_use_area_not_rounded_pixel_counts(self):
        image = np.array([[[250, 250, 250], [20, 20, 20], [20, 20, 20]]], np.uint8)
        out = k_centroid_pixels(image, (2, 1))
        np.testing.assert_array_equal(out[0, :, 0], [250, 20])
        # Transposition must preserve the area mapping.
        np.testing.assert_array_equal(k_centroid_pixels(image.transpose(1, 0, 2).copy(), (1, 2)),
                                      out.transpose(1, 0, 2))

    def test_hidden_rgb_never_changes_color_and_alpha_belongs_to_winner(self):
        image = np.full((8, 8, 4), [0, 255, 0, 0], np.uint8)
        image[1:7, 1:7] = [10, 30, 200, 64]
        out = k_centroid_pixels(image, (4, 4))
        changed = image.copy()
        changed[changed[..., 3] == 0, :3] = [255, 0, 255]
        np.testing.assert_array_equal(out, k_centroid_pixels(changed, (4, 4)))
        visible = out[..., 3] > 0
        self.assertTrue(visible.any())
        np.testing.assert_array_equal(out[visible], np.tile([10, 30, 200, 64], (visible.sum(), 1)))
        self.assertTrue(np.all(out[~visible] == 0))
        two_colors = np.full((4, 4, 4), [20, 20, 20, 64], np.uint8)
        two_colors[:, 0] = [250, 250, 250, 255]
        np.testing.assert_array_equal(k_centroid_pixels(two_colors, (1, 1))[0, 0],
                                      [250, 250, 250, 255])

    def test_coverage_threshold_is_hard_and_fully_transparent_input_is_zero(self):
        image = np.full((1, 4, 4), [0, 255, 0, 0], np.uint8)
        image[:, :2] = [10, 30, 200, 128]
        np.testing.assert_array_equal(k_centroid_pixels(image, (1, 1))[0, 0], [10, 30, 200, 128])
        image[:, 1, 3] = 0
        self.assertTrue(np.all(k_centroid_pixels(image, (1, 1)) == 0))
        image[..., 3] = 0
        self.assertTrue(np.all(k_centroid_pixels(image, (2, 1)) == 0))

    def test_upscale_and_same_size_preserve_visible_pixels_and_opacity(self):
        image = np.array([[[10, 40, 200, 64], [30, 200, 40, 255]],
                          [[255, 0, 255, 0], [240, 30, 40, 128]]], np.uint8)
        for size in ((2, 2), (3, 5), (4, 4)):
            expected = cv2.resize(image, size, interpolation=cv2.INTER_NEAREST_EXACT)
            expected[expected[..., 3] == 0, :3] = 0
            np.testing.assert_array_equal(k_centroid_pixels(image, size), expected)

    def test_mixed_axes_and_non_square_outputs_are_deterministic(self):
        image = np.random.default_rng(22).integers(0, 256, (42, 30, 4), dtype=np.uint8)
        image[..., 3] = 255
        for size in ((32, 16), (16, 32), (40, 20)):
            out = k_centroid_pixels(image, size)
            self.assertEqual(out.shape, (size[1], size[0], 4))
            self.assertTrue(np.all(out[..., 3] == 255))
            np.testing.assert_array_equal(out, k_centroid_pixels(image, size))

    def test_layouts_keep_subject_aspect_and_full_canvas_position(self):
        image = np.zeros((42, 42, 4), np.uint8)
        image[4:39, 11:31] = [30, 80, 200, 255]
        out = core.layout_image(image, core.Options(layout="fit", canvas=(32, 32), resample="k-centroid"))
        self.assertEqual(core.image_info(out).subject, (18, 32))
        portrait = np.zeros((12, 8, 4), np.uint8)
        portrait[2:6, 2:4] = [30, 80, 200, 255]
        out = core.layout_image(portrait, core.Options(layout="canvas_fit", canvas=(10, 6), resample="k-centroid"))
        self.assertEqual(core.subject_bounds(out), (4, 1, 5, 3))
        opaque = np.full((30, 42, 3), [30, 80, 200], np.uint8)
        out = core.layout_image(opaque, core.Options(layout="stretch", canvas=(32, 16), resample="k-centroid"))
        self.assertEqual(out.shape, (16, 32, 4))
        self.assertTrue(np.all(out[..., 3] == 255))

    def test_cancel_and_bad_sizes(self):
        image = np.full((42, 42, 4), 255, np.uint8)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            k_centroid_pixels(image, (32, 32), cancel)
        class CancelAfterChecks:
            calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls >= 8
        with self.assertRaises(InterruptedError):
            k_centroid_pixels(image, (32, 32), CancelAfterChecks())
        for size in ((0, 32), (32, 1025), (1.5, 3), (True, 3)):
            with self.assertRaises(ValueError):
                k_centroid_pixels(image, size)


if __name__ == "__main__":
    unittest.main()
