"""Palette-based target grid voting with bounded thin-feature protection.

This is a deterministic geometric conversion, not a semantic redraw. Each target
cell votes over its actual source footprint. Opposite-edge contrast gives narrow
lines extra weight; a small neighborhood term resolves near-ties coherently.
"""
import cv2
import numpy as np


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("预览已取消")


def _palette_labels(colors, limit, cancel):
    """Return labels and actual source colors; optional weighted median-cut palette."""
    unique, inverse, counts = np.unique(colors, axis=0, return_inverse=True, return_counts=True)
    if not limit or len(unique) <= limit:
        return unique, inverse
    # Bin only for palette selection. The final representatives remain source colors.
    bins = unique.astype(np.int32) // 8
    _, bin_ids = np.unique(bins, axis=0, return_inverse=True)
    total = np.bincount(bin_ids, weights=counts)
    sums = np.stack([np.bincount(bin_ids, weights=counts * unique[:, i]) for i in range(3)], axis=1)
    means = sums / total[:, None]
    points = cv2.cvtColor(np.rint(means).astype(np.uint8)[None], cv2.COLOR_BGR2LAB)[0].astype(np.float32)
    groups = [np.arange(len(points))]
    while len(groups) < limit:
        _check_cancel(cancel)
        scores = []
        for indices in groups:
            weights = total[indices]
            center = np.average(points[indices], axis=0, weights=weights)
            variance = np.average((points[indices] - center) ** 2, axis=0, weights=weights)
            scores.append(float(variance.max() * weights.sum()) if len(indices) > 1 else -1)
        selected = int(np.argmax(scores))
        if scores[selected] <= 0:
            break
        indices = groups.pop(selected)
        center = np.average(points[indices], axis=0, weights=total[indices])
        axis = int(np.argmax(np.average((points[indices] - center) ** 2,
                                       axis=0, weights=total[indices])))
        order = indices[np.argsort(points[indices, axis], kind="stable")]
        split = int(np.searchsorted(np.cumsum(total[order]), total[order].sum() / 2)) + 1
        split = min(len(order) - 1, max(1, split))
        groups.extend((order[:split], order[split:]))
    # Pick the actual color closest to each cluster's average, including low-count accents.
    unique_lab = cv2.cvtColor(unique[None], cv2.COLOR_BGR2LAB)[0].astype(np.float32)
    representatives = []
    for group in groups:
        _check_cancel(cancel)
        members = np.flatnonzero(np.isin(bin_ids, group))
        center = np.average(unique_lab[members], axis=0, weights=counts[members])
        representatives.append(unique[members[np.argmin(((unique_lab[members] - center) ** 2).sum(axis=1))]])
    palette = np.asarray(representatives, np.uint8)
    palette_lab = cv2.cvtColor(palette[None], cv2.COLOR_BGR2LAB)[0].astype(np.float32)
    mapping = np.empty(len(unique), np.int32)
    for start in range(0, len(unique), 4096):
        _check_cancel(cancel)
        distance = ((unique_lab[start:start + 4096, None] - palette_lab[None]) ** 2).sum(axis=2)
        mapping[start:start + 4096] = distance.argmin(axis=1)
    return palette, mapping[inverse]


