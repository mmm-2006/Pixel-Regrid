"""Render README comparisons from project inputs and actual JavaScript output pixels."""
import base64
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'docs/assets'
SOURCES = {
    'ice-cream': 'ChatGPT 图像 2026年10月9日 22_36_59.png',
    'enchanting-table': 'advanced_enchanting_table_top_diamond_ai.png',
}


def font(size):
    path = Path('C:/Windows/Fonts/msyh.ttc')
    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default(size=size)


def comparison(filename, panels, zoom=None):
    """Keep a shared integer zoom for layout comparisons so cropping never enlarges the subject."""
    columns = len(panels)
    panel_width = 480 if columns == 2 else 360
    area = 420 if columns == 2 else 336
    margin = 24
    width = columns * panel_width + (columns + 1) * margin
    canvas = Image.new('RGB', (width, area + 160), '#f4f5f7')
    draw = ImageDraw.Draw(canvas)
    for index, (picture, title, caption) in enumerate(panels):
        x = margin + index * (panel_width + margin)
        draw.text((x, 24), title, font=font(22 if columns == 2 else 20), fill='#283447')
        factor = zoom or min(area / picture.width, area / picture.height)
        size = (round(picture.width * factor), round(picture.height * factor))
        left = x + (panel_width - size[0]) // 2
        top = 80 + (area - size[1]) // 2
        step = max(8, zoom or 10)
        board = Image.new('RGBA', size, '#ffffff')
        check = ImageDraw.Draw(board)
        for y in range(0, size[1], step):
            for column in range(0, size[0], step):
                if (column // step + y // step) % 2:
                    check.rectangle((column, y, column + step - 1, y + step - 1), fill='#e4e7eb')
        board.alpha_composite(picture.convert('RGBA').resize(size, Image.Resampling.NEAREST))
        canvas.paste(board.convert('RGB'), (left, top))
        draw.rectangle((left - 1, top - 1, left + size[0], top + size[1]), outline='#b4bbc5')
        draw.text((x, area + 104), caption, font=font(18), fill='#586272')
    canvas.save(ASSETS / filename)


def main():
    ASSETS.mkdir(exist_ok=True)
    temporary = ROOT / '.test_tmp/readme-examples'
    temporary.mkdir(parents=True, exist_ok=True)
    inputs = []
    originals = {}
    for name, filename in SOURCES.items():
        path = ROOT / 'test-images' / filename
        with Image.open(path) as image:
            rgba = image.convert('RGBA')
            originals[name] = rgba.copy()
            inputs.append(dict(name=name, source=path.relative_to(ROOT).as_posix(),
                               image=dict(width=image.width, height=image.height,
                                          hasAlpha='A' in image.getbands(), data=base64.b64encode(rgba.tobytes()).decode())))
    request = temporary / 'inputs.json'
    response = temporary / 'outputs.json'
    request.write_text(json.dumps(inputs, ensure_ascii=False), encoding='utf-8')
    subprocess.run(['node', str(ROOT / 'frontend/scripts/readme-examples.mjs'), str(request), str(response)],
                   check=True, cwd=ROOT)
    records = json.loads(response.read_text(encoding='utf-8'))
    pictures = {}
    for record in records:
        raw = record.pop('image')
        size = (raw['width'], raw['height'])
        result = Image.frombytes('RGBA', size, base64.b64decode(raw['data']))
        name = record['name']
        result.save(ASSETS / f'{name}.png')
        pictures[name] = result
        record['output'] = dict(file=f'{name}.png', width=size[0], height=size[1])
    items = {record['name']: record for record in records}
    assert items['ice-cream-grid']['info']['grid'] == [42, 42]
    assert items['ice-cream-grid']['info']['subject'] == [20, 35]
    assert pictures['ice-cream-crop'].size == (20, 35)
    assert items['ice-cream-fit']['scaled_size'] == [18, 32]
    assert pictures['ice-cream-fit'].size == (20, 32)
    assert items['enchanting-table-grid']['info']['grid'] == [30, 30]
    assert pictures['enchanting-table-fit'].size == (32, 32)
    comparison('ice-cream-grid-comparison.png', [
        (originals['ice-cream'], 'AI 原图 · 1254 × 1254', '大色块不等于真实像素网格'),
        (pictures['ice-cream-grid'].resize((420, 420), Image.Resampling.NEAREST),
         '自动识别 · 42 × 42 网格', '每个识别到的像素块还原为一个像素'),
    ])
    comparison('ice-cream-layout-comparison.png', [
        (pictures['ice-cream-grid'], '还原画布 · 42 × 42', '主体 20 × 35，四周保留留白'),
        (pictures['ice-cream-crop'], '裁剪画布 · 20 × 35', '去掉透明留白，主体像素不变'),
        (pictures['ice-cream-fit'], '缩放画布 · 20 × 32', '等比缩放 · 主体 18 × 32 · 结构保护'),
    ], zoom=8)
    comparison('enchanting-table-comparison.png', [
        (pictures['enchanting-table-grid'], '自动识别 · 30 × 30 网格', 'AI 原图：1254 × 1254'),
        (pictures['enchanting-table-fit'], '缩放结果 · 32 × 32', '整图等比例缩放 · k-centroid'),
    ], zoom=12)
    (ASSETS / 'examples.json').write_text(json.dumps(dict(implementation='JavaScript', examples=records),
                                                    ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Saved actual algorithm outputs, three comparisons, and examples.json')


if __name__ == '__main__':
    main()
