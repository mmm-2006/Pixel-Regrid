"""Image processing and file operations, independent of the Tk event loop."""
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import time

import cv2
import numpy as np
from pixel_retarget import target_pixels
from pixel_k_centroid import k_centroid_pixels
from perfect_pixel.perfect_pixel import (
    detect_grid_scale, refine_grids, sample_center, sample_majority, sample_median,
)

SUPPORTED = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
OUTPUT_FOLDER = "perfect_pixel_output"
MAX_IMAGE_PIXELS = 32_000_000
SAMPLERS = {"center": sample_center, "median": sample_median, "majority": sample_majority}


@dataclass(frozen=True)
class Options:
    method: str = "center"
    grid: tuple[int, int] | None = None
    output_dir: Path | None = None
    layout: str = "original"
    canvas: tuple[int, int] | None = None
    resample: str = "nearest"
    palette_size: int = 32
    detail: int = 1
    direct: bool = False

    def validate(self):
        if self.method not in SAMPLERS:
            raise ValueError("未知取样方式")
        if self.grid is not None and (len(self.grid) != 2 or any(
            type(n) is not int or not 1 <= n <= 1024 for n in self.grid
        )):
            raise ValueError("输出宽、高必须是 1～1024 的整数")
        if self.layout not in ("original", "crop", "keep", "fit", "canvas_fit", "stretch"):
            raise ValueError("未知主体 / 画布处理方式")
        if self.canvas is not None and (len(self.canvas) != 2 or any(
            type(n) is not int or not 1 <= n <= 1024 for n in self.canvas
        )):
            raise ValueError("画布宽、高必须是 1～1024 的整数")
        if self.layout in ("keep", "fit", "canvas_fit", "stretch") and self.canvas is None:
            raise ValueError("请指定画布宽、高")
        if self.resample not in ("nearest", "pixel", "k-centroid"):
            raise ValueError("未知主体缩放方式")
        if type(self.palette_size) is not int or self.palette_size not in (0, 8, 16, 32, 64):
            raise ValueError("目标像素颜色数必须为保留颜色、8、16、32 或 64")
        if type(self.detail) is not int or self.detail not in (0, 1, 2):
            raise ValueError("细节保护必须为关闭、适中或较强")
        if type(self.direct) is not bool:
            raise ValueError("直接转换选项必须为布尔值")


@dataclass(frozen=True)
class ImageInfo:
    grid: tuple[int, int]
    subject: tuple[int, int] | None
    has_alpha: bool
    recovery: str = "grid"


def subject_bounds(image):
    """Return exclusive bounds of every nontransparent pixel; never discard faint edges."""
    h, w = image.shape[:2]
    if image.shape[2] == 3:
        return 0, 0, w, h
    ys, xs = np.nonzero(image[..., 3] > 0)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def image_info(image, recovery="grid"):
    h, w = image.shape[:2]
    bounds = subject_bounds(image)
    subject = (bounds[2] - bounds[0], bounds[3] - bounds[1]) if bounds else None
    return ImageInfo((w, h), subject, image.shape[2] == 4, recovery)


