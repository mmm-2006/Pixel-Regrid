"""Create an original, reproducible pseudo-pixel fixture and actual processed output."""
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from pixel_core import Options, layout_image, prepare_image


def main():
    destination = ROOT / "docs/assets"
    destination.mkdir(parents=True, exist_ok=True)
    rows = ["......KKKK......", "......KLLK......", "......DGGD......",
            "......DGGD......", ".....DGGGGD.....", "....DGHGGGGD....",
            "...DGHGGGGGGD...", "...DGHGGGGGGD...", "..DGHGCCCCGGGD..",
            "..DGHCCCCCCGSD..", "..DGCCCCCCBBSD..", "..DGCCCBBBBBSD..",
            "...DGCBBBBBSD...", "...DGGSSSSSGD...", "....DDDDDDDD....",
            "................"]
    palette = {".": (0, 0, 0, 0), "D": (39, 54, 71, 255), "G": (191, 213, 226, 255),
               "H": (230, 243, 246, 255), "B": (56, 149, 201, 255), "C": (111, 200, 233, 255),
               "S": (34, 102, 149, 255), "K": (166, 107, 66, 255), "L": (212, 170, 113, 255)}
    assert all(len(row) == 16 for row in rows)
    widths = np.array([24, 23, 25, 24, 25, 23, 24, 25, 23, 24, 24, 25, 23, 24, 25, 23])
    heights = widths[::-1]
    xs = np.r_[0, np.cumsum(widths)]
    ys = np.r_[0, np.cumsum(heights)]
    source = np.zeros((int(ys[-1]), int(xs[-1]), 4), dtype=np.uint8)
    rng = np.random.default_rng(20261011)
    for y, row in enumerate(rows):
        for x, symbol in enumerate(row):
            color = palette[symbol]
            source[ys[y]:ys[y + 1], xs[x]:xs[x + 1]] = color
            if color[3]:
                noise = rng.integers(-7, 8, size=(heights[y], widths[x], 3))
                source[ys[y]:ys[y + 1], xs[x]:xs[x + 1], :3] = np.clip(np.array(color[:3]) + noise, 0, 255)
    original = Image.fromarray(source).filter(ImageFilter.GaussianBlur(.6))
    original.save(destination / "demo-original.png")
    rgba = np.array(original)
    bgra = rgba[..., [2, 1, 0, 3]].copy()
    prepared, info = prepare_image(bgra, Options(method="center"))
    output = layout_image(prepared, Options(method="center"))
    result = Image.fromarray(output[..., [2, 1, 0, 3]])
    result.save(destination / "demo-result.png")
    canvas = Image.new("RGB", (1024, 576), "#f4f5f7")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22) if Path("C:/Windows/Fonts/msyh.ttc").exists() else ImageFont.load_default()
    labels = [f"扰动原图 · {original.width} × {original.height}", f"实际还原结果 · {result.width} × {result.height}"]
    for offset, picture, label in zip((32, 536), (original, result), labels):
        draw.text((offset, 24), label, font=font, fill="#283447")
        for y in range(88, 536, 16):
            for x in range(offset, offset + 448, 16):
                fill = "#e4e7eb" if ((x - offset) // 16 + (y - 88) // 16) % 2 else "#ffffff"
                draw.rectangle((x, y, x + 15, y + 15), fill=fill)
        canvas.paste(picture.resize((448, 448), Image.Resampling.NEAREST), (offset, 88),
                     picture.resize((448, 448), Image.Resampling.NEAREST).getchannel("A"))
    canvas.save(destination / "demo-comparison.png")
    print(f"Original {original.width}x{original.height}; actual detected grid: {info.grid}; output {result.width}x{result.height}")


if __name__ == "__main__":
    main()
