"""Generate Python reference pixels for the JS prototype; never open a UI.

Run from the repository root, then: node frontend/scripts/compare.mjs
User images and reference pixels stay in the ignored prototype-results folder.
"""
import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from pixel_core import Options, prepare_image, layout_image, read_image

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "prototype-results"


def rgba(image):
    if image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    return image[..., [2, 1, 0, 3]].copy()


def main():
    DEST.mkdir(exist_ok=True)
    cases = []
    def add(name, source, options, exact=True):
        payload = dict(direct=options.direct, method=options.method, layout=options.layout,
                       width=options.canvas[0] if options.canvas else 32,
                       height=options.canvas[1] if options.canvas else 32,
                       resample=options.resample, palette_size=options.palette_size,
                       detail=options.detail, alpha_threshold=options.alpha_threshold)
        if options.grid:
            payload["grid"] = options.grid
        item = dict(name=name, source=dict(width=source.shape[1], height=source.shape[0],
                    hasAlpha=source.shape[2] == 4,
                    data=base64.b64encode(rgba(source).tobytes()).decode()), options=payload,
                    exact_required=exact)
        start = time.perf_counter()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                prepared, info = prepare_image(source, options)
                output = layout_image(prepared, options)
            item.update(expected=dict(width=output.shape[1], height=output.shape[0],
                        recovery=info.recovery, grid=info.grid,
                        data=base64.b64encode(rgba(output).tobytes()).decode()))
        except Exception as error:
            item["error"] = str(error)
        item["python_ms"] = (time.perf_counter() - start) * 1000
        cases.append(item)

    image = np.zeros((24, 32, 4), np.uint8)
    image[4:20, 10:22] = [30, 70, 150, 255]
    image[6:18, 12:20] = [100, 110, 130, 128]
    image[3, 9] = [14, 34, 56, 1]
    for layout in ("original", "keep", "fit", "canvas_fit"):
        for method in ("nearest", "pixel", "k-centroid"):
            add(f"transparent-{layout}-{method}", image,
                Options(direct=True, layout=layout, canvas=(32, 40), resample=method,
                        palette_size=0, detail=0))
    for shape in ((3, 5), (5, 3), (7, 11), (8, 12)):
        source = np.arange(shape[0] * shape[1] * 3, dtype=np.uint8).reshape(*shape, 3)
        for canvas in ((16, 16), (4, 4), (9, 15)):
            add(f"nearest-{shape}-{canvas}", source, Options(direct=True, layout="canvas_fit", canvas=canvas))
    rng = np.random.default_rng(42)
    pixels = rng.integers(0, 256, size=(12, 16, 4), dtype=np.uint8)
    pixels[..., 3] = rng.choice([0, 128, 255], size=(12, 16))
    scaled = cv2.resize(pixels, (128, 96), interpolation=cv2.INTER_NEAREST)
    for sampler in ("center", "median", "majority"):
        add(f"manual-grid-{sampler}", scaled, Options(grid=(16, 12), method=sampler))
        add(f"automatic-grid-{sampler}", scaled, Options(method=sampler), exact=sampler != "majority")
    for method in ("pixel", "k-centroid"):
        for palette in (0, 8, 32):
            add(f"downscale-{method}-palette{palette}", pixels,
                Options(direct=True, layout="canvas_fit", canvas=(8, 8), resample=method,
                        palette_size=palette, detail=1), exact=False)
    for layout in ("keep", "fit", "canvas_fit"):
        blank = np.zeros((8, 8, 4), np.uint8)
        add(f"blank-{layout}", blank, Options(direct=True, layout=layout, canvas=(16, 16), resample="nearest"))
    add("undersized-canvas", image, Options(direct=True, layout="keep", canvas=(2, 2)))
    for folder in (ROOT / "1", ROOT / "2"):
        for path in sorted(folder.glob("*.png"))[:2]:
            source = read_image(path)
            for method in ("nearest", "pixel", "k-centroid"):
                add(f"real-{folder.name}-{path.stem}-{method}", source,
                    Options(layout="canvas_fit", canvas=(32, 32), resample=method,
                            palette_size=32, detail=1), exact=False)
    (DEST / "references.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {len(cases)} Python reference cases in prototype-results/references.json")


if __name__ == "__main__":
    main()