def layout_image(image, options, cancel=None):
    """Lay out the subject or full image on a target canvas after grid recovery."""
    options.validate()
    if options.layout == "original":
        return image
    bounds = ((0, 0, image.shape[1], image.shape[0])
              if options.layout in ("canvas_fit", "stretch") else subject_bounds(image))
    if bounds is None:
        raise ValueError("图片完全透明，没有可识别的主体")
    x0, y0, x1, y1 = bounds
    subject = image[y0:y1, x0:x1]
    if options.layout == "crop":
        return subject.copy()
    cw, ch = options.canvas
    sh, sw = subject.shape[:2]
    if options.layout == "keep" and (cw < sw or ch < sh):
        raise ValueError(f"主体 {sw}×{sh}；保持主体不变时画布至少为 {sw}×{sh}，"
                         "请增大画布或选择主体等比例缩放")
    if subject.shape[2] == 3:
        subject = cv2.cvtColor(subject, cv2.COLOR_BGR2BGRA)
    if options.layout in ("fit", "canvas_fit", "stretch"):
        factor = min(cw / sw, ch / sh)
        tw, th = ((cw, ch) if options.layout == "stretch" else
                  (min(cw, max(1, round(sw * factor))), min(ch, max(1, round(sh * factor)))))
        if options.resample == "pixel":
            subject = target_pixels(subject, (tw, th), options.palette_size, options.detail,
                                    cancel=cancel, wrap=options.layout == "stretch")
        elif options.resample == "k-centroid":
            subject = k_centroid_pixels(subject, (tw, th), cancel=cancel)
        elif (tw, th) != (sw, sh):
            # Select existing pixels, including alpha, without blending colors.
            # Exact center mapping avoids the directional bias of legacy nearest.
            subject = cv2.resize(subject, (tw, th), interpolation=cv2.INTER_NEAREST_EXACT)
    sh, sw = subject.shape[:2]
    canvas = np.zeros((ch, cw, 4), dtype=np.uint8)
    left, top = (cw - sw) // 2, (ch - sh) // 2
    canvas[top:top + sh, left:left + sw] = subject
    return canvas


@dataclass(frozen=True)
class Result:
    source: Path
    output: Path
    width: int
    height: int
    seconds: float
    info: ImageInfo | None = None


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def scan_folder(folder, output_dir=None, cancel=None):
    """Prune output trees, hidden directories and symlinks before descending."""
    found, warnings = [], []
    excluded = path_key(output_dir) if output_dir else None
    def onerror(exc):
        warnings.append(str(exc))
    for root, dirs, files in os.walk(folder, onerror=onerror, followlinks=False):
        if cancel is not None and cancel.is_set():
            break
        if Path(root).name.casefold() == OUTPUT_FOLDER or path_key(root) == excluded:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                         and d.casefold() != OUTPUT_FOLDER
                         and not (Path(root) / d).is_symlink()
                         and not (Path(root) / d).is_junction()
                         and path_key(Path(root) / d) != excluded)
        for name in sorted(files):
            p = Path(root) / name
            if p.suffix.lower() in SUPPORTED and not p.is_symlink():
                found.append(p.resolve())
    return found, warnings


def read_image(path):
    raw = np.fromfile(str(path), dtype=np.uint8)
    if not raw.size:
        raise ValueError("文件为空")
    image = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("无法读取图片，文件可能已损坏或格式不支持")
    if image.shape[0] * image.shape[1] > MAX_IMAGE_PIXELS:
        raise ValueError("图片超过 3200 万像素，请先缩小后再处理")
    if image.dtype == np.uint16:
        # Use the full 16-bit range instead of truncating the low byte.
        image = np.rint(image.astype(np.float32) / 257).astype(np.uint8)
    elif image.dtype != np.uint8:
        raise ValueError("暂不支持浮点图片，请先转成 8 位 PNG")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("不支持的图片通道数")
    return image


class GridDetectionError(ValueError):
    pass


