"""Local pywebview desktop shell and a thread-safe Python/JavaScript bridge."""
import base64
from collections import OrderedDict
from dataclasses import asdict
from functools import wraps
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

import cv2

from pixel_core import (Options, SUPPORTED, image_info, layout_image, path_key,
                        prepare_image, process_file, read_image, scan_folder)
from pixel_ui_shared import (METHODS, LAYOUTS, RESAMPLERS, PALETTES, DETAILS,
                             info_text, scaling_text)

from pixel_paths import APP_HOME, RESOURCE_ROOT as HERE
DEFAULTS = dict(direct=False, method="center", layout="original", width=32,
                height=32, resample="pixel", palette_size=32, detail=1, alpha_threshold=1)


def api_call(function):
    """Only return JSON-safe errors across the bridge; log unexpected failures."""
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return dict(ok=False, error=str(exc))
        except Exception as exc:
            logging.exception("Desktop API failed: %s", function.__name__)
            return dict(ok=False, error=f"操作失败：{exc}")
    return call


def parse_options(payload, output_dir=None):
    if not isinstance(payload, dict):
        raise ValueError("参数格式有误")
    data = DEFAULTS | {k: v for k, v in payload.items() if k in DEFAULTS}
    if type(data["direct"]) is not bool:
        raise ValueError("输入方式有误")
    if data["layout"] not in LAYOUTS.values():
        raise ValueError("输出方式有误")
    for field in ("width", "height", "palette_size", "detail", "alpha_threshold"):
        if type(data[field]) is not int:
            raise ValueError("尺寸、颜色数和透明阈值必须是整数")
    canvas = None if data["layout"] == "original" else (data["width"], data["height"])
    options = Options(method=data["method"], direct=data["direct"], layout=data["layout"],
                      canvas=canvas, resample=data["resample"], palette_size=data["palette_size"],
                      detail=data["detail"], alpha_threshold=data["alpha_threshold"],
                      output_dir=Path(output_dir).resolve() if output_dir else None)
    options.validate()
    # Even inactive inputs must remain usable when a different layout is selected.
    limit = 8192 if options.layout == "keep" else 1024
    if not all(1 <= data[k] <= limit for k in ("width", "height")):
        raise ValueError(f"画布宽、高必须是 1～{limit} 的整数")
    return options, data


def migrate_settings(settings):
    data = dict(DEFAULTS)
    legacy = dict(settings)
    if legacy.get("layout") == "方块铺满 · 改尺寸":
        legacy["layout"] = "整图等比例缩放 · 保留原留白"
    if legacy.get("mode") == "指定尺寸":
        legacy["mode"] = "自动识别"
        if legacy.get("layout", "保持原画布") in ("保持原画布", "只裁透明边 · 最小画布"):
            legacy.update(layout="整图等比例缩放 · 保留原留白",
                          canvas_width=legacy.get("width", 32), canvas_height=legacy.get("height", 32))
    data.update(direct=legacy.get("mode") == "原图直接转换",
                method=METHODS.get(legacy.get("method"), "center"),
                layout=LAYOUTS.get(legacy.get("layout"), "original"),
                resample=RESAMPLERS.get(legacy.get("resample"), "pixel"),
                palette_size=PALETTES.get(legacy.get("palette"), 32),
                detail=DETAILS.get(legacy.get("detail"), 1))
    for field, old in (("width", "canvas_width"), ("height", "canvas_height"), ("alpha_threshold", "alpha_threshold")):
        value = legacy.get(old, data[field])
        maximum = 254 if field == "alpha_threshold" else 8192 if data["layout"] == "keep" else 1024
        minimum = 0 if field == "alpha_threshold" else 1
        if type(value) is int and minimum <= value <= maximum:
            data[field] = value
    if isinstance(settings.get("web_options"), dict):
        web_options = dict(settings["web_options"])
        if web_options.get("layout") == "stretch":
            web_options["layout"] = "canvas_fit"
        try:
            _, data = parse_options(web_options)
        except (ValueError, TypeError):
            pass
    return data


def preview_image(image, limit=2048):
    """Keep alpha and hard edges. Never enlarge the PNG transferred to the UI."""
    h, w = image.shape[:2]
    scale = min(1, limit / max(w, h))
    if scale < 1:
        image = cv2.resize(image, (max(1, round(w * scale)), max(1, round(h * scale))),
                           interpolation=cv2.INTER_NEAREST)
    ok, blob = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("预览编码失败")
    return dict(src="data:image/png;base64," + base64.b64encode(blob).decode("ascii"),
                width=w, height=h, limited=scale < 1)


