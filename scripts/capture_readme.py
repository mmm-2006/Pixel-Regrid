"""Render the real Vue interface with isolated demo bridge data in a headless browser."""
import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def picture(path):
    with Image.open(path) as image:
        width, height = image.size
    return dict(src="data:image/png;base64," + base64.b64encode(path.read_bytes()).decode(),
                width=width, height=height, limited=False)


def main():
    (ROOT / ".test_tmp").mkdir(exist_ok=True)
    examples = json.loads((ROOT / "docs/assets/examples.json").read_text(encoding="utf-8"))
    example = next(item for item in examples["examples"] if item["name"] == "ice-cream-fit")
    source_path = ROOT / example["source"]
    source = picture(source_path)
    result = picture(ROOT / "docs/assets" / example["output"]["file"])
    options = example["options"]
    state = dict(ok=True, revision=1, files=[dict(key="demo", name=source_path.name,
                 path=example["source"], status="pending", size=None)], options=options,
                 busy=False, cancelling=False, closing=False, status="已添加 1 张图片",
                 progress=dict(done=0, total=0), details=[], output_dir="")
    preview = dict(ok=True, original=source, output=result, error=None,
                   info=example["info"], **example["explanation"])
    bridge = """<script>
    const demoState = STATE, demoPreview = PREVIEW;
    window.pywebview = {api: {
      bootstrap: async () => demoState, get_state: async () => ({ok: true}),
      configure: async () => ({ok: true}), cancel_preview: async () => ({ok: true}),
      thumbnail: async () => ({ok: true, image: demoPreview.original}),
      preview: async () => demoPreview
    }};
    </script>""".replace("STATE", json.dumps(state, ensure_ascii=False)).replace("PREVIEW", json.dumps(preview, ensure_ascii=False))
    assets = ROOT / "frontend/dist"

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                content = (assets / "index.html").read_text(encoding="utf-8").replace("<head>", "<head>" + bridge).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                super().do_GET()

        def log_message(self, *args):
            pass

    browsers = [Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")]
    browser = next((path for path in browsers if path.is_file()), None)
    if not browser:
        raise RuntimeError("A locally installed Chrome or Edge browser is required for this optional screenshot script.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(assets)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="readme-browser-", dir=ROOT / ".test_tmp") as profile:
            screenshot = ROOT / "docs/assets/interface.png"
            command = [str(browser), "--headless=new", "--no-first-run", "--no-default-browser-check",
                       "--disable-background-networking", "--hide-scrollbars", "--window-size=1440,960",
                       "--virtual-time-budget=5000", f"--user-data-dir={profile}",
                       f"--screenshot={screenshot}", f"http://127.0.0.1:{server.server_port}/"]
            completed = subprocess.run(command, capture_output=True, timeout=45,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            if completed.returncode or not screenshot.is_file():
                raise RuntimeError(completed.stderr.decode(errors="replace")[-1500:])
            print(f"Saved real Vue interface preview: {screenshot}")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