def _refine_grid_image(image, options, cancel=None):
    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise InterruptedError("预览已取消")

    check_cancel()
    options.validate()
    h, w = image.shape[:2]
    bgr = image[..., :3]
    if image.shape[2] == 4:
        alpha = image[..., 3:4].astype(np.float32) / 255
        # Invisible RGB must not create false grid edges or dark color fringes.
        detection = np.rint(bgr * alpha + 192 * (1 - alpha)).astype(np.uint8)
        sampling = np.concatenate((bgr.astype(np.float32) * alpha,
                                   image[..., 3:4].astype(np.float32)), axis=2)
    else:
        detection, sampling = bgr, image
    if options.grid:
        gw, gh = options.grid
        if gw > w or gh > h:
            raise ValueError(f"输出 {gw}×{gh} 大于原图 {w}×{h}")
        # Manual dimensions are exact, including all four image edges.
        xs = np.linspace(0, w, gw + 1).astype(np.int32)
        ys = np.linspace(0, h, gh + 1).astype(np.int32)
    else:
        if min(w, h) < 16:
            raise GridDetectionError("图片过小，无法可靠识别网格；请选择原图直接转换")
        gw, gh = detect_grid_scale(detection)
        if gw is None or gh is None or gw < 1 or gh < 1:
            raise GridDetectionError("自动识别网格失败；请选择原图直接转换，再设置目标画布尺寸")
        if gw > min(w, 1024) or gh > min(h, 1024):
            raise GridDetectionError("识别网格过密；请选择原图直接转换，再设置目标画布尺寸")
        xs, ys = refine_grids(detection, gw, gh)
        if len(xs) < 2 or len(ys) < 2:
            raise GridDetectionError("无法生成有效网格；请选择原图直接转换")
    check_cancel()
    cv2.setRNGSeed(42)
    if options.method == "center":
        out = sample_center(sampling, xs, ys)
    else:
        # Sample row by row so an obsolete preview can stop promptly. Use the
        # same deterministic sampling for previews and saved output.
        values = sampling.astype(np.float32, copy=False)
        out = np.empty((len(ys) - 1, len(xs) - 1, values.shape[2]), dtype=np.float32)
        for row in range(len(ys) - 1):
            check_cancel()
            sampler = SAMPLERS[options.method]
            kwargs = {"seed": 42 + row} if options.method == "majority" else {}
            out[row] = sampler(values, xs, ys[row:row + 2], **kwargs)[0]
    check_cancel()
    if image.shape[2] == 4:
        alpha = out[..., 3:4] / 255
        colors = np.divide(out[..., :3], alpha, out=np.zeros_like(out[..., :3]),
                           where=alpha > 0)
        out = np.concatenate((colors, out[..., 3:4]), axis=2)
    out = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    if out.size == 0:
        raise ValueError("处理结果为空；请指定输出尺寸")
    return out


def prepare_image(image, options, cancel=None):
    """Restore a grid or explicitly use the source; expose fallback in preview metadata."""
    options.validate()
    if cancel is not None and cancel.is_set():
        raise InterruptedError("预览已取消")
    recovery = "grid"
    if options.direct:
        out, recovery = image, "direct"
    else:
        try:
            out = _refine_grid_image(image, options, cancel)
        except GridDetectionError:
            if options.resample not in ("pixel", "k-centroid") or options.layout not in ("fit", "canvas_fit", "stretch") or options.grid:
                raise
            out, recovery = image, "fallback"
    return out, image_info(out, recovery)


def refine_image(image, options, cancel=None):
    out, _ = prepare_image(image, options, cancel)
    return layout_image(out, options, cancel)


def _encode_png(image):
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise OSError("PNG 编码失败")
    return encoded.tobytes()


def save_output(dest, stem, image):
    """Reserve a unique name, then atomically publish one target-size PNG."""
    h, w = image.shape[:2]
    blob = _encode_png(image)
    dest.mkdir(parents=True, exist_ok=True)
    base = f"{stem}_perfect_{w}x{h}"
    number = 1
    while True:
        name = base if number == 1 else f"{base}_{number}"
        path = dest / f"{name}.png"
        try:
            with path.open("xb"):
                pass
        except FileExistsError:
            number += 1
            continue
        break
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=dest, prefix=".pixel-", suffix=".tmp",
                                          delete=False) as f:
            temporary = Path(f.name)
            f.write(blob)
        os.replace(temporary, path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def process_file(path, options):
    options.validate()
    started = time.perf_counter()
    image = read_image(path)
    grid_image, info = prepare_image(image, options)
    out = layout_image(grid_image, options)
    dest = options.output_dir or path.parent / OUTPUT_FOLDER
    output = save_output(dest, path.stem, out)
    h, w = out.shape[:2]
    return Result(path, output, w, h, time.perf_counter() - started, info)