class WebRenderer:
    """One serialized renderer with a bounded grid cache; no Tk dependency."""
    def __init__(self):
        self.source_key = None
        self.source = None
        self.original = None
        self.prepared = OrderedDict()

    def render(self, path, options, cancel):
        if cancel.is_set():
            return dict(ok=False, cancelled=True)
        stat = path.stat()
        source_key = path_key(path), stat.st_mtime_ns, stat.st_size
        if source_key != self.source_key:
            self.prepared.clear()
            self.source = None
            self.source_key = None
            self.source = read_image(path)
            self.original = preview_image(self.source)
            self.source_key = source_key
        key = (options.method, options.direct,
               options.resample in ("pixel", "k-centroid") and options.layout in ("fit", "canvas_fit", "stretch"))
        info = None
        result = dict(ok=True, original=self.original, output=None, error=None)
        try:
            if key not in self.prepared:
                self.prepared[key] = prepare_image(self.source, options, cancel)
                while len(self.prepared) > 4:
                    self.prepared.popitem(last=False)
            prepared, previous = self.prepared[key]
            self.prepared.move_to_end(key)
            info = image_info(prepared, previous.recovery, options.alpha_threshold)
            result["output"] = preview_image(layout_image(prepared, options, cancel))
        except InterruptedError:
            return dict(ok=False, cancelled=True)
        except Exception as exc:
            result["error"] = str(exc)
        if cancel.is_set():
            return dict(ok=False, cancelled=True)
        text, attention = scaling_text(info, options)
        result.update(info=asdict(info) if info else None, info_text=info_text(info),
                      scaling_text=text, attention=attention)
        return result


