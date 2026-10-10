"""Lightweight k-centroid resizing adapted from Astropulse's MIT implementation.

Reference: https://github.com/Astropulse/pixeldetector/blob/
6e88e18ddbd16529b5dd85b1c615cbb2e5778bf2/k-centroid.py
See THIRD_PARTY_NOTICES.md for the upstream license.

Keep the local Pillow quantization / dominant-cluster approach, but use exact
source-area overlap rather than rounded crops. Transparent RGB is excluded,
votes are opacity weighted, and alpha is selected from the winning cluster.
No outline expansion, global palette reduction, or thin-feature boost is used.
"""
import math

import cv2
import numpy as np
from PIL import Image


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("预览已取消")


def _footprints(length, target):
    """Area overlap for shrinking; select one source pixel along enlarged axes."""
    footprints = []
    for position in range(target):
        if target >= length:
            index = min(length - 1, int((position + .5) * length / target))
            footprints.append((index, index + 1, np.ones(1)))
        else:
            start, end = position * length / target, (position + 1) * length / target
            first, last = math.floor(start), min(length, math.ceil(end))
            indices = np.arange(first, last)
            weights = np.maximum(0, np.minimum(indices + 1, end) - np.maximum(indices, start))
            footprints.append((first, last, weights))
    return footprints


def k_centroid_pixels(image, size, cancel=None):
    """Resize BGR/BGRA to exact (width, height), using two local color clusters.

    At least half a cell's source area must be nontransparent. Foreground wins
    exact coverage ties. Output opacity is an area-weighted median of source
    alpha values in the winning color cluster, avoiding invented soft fringes.
    Palette centroids may introduce colors. This is an adapted legacy algorithm,
    not a reproduction of PixelOE's newer Torch backend.
    """
    _check_cancel(cancel)
    if (image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] not in (3, 4)
            or not image.shape[0] or not image.shape[1]):
        raise ValueError("k-centroid 需要非空的 8 位 BGR / BGRA 图片")
    if len(size) != 2 or any(type(n) is not int or not 1 <= n <= 1024 for n in size):
        raise ValueError("目标宽、高必须是 1～1024 的整数")
    tw, th = size
    h, w = image.shape[:2]
    # Upscaling does not need clustering, and must not recolor existing pixels.
    if tw >= w and th >= h:
        out = cv2.resize(image, size, interpolation=cv2.INTER_NEAREST_EXACT)
        if out.shape[2] == 4:
            out[out[..., 3] == 0, :3] = 0
        _check_cancel(cancel)
        return out
    if h * w > 4_000_000:
        raise ValueError("k-centroid 缩小最多处理 400 万像素；请先还原网格或缩小原图")
    out = np.zeros((th, tw, image.shape[2]), dtype=np.uint8)
    xs, ys = _footprints(w, tw), _footprints(h, th)
    for row, (y0, y1, yw) in enumerate(ys):
        for col, (x0, x1, xw) in enumerate(xs):
            _check_cancel(cancel)
            tile = image[y0:y1, x0:x1].reshape(-1, image.shape[2])
            areas = (yw[:, None] * xw[None]).ravel()
            alpha = tile[:, 3] if tile.shape[1] == 4 else np.full(len(tile), 255, np.uint8)
            visible = (alpha > 0) & (areas > 0)
            if not visible.any() or areas[visible].sum() < areas.sum() * .5 - 1e-10:
                continue
            colors, opacity, weights = tile[visible, :3], alpha[visible], areas[visible]
            # Same-color cells need neither a palette nor k-means iterations.
            if np.all(colors == colors[0]):
                color, members = colors[0], np.ones(len(colors), dtype=bool)
            else:
                rgb = np.ascontiguousarray(colors[:, ::-1][None])
                quantized = Image.fromarray(rgb).quantize(
                    colors=min(2, len(colors)), method=Image.Quantize.MAXCOVERAGE,
                    kmeans=2, dither=Image.Dither.NONE)
                labels = np.asarray(quantized).ravel()
                palette = np.asarray(quantized.getpalette(), dtype=np.uint8).reshape(-1, 3)
                votes = np.bincount(labels, weights=weights * opacity / 255, minlength=len(palette))
                tied = np.flatnonzero(np.isclose(votes, votes.max(), rtol=1e-12, atol=1e-12))
                # Resolve equal votes by color, independent of source traversal order.
                winner = min(tied, key=lambda index: tuple(palette[index]))
                color, members = palette[winner, ::-1], labels == winner
            out[row, col, :3] = color
            if out.shape[2] == 4:
                values, alpha_weights = opacity[members], weights[members]
                order = np.argsort(values, kind="stable")
                middle = np.searchsorted(np.cumsum(alpha_weights[order]), alpha_weights.sum() / 2)
                out[row, col, 3] = values[order[middle]]
    return out