def target_pixels(image, size, palette_size=32, detail=0, cancel=None, wrap=False):
    """Convert to an exact target grid using source colors, never averaged output colors."""
    _check_cancel(cancel)
    tw, th = size
    h, w = image.shape[:2]
    if h * w > 4_000_000:
        raise ValueError("直接目标像素转换最多处理 400 万像素；请先还原网格或缩小原图")
    rgba = image if image.shape[2] == 4 else cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    alpha = rgba[..., 3]
    visible = alpha > 0
    if not np.any(visible):
        return np.zeros((th, tw, 4), np.uint8)
    # Palette construction ignores hidden RGB. Transparency stays a separate category.
    lab = cv2.cvtColor(rgba[..., :3], cv2.COLOR_BGR2LAB).astype(np.float32)
    palette, visible_labels = _palette_labels(rgba[..., :3][visible], palette_size, cancel)
    labels = np.full((h, w), -1, np.int32)
    labels[visible] = visible_labels
    if (tw, th) == (w, h):
        out = rgba.copy()
        out[visible, :3] = palette[visible_labels]
        out[~visible] = 0
        return out
    # Thin ridges contrast with BOTH opposite neighbors. Ordinary boundaries do
    # not get the same reward as a narrow line, reducing indiscriminate sharpening.
    comparison = np.concatenate((lab * (alpha[..., None] / 255),
                                 alpha[..., None].astype(np.float32)), axis=2)
    border = "wrap" if wrap else "edge"
    padded = np.pad(comparison, ((1, 1), (1, 1), (0, 0)), mode=border)
    center = padded[1:-1, 1:-1]
    distances = [np.linalg.norm(center - neighbor, axis=2) for neighbor in
                 (padded[1:-1, :-2], padded[1:-1, 2:], padded[:-2, 1:-1], padded[2:, 1:-1])]
    ridge = np.maximum(np.minimum(distances[0], distances[1]),
                       np.minimum(distances[2], distances[3]))
    importance = 1 + 3 * detail * np.clip((ridge - 12) / 60, 0, 1)
    xs = np.linspace(0, w, tw + 1)
    ys = np.linspace(0, h, th + 1)
    winners = np.full((th, tw), -1, np.int32)
    opacity = np.zeros((th, tw), np.uint8)
    candidates = []
    for row in range(th):
        _check_cancel(cancel)
        y0, y1 = ys[row:row + 2]
        iy0, iy1 = int(np.floor(y0)), min(h, int(np.ceil(y1)))
        wy = np.minimum(np.arange(iy0, iy1) + 1, y1) - np.maximum(np.arange(iy0, iy1), y0)
        for col in range(tw):
            x0, x1 = xs[col:col + 2]
            ix0, ix1 = int(np.floor(x0)), min(w, int(np.ceil(x1)))
            wx = np.minimum(np.arange(ix0, ix1) + 1, x1) - np.maximum(np.arange(ix0, ix1), x0)
            area = wy[:, None] * wx[None]
            local_labels = labels[iy0:iy1, ix0:ix1]
            local_alpha = alpha[iy0:iy1, ix0:ix1]
            occupied = local_labels >= 0
            fraction = float(area[occupied].sum() / area.sum())
            weighted = area * importance[iy0:iy1, ix0:ix1]
            foreground = float(weighted[occupied].sum())
            background = float(weighted[~occupied].sum())
            # Preserve narrow opaque protrusions, but never expand from zero coverage.
            if fraction < 0.45 and not (detail and fraction >= 0.12 and foreground > background):
                candidates.append(None)
                continue
            local_ids = local_labels[occupied]
            ids, inverse = np.unique(local_ids, return_inverse=True)
            masses = np.bincount(inverse, weights=weighted[occupied])
            coverage = np.bincount(inverse, weights=area[occupied]) / area.sum()
            score = masses / weighted.sum()
            # A tiny center preference makes ties deterministic without relying on
            # palette index order. Candidates still need a meaningful source footprint.
            cx, cy = min(w - 1, int((x0 + x1) / 2)), min(h - 1, int((y0 + y1) / 2))
            score += (ids == labels[cy, cx]) * 0.015
            allowed = coverage >= min(0.08, fraction)
            if not np.any(allowed):
                allowed[int(np.argmax(masses))] = True
            ids, score = ids[allowed], score[allowed]
            winners[row, col] = ids[int(np.argmax(score))]
            # Use an observed alpha level (weighted median), not a smoothed edge.
            order = np.argsort(local_alpha[occupied], kind="stable")
            cumulative = np.cumsum(area[occupied][order])
            opacity[row, col] = local_alpha[occupied][order[np.searchsorted(cumulative, cumulative[-1] / 2)]]
            candidates.append((ids, score))
    # Two conservative synchronous passes encourage coherent colors in near-ties.
    # Structural votes dominate this small term; no colors outside the local vote appear.
    for _ in range(2):
        updated = winners.copy()
        for row in range(th):
            _check_cancel(cancel)
            for col in range(tw):
                candidate = candidates[row * tw + col]
                if candidate is None:
                    continue
                ids, score = candidate
                support = np.zeros(len(ids), np.float64)
                for dy, dx in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                    ny, nx = row + dy, col + dx
                    if wrap:
                        ny, nx = ny % th, nx % tw
                    if 0 <= ny < th and 0 <= nx < tw:
                        support += ids == winners[ny, nx]
                updated[row, col] = ids[int(np.argmax(score + support * 0.025))]
        winners = updated
    out = np.zeros((th, tw, 4), np.uint8)
    selected = winners >= 0
    out[selected, :3] = palette[winners[selected]]
    out[..., 3] = opacity
    return out