class DesktopApi:
    def __init__(self, settings_path=None):
        self._settings_path = Path(settings_path) if settings_path else APP_HOME / "perfect_pixel_settings.json"
        try:
            settings = json.loads(self._settings_path.read_text(encoding="utf-8"))
            self._settings = settings if isinstance(settings, dict) else {}
        except (OSError, ValueError):
            self._settings = {}
        self._options = migrate_settings(self._settings)
        self._output_dir = self._settings.get("output_dir", "")
        if not isinstance(self._output_dir, str):
            self._output_dir = ""
        self._window = None
        self._lock = threading.RLock()
        self._render_lock = threading.Lock()
        self._dialog_lock = threading.Lock()
        self._files = OrderedDict()
        self._revision = 0
        self._busy = False
        self._closing = False
        self._cancel = threading.Event()
        self._preview_cancel = threading.Event()
        self._renderer = WebRenderer()
        self._worker = None
        self._last_output = None
        self._progress = dict(done=0, total=0)
        self._status = "就绪"
        self._details = []

    def _idle(self):
        if self._busy or self._closing:
            raise ValueError("请等待当前任务结束")

    def _touch(self, status=None, detail=None):
        self._revision += 1
        if status is not None:
            self._status = status
        if detail is not None:
            self._details.append(detail)
            self._details = self._details[-200:]

    def _snapshot(self):
        return dict(ok=True, revision=self._revision, files=[dict(f) for f in self._files.values()],
                    busy=self._busy, closing=self._closing, cancelling=self._cancel.is_set(),
                    progress=dict(self._progress), status=self._status, details=list(self._details),
                    output_dir=self._output_dir)

    def _save(self):
        data = dict(self._settings, web_options=dict(self._options), output_dir=self._output_dir)
        data.update(mode="原图直接转换" if self._options["direct"] else "自动识别",
                    canvas_width=self._options["width"], canvas_height=self._options["height"],
                    alpha_threshold=self._options["alpha_threshold"])
        for name, mapping, key in (("method", METHODS, "method"), ("layout", LAYOUTS, "layout"),
                                  ("resample", RESAMPLERS, "resample"), ("palette", PALETTES, "palette_size"),
                                  ("detail", DETAILS, "detail")):
            data[name] = next(label for label, value in mapping.items() if value == self._options[key])
        if self._window is not None:
            data["web_geometry"] = [self._window.width, self._window.height]
        temporary = self._settings_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._settings_path)
        self._settings = data

    def _append(self, paths, from_scan=False):
        with self._lock:
            if not from_scan:
                self._idle()
            added = skipped = 0
            for value in paths:
                path = Path(value).resolve()
                key = path_key(path)
                if key in self._files or not path.is_file() or path.suffix.lower() not in SUPPORTED:
                    skipped += 1
                    continue
                self._files[key] = dict(key=key, name=path.name, path=str(path), status="pending",
                                        output=None, size=None, error=None)
                added += 1
            self._touch(f"添加 {added} 张图片" + (f"，跳过 {skipped} 项" if skipped else ""))
            return dict(self._snapshot(), added=added)

    @api_call
    def bootstrap(self):
        with self._lock:
            return dict(self._snapshot(), options=dict(self._options))

    @api_call
    def get_state(self, revision=-1):
        with self._lock:
            return dict(ok=True, unchanged=True) if revision == self._revision else self._snapshot()

    @api_call
    def configure(self, payload):
        _, data = parse_options(payload)
        with self._lock:
            self._idle()
            self._options = data
            self._save()
        return dict(ok=True)

    @api_call
    def choose_files(self):
        import webview
        with self._dialog_lock:
            with self._lock:
                self._idle()
            selected = self._window.create_file_dialog(webview.FileDialog.OPEN,
                directory=self._settings.get("last_dir", ""), allow_multiple=True,
                file_types=("图片 (*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.tif;*.tiff)",))
            if selected:
                with self._lock:
                    self._settings["last_dir"] = str(Path(selected[0]).parent)
                return self._append(selected)
        return dict(ok=True)

    def _begin(self, status):
        self._idle()
        self._cancel.clear()
        self._preview_cancel.set()
        self._busy = True
        self._touch(status)

    def _finish(self):
        with self._lock:
            self._busy = False
            closing = self._closing
            self._touch()
        if closing and self._window is not None:
            self._window.destroy()

    def _scan(self, folder):
        try:
            paths, warnings = scan_folder(folder, Path(self._output_dir) if self._output_dir else None, self._cancel)
            with self._lock:
                # Append under the same lock before marking the scan idle.
                if not self._closing:
                    result = self._append(paths, from_scan=True)
                    self._touch(f"扫描{'已取消' if self._cancel.is_set() else '完成'}：添加 {result['added']} 张图片",
                                "\n".join(warnings) if warnings else None)
        except Exception as exc:
            logging.exception("Folder scan failed")
            with self._lock:
                self._touch("扫描失败", str(exc))
        finally:
            self._finish()

    @api_call
    def choose_folder(self):
        import webview
        with self._dialog_lock:
            with self._lock:
                self._idle()
            selected = self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                       directory=self._settings.get("last_dir", ""))
            if not selected:
                return dict(ok=True)
            return self._start_scan(selected[0])

    def _start_scan(self, folder):
        with self._lock:
            self._begin("正在扫描文件夹…")
            self._settings["last_dir"] = str(folder)
            self._progress = dict(done=0, total=0)
            self._worker = threading.Thread(target=self._scan, args=(folder,), daemon=True)
            self._worker.start()
            return self._snapshot()

    @api_call
    def remove_files(self, keys):
        with self._lock:
            self._idle()
            for key in keys:
                self._files.pop(key, None)
            self._preview_cancel.set()
            self._touch("已移除选中图片")
            return self._snapshot()

    @api_call
    def choose_output(self, reset=False):
        import webview
        with self._dialog_lock:
            with self._lock:
                self._idle()
            selected = None if reset else self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                                          directory=self._output_dir)
            if reset or selected:
                with self._lock:
                    self._idle()
                    self._output_dir = "" if reset else str(Path(selected[0]).resolve())
                    self._save()
                    self._touch()
                    return self._snapshot()
        return dict(ok=True)

    @api_call
    def cancel_preview(self):
        with self._lock:
            self._preview_cancel.set()
        return dict(ok=True)

    @api_call
    def preview(self, key, payload):
        options, _ = parse_options(payload)
        with self._lock:
            if self._closing:
                return dict(ok=False, cancelled=True)
            file = dict(self._files[key])
            self._preview_cancel.set()
            cancel = self._preview_cancel = threading.Event()
            busy = self._busy
        with self._render_lock:
            if cancel.is_set():
                return dict(ok=False, cancelled=True)
            if busy:
                original = preview_image(read_image(Path(file["path"])))
                output = preview_image(read_image(Path(file["output"]))) if file["output"] else None
                return dict(ok=True, original=original, output=output, info=None,
                            error=file["error"], info_text="批处理使用开始导出时的参数", scaling_text="",
                            attention=False, saved=True)
            return self._renderer.render(Path(file["path"]), options, cancel)

    @api_call
    def thumbnail(self, key):
        with self._lock:
            path = Path(self._files[key]["path"])
        return dict(ok=True, image=preview_image(read_image(path), 64))

    @api_call
    def start_export(self, keys, payload):
        with self._lock:
            self._idle()
            if not keys:
                raise ValueError("请先添加图片")
            files = [dict(self._files[key]) for key in dict.fromkeys(keys)]
            options, data = parse_options(payload, self._output_dir)
            self._options = data
            self._save()
            self._begin(f"开始处理 {len(files)} 张图片…")
            self._progress = dict(done=0, total=len(files))
            self._details = []
            for file in files:
                self._files[file["key"]].update(status="waiting", output=None, error=None, size=None)
            self._worker = threading.Thread(target=self._export, args=(files, options), daemon=True)
            self._worker.start()
            return self._snapshot()

    def _export(self, files, options):
        succeeded = failed = processed = 0
        try:
            for file in files:
                if self._cancel.is_set():
                    break
                with self._lock:
                    self._files[file["key"]]["status"] = "working"
                    self._touch(f"处理中 {processed + 1}/{len(files)}：{file['name']}")
                try:
                    result = process_file(Path(file["path"]), options)
                    succeeded += 1
                    with self._lock:
                        self._last_output = result.output.parent
                        self._files[file["key"]].update(status="success", output=str(result.output),
                                                       size=[result.width, result.height])
                        self._touch(detail=f"成功 · {file['name']} → {result.width}×{result.height} · {result.seconds:.2f}s\n"
                                           f"{info_text(result.info)}\n{result.output}")
                except Exception as exc:
                    failed += 1
                    logging.exception("Processing failed: %s", file["path"])
                    with self._lock:
                        self._files[file["key"]].update(status="error", error=str(exc))
                        self._touch(detail=f"失败 · {file['path']}\n{exc}")
                processed += 1
                with self._lock:
                    self._progress["done"] = processed
                    self._touch()
            with self._lock:
                for file in files[processed:]:
                    self._files[file["key"]]["status"] = "cancelled"
                self._touch(f"{'已取消' if processed < len(files) else '完成'}：成功 {succeeded} 张，失败 {failed} 张，未处理 {len(files) - processed} 张")
        finally:
            self._finish()

    @api_call
    def cancel(self):
        with self._lock:
            if self._busy:
                self._cancel.set()
                self._touch("正在取消，当前图片处理完后停止…")
            return self._snapshot()

    @api_call
    def open_output(self, key=None):
        with self._lock:
            file = self._files.get(key, {})
            folder = Path(file["output"]).parent if file.get("output") else self._last_output
        if folder is None or not folder.is_dir():
            raise ValueError("处理成功后可打开输出文件夹")
        if sys.platform == "win32":
            os.startfile(str(folder))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
        return dict(ok=True)

    def _on_closing(self):
        with self._lock:
            try:
                self._save()
            except OSError:
                logging.exception("Settings could not be saved")
            self._closing = True
            self._preview_cancel.set()
            self._cancel.set()
            if self._busy:
                self._touch("正在安全退出，当前图片处理完后关闭…")
                return False
        return True

    def _on_drop(self, event):
        paths = [f.get("pywebviewFullPath") for f in event.get("dataTransfer", {}).get("files", [])]
        paths = [p for p in paths if p]
        try:
            self._append(paths)
        except ValueError:
            pass


def run():
    import webview
    from webview.dom import DOMEventHandler
    frontend = HERE / "frontend" / "dist" / "index.html"
    if not frontend.is_file():
        raise RuntimeError("界面尚未构建，请在 frontend 目录执行 npm ci 和 npm run build。")
    api = DesktopApi()
    geometry = api._settings.get("web_geometry", [1280, 780])
    if not (isinstance(geometry, list) and len(geometry) == 2 and
            all(type(n) is int for n in geometry)):
        geometry = [1280, 780]
    screen = webview.screens[0]
    api._window = webview.create_window("Pixel Regrid · 像素网格化", str(frontend), js_api=api,
        width=max(960, min(screen.width - 48, geometry[0])),
        height=max(640, min(screen.height - 80, geometry[1])),
        min_size=(960, 640), background_color="#f4f5f7", text_select=True)
    api._window.events.closing += api._on_closing

    def loaded():
        api._window.dom.document.events.drop += DOMEventHandler(api._on_drop, prevent_default=True)

    api._window.events.loaded += loaded
    webview.start(gui="edgechromium" if sys.platform == "win32" else None,
                  localization={"global.quitConfirmation": "确定退出？", "global.ok": "确定", "global.cancel": "取消"})
