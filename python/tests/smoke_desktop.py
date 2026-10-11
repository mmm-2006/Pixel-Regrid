"""Exercise the built Vue UI in real WebView2 with isolated images/settings.

Run manually from the project root: .venv\Scripts\python.exe python\tests\smoke_desktop.py
Native file dialogs are substituted so this check does not depend on UI automation.
Use --keep-open to inspect the final desktop test window.
"""
from pathlib import Path
import json
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import webview

from pixel_desktop import DesktopApi, HERE, api_call


class SmokeApi(DesktopApi):
    @api_call
    def choose_files(self):
        return self._append(self._samples)


def main():
    test_root = HERE / ".test_tmp"
    test_root.mkdir(exist_ok=True)
    folder = tempfile.TemporaryDirectory(dir=test_root)
    root = Path(folder.name)
    good, bad = root / "pixel-sword.png", root / "broken.png"
    fixture = HERE / ".test_tmp" / "ui-smoke" / "pixel-sword.png"
    if fixture.exists():
        good.write_bytes(fixture.read_bytes())
    else:
        image = np.zeros((32, 32, 4), np.uint8)
        for i in range(5, 26):
            image[i, 31 - i:34 - i] = [100, 220, 150, 255]
        cv2.imencode(".png", image)[1].tofile(good)
    bad.write_bytes(b"broken image")
    api = SmokeApi(root / "settings.json")
    api._samples = [good, bad]
    api._output_dir = str(root / "exports")
    api._options.update(direct=True, layout="fit", width=32, height=32)
    api._window = webview.create_window("Pixel Regrid · 界面验证", str(HERE / "frontend/dist/index.html"),
                                        js_api=api, width=1000, height=680, min_size=(960, 640),
                                        background_color="#111315")
    api._window.events.closing += api._on_closing
    finished = threading.Event()
    failure = []

    def checks():
        try:
            api._window.events.loaded.wait(20)
            api._window.evaluate_js(r"""
            window.__smoke = { done: false, steps: [] };
            (async () => {
              const wait = async (predicate, label) => {
                const deadline = Date.now() + 20000;
                while (!predicate()) {
                  if (Date.now() > deadline) throw new Error('Timeout: ' + label);
                  await new Promise(resolve => setTimeout(resolve, 100));
                }
                window.__smoke.steps.push(label);
              };
              const click = text => {
                const button = [...document.querySelectorAll('button')].find(el => el.textContent.trim() === text);
                if (!button || button.disabled) throw new Error('Missing enabled button: ' + text);
                button.click();
              };
              try {
                await wait(() => !document.querySelector('.import-actions button').disabled, 'bridge ready');
                click('添加图片');
                await wait(() => document.querySelectorAll('.file-row').length === 2, 'files imported');
                await wait(() => document.querySelectorAll('.image-heading small').length === 2, 'both previews loaded');
                click('物品图标');
                click('16 × 16');
                await wait(() => document.querySelectorAll('.image-heading small')[1]?.textContent.trim() === '16 × 16', 'preset updated preview');
                const input = document.querySelector('input[aria-label="画布宽度"]');
                input.value = '0'; input.dispatchEvent(new Event('input', { bubbles: true }));
                await wait(() => !!document.querySelector('.preview-error'), 'invalid parameter displayed');
                input.value = '16'; input.dispatchEvent(new Event('input', { bubbles: true }));
                await wait(() => !document.querySelector('.preview-error') && document.querySelectorAll('.image-heading small').length === 2, 'preview recovered');
                click('导出全部');
                await wait(() => document.querySelector('.status-copy').textContent.includes('成功 1 张，失败 1 张'), 'batch completed despite corrupt image');
                const rows = [...document.querySelectorAll('.file-row')];
                if (!rows[0].textContent.includes('已导出') || !rows[1].textContent.includes('失败')) throw new Error('Incorrect result states');
                click('处理结果');
                await wait(() => document.querySelectorAll('.image-pane').length === 1, 'result-only view');
                click('并排对比');
                await wait(() => document.querySelectorAll('.image-pane').length === 2, 'comparison restored');
                window.__smoke.done = true;
              } catch (error) { window.__smoke.error = String(error); window.__smoke.done = true; }
            })();
            true;
            """)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                result = api._window.evaluate_js("window.__smoke")
                if result and result.get("done"):
                    if result.get("error"):
                        raise AssertionError(json.dumps(result, ensure_ascii=False))
                    outputs = list((root / "exports").glob("*.png"))
                    assert len(outputs) == 1, outputs
                    saved = cv2.imdecode(np.fromfile(outputs[0], np.uint8), cv2.IMREAD_UNCHANGED)
                    assert saved.shape[:2] == (16, 16), saved.shape
                    assert json.loads((root / "settings.json").read_text(encoding="utf-8"))["web_options"]["width"] == 16
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    break
                time.sleep(.2)
            else:
                raise TimeoutError("Desktop smoke check timed out")
        except Exception as exc:
            failure.append(str(exc))
            print(f"SMOKE FAILED: {exc}", flush=True)
        finally:
            finished.set()
            if failure or "--keep-open" not in sys.argv:
                api._window.destroy()

    webview.start(checks, gui="edgechromium")
    finished.wait(5)
    folder.cleanup()
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())
