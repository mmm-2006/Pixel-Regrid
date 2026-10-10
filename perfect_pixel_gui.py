import base64
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Portable Python distributions may need explicit Tcl/Tk paths.
_tcl_root = Path(sys.base_prefix) / "tcl"
for variable, pattern in (("TCL_LIBRARY", "tcl*/init.tcl"), ("TK_LIBRARY", "tk*/tk.tcl")):
    if not os.environ.get(variable):
        script = next(iter(sorted(_tcl_root.glob(pattern), reverse=True)), None)
        if script:
            os.environ[variable] = str(script.parent)

import cv2
import numpy as np
from pixel_core import (Options, SUPPORTED, SCALE_CHANGE_THRESHOLD, canvas_limit, image_info,
                        layout_image, path_key, prepare_image, process_file, read_image,
                        scaling_info, scan_folder)

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "perfect_pixel_settings.json"
from pixel_ui_shared import (METHODS, LAYOUTS, RESAMPLERS, PALETTES, DETAILS,
                             LAYOUT_HELP, RESAMPLE_HELP, info_text, scaling_text)


def load_settings():
    try:
        value = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def thumbnail(path, width=360, height=180):
    return image_thumbnail(read_image(path), width, height)


def image_thumbnail(image, width=360, height=180):
    h, w = image.shape[:2]
    factor = min(width / w, height / h)
    image = cv2.resize(image, (max(1, round(w * factor)), max(1, round(h * factor))),
                       interpolation=cv2.INTER_NEAREST)
    if image.shape[2] == 4:
        # Checkerboard makes transparent texture edges visible in the preview.
        y, x = np.indices(image.shape[:2])
        background = np.where((x // 10 + y // 10) % 2, 210, 240)[..., None]
        alpha = image[..., 3:4].astype(np.float32) / 255
        image = np.rint(image[..., :3] * alpha + background * (1 - alpha)).astype(np.uint8)
    ok, data = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("预览编码失败")
    return base64.b64encode(data).decode("ascii"), f"{w} × {h}"


class PreviewRenderer:
    """Used by one background thread; reuse decoded input and recent refinements."""
    def __init__(self):
        self.source_key = None
        self.source = None
        self.outputs = OrderedDict()
        self.infos = {}

    def render(self, path, options, width, height, cancelled):
        if cancelled.is_set():
            return None
        stat = path.stat()
        source_key = (path_key(path), stat.st_mtime_ns, stat.st_size)
        if source_key != self.source_key:
            # Do not keep the previous large source around while decoding a new one.
            self.source = None
            self.source_key = None
            self.outputs.clear()
            self.infos.clear()
            self.source = read_image(path)
            self.source_key = source_key
        original = image_thumbnail(self.source, width, height)
        if cancelled.is_set():
            return None
        key = (options.method, options.grid, options.direct,
               options.resample in ("pixel", "k-centroid") and options.layout in ("fit", "canvas_fit", "stretch"))
        info = None
        try:
            if key not in self.outputs:
                out, prepared_info = prepare_image(self.source, options, cancel=cancelled)
                self.outputs[key] = out
                self.infos[key] = prepared_info
                while len(self.outputs) > 4:
                    old_key, _ = self.outputs.popitem(last=False)
                    self.infos.pop(old_key, None)
            self.outputs.move_to_end(key)
            info = self.infos[key]
            if info.alpha_threshold != options.alpha_threshold:
                info = image_info(self.outputs[key], info.recovery, options.alpha_threshold)
                self.infos[key] = info
            output = image_thumbnail(layout_image(self.outputs[key], options, cancel=cancelled), width, height)
        except Exception as exc:
            output = f"无法预览：{exc}"
        return None if cancelled.is_set() else (original, output, info)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Perfect Pixel · 像素画整理")
        self.geometry("1060x930")
        self.minsize(880, 900)
        self.settings = load_settings()
        # Retire uniform manual-grid sampling, preserving its final size as a
        # target canvas only when the old layout did not already specify one.
        if self.settings.get("mode") == "指定尺寸":
            self.settings["mode"] = "自动识别"
            if self.settings.get("layout", "保持原画布") in ("保持原画布", "只裁透明边 · 最小画布"):
                self.settings["layout"] = "整图等比例缩放 · 保留原留白"
                for axis in ("width", "height"):
                    value = self.settings.get(axis, 32)
                    self.settings["canvas_" + axis] = value if type(value) is int and 1 <= value <= 1024 else 32
        if self.settings.get("layout") == "方块铺满 · 改尺寸":
            self.settings["layout"] = "整图等比例缩放 · 保留原留白"
        if self.settings.get("layout") == "只裁透明边 · 最小画布":
            # Its former per-image canvas has no saved fixed dimensions. Keep
            # the input intact until the user chooses "裁到主体大小".
            self.settings["layout"] = "保持原画布"
        geometry = self.settings.get("geometry", "")
        if isinstance(geometry, str):
            import re
            if re.fullmatch(r"\d{3,4}x\d{3,4}", geometry):
                self.geometry(geometry)
        self.files = []
        self.keys = set()
        self.results = {}
        self.last_output = None
        self.busy = False
        self.closing = False
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self.preview_token = 0
        self.worker = None
        self.controls = []
        self.photos = []
        self.current_info = None
        self.preview_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="thumbnail")
        self.preview_future = None
        self.preview_after_id = None
        self.preview_cancel = threading.Event()
        self.preview_renderer = PreviewRenderer()
        self._ui()
        for variable in (self.mode, self.method,
                         self.layout, self.canvas_width, self.canvas_height, self.resample,
                         self.palette, self.detail, self.alpha_threshold):
            variable.trace_add("write", self.preview_options_changed)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.tree.bind("<Delete>", lambda _: self.remove_selected())
        self.bind("<Control-o>", lambda _: self.add_files())
        self.bind("<Control-a>", self.select_all)
        self.poll_id = self.after(80, self.poll)

    def _setting(self, name, default):
        value = self.settings.get(name, default)
        return value if type(value) is type(default) else default

    def _button(self, parent, text, command, **pack):
        button = ttk.Button(parent, text=text, command=command)
        button.pack(**pack)
        self.controls.append((button, "normal"))
        return button

    def _ui(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=27)
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)
        ttk.Label(root, text="Perfect Pixel · 像素画整理", font=("Microsoft YaHei UI", 17, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(root, text="整理 AI 像素风图片，或导出指定尺寸的 Minecraft 贴图。支持透明 PNG。", foreground="#555").grid(row=1, column=0, sticky="w", pady=(4, 12))
        toolbar = ttk.Frame(root)
        toolbar.grid(row=2, column=0, sticky="ew")
        for text, command in (("添加图片…", self.add_files), ("添加文件夹…", self.add_folder),
                              ("移除选中", self.remove_selected), ("清空", self.clear)):
            self._button(toolbar, text, command, side="left", padx=(0, 8))
        self.count = ttk.Label(toolbar, text="尚未选择图片")
        self.count.pack(side="right")

        main = ttk.Panedwindow(root, orient="horizontal")
        main.grid(row=3, column=0, sticky="nsew", pady=(10, 8))
        listing = ttk.Frame(main)
        main.add(listing, weight=1)
        self.tree = ttk.Treeview(listing, columns=("file", "status", "size"), show="headings", selectmode="extended", height=8)
        for name, text, width in (("file", "图片", 200), ("status", "状态", 75), ("size", "输出尺寸", 75)):
            self.tree.heading(name, text=text)
            self.tree.column(name, width=width, minwidth=60, stretch=name == "file")
        self.tree.tag_configure("error", foreground="#af2020")
        self.tree.tag_configure("ok", foreground="#187443")
        scroll = ttk.Scrollbar(listing, orient="vertical", command=self.tree.yview)
        hscroll = ttk.Scrollbar(listing, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=hscroll.set)
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self.show_selection)
        preview = ttk.Frame(main, padding=(12, 0, 0, 0))
        main.add(preview, weight=2)
        ttk.Label(preview, text="调整参数自动更新预览 · 点击开始处理才保存文件",
                  anchor="center", foreground="#555").pack(side="bottom", fill="x", pady=(6, 0))
        original_panel = ttk.Frame(preview)
        original_panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        output_panel = ttk.Frame(preview)
        output_panel.pack(side="left", fill="both", expand=True)
        self.original_caption = ttk.Label(original_panel, text="原图", anchor="center")
        self.original_caption.pack(fill="x")
        self.original_view = ttk.Label(original_panel, text="选择图片查看预览", anchor="center")
        self.original_view.pack(fill="both", expand=True)
        self.output_caption = ttk.Label(output_panel, text="实时预览 · 最近邻显示", anchor="center")
        self.output_caption.pack(fill="x")
        self.output_view = ttk.Label(output_panel, text="选择图片后自动预览", anchor="center")
        self.output_view.pack(fill="both", expand=True)
        main.update_idletasks()
        if main.winfo_width() > 100:
            main.sashpos(0, int(main.winfo_width() * .34))

        opts = ttk.Frame(root)
        opts.grid(row=4, column=0, sticky="ew")
        self.mode = tk.StringVar(value=self._setting("mode", "自动识别"))
        if self.mode.get() not in ("自动识别", "原图直接转换"):
            self.mode.set("自动识别")
        self.method = tk.StringVar(value=self._setting("method", next(iter(METHODS))))
        if self.method.get() not in METHODS:
            self.method.set(next(iter(METHODS)))
        source_step = ttk.LabelFrame(opts, text="1. 输入方式", padding=8)
        source_step.pack(fill="x")
        first = ttk.Frame(source_step)
        first.pack(fill="x")
        self.source_buttons = []
        for label in ("自动识别", "原图直接转换"):
            button = ttk.Radiobutton(first, text=label, variable=self.mode, value=label)
            button.pack(side="left", padx=(0, 18))
            self.controls.append((button, "normal"))
            self.source_buttons.append(button)
        ttk.Label(first, text="网格取样").pack(side="left", padx=(16, 0))
        self.method_input = ttk.Combobox(first, textvariable=self.method, values=tuple(METHODS), width=20, state="readonly")
        self.method_input.pack(side="left", padx=8)
        self.controls.append((self.method_input, "readonly"))
        self.source_help = ttk.Label(source_step, foreground="#555", wraplength=820)
        self.source_help.pack(anchor="w", pady=(5, 0))
        self.resample = tk.StringVar(value=self._setting("resample", next(iter(RESAMPLERS))))
        if self.resample.get() not in RESAMPLERS:
            self.resample.set(next(iter(RESAMPLERS)))
        self.layout = tk.StringVar(value=self._setting("layout", "保持原画布"))
        if self.layout.get() not in LAYOUTS:
            self.layout.set("保持原画布")
        self.canvas_width = tk.StringVar(value=str(self._setting("canvas_width", 32)))
        self.canvas_height = tk.StringVar(value=str(self._setting("canvas_height", 32)))
        target_step = ttk.LabelFrame(opts, text="2. 输出布局与目标尺寸", padding=8)
        target_step.pack(fill="x", pady=(6, 0))
        layout_row = ttk.Frame(target_step)
        layout_row.pack(fill="x")
        ttk.Label(layout_row, text="输出方式").pack(side="left")
        combo = ttk.Combobox(layout_row, textvariable=self.layout, values=tuple(LAYOUTS),
                             width=30, state="readonly")
        combo.pack(side="left", padx=(8, 12))
        self.controls.append((combo, "readonly"))
        self.layout_help = ttk.Label(layout_row, foreground="#555", wraplength=470)
        self.layout_help.pack(side="left", fill="x", expand=True)
        canvas_row = ttk.Frame(target_step)
        canvas_row.pack(fill="x", pady=(8, 0))
        ttk.Label(canvas_row, text="目标画布宽 × 高").pack(side="left", padx=(0, 6))
        self.canvas_width_input = ttk.Spinbox(canvas_row, from_=1, to=1024,
                                              textvariable=self.canvas_width, width=5)
        self.canvas_width_input.pack(side="left")
        ttk.Label(canvas_row, text=" × ").pack(side="left")
        self.canvas_height_input = ttk.Spinbox(canvas_row, from_=1, to=1024,
                                               textvariable=self.canvas_height, width=5)
        self.canvas_height_input.pack(side="left")
        self.controls.extend(((self.canvas_width_input, "normal"),
                              (self.canvas_height_input, "normal")))
        for size in (16, 32, 64, 128):
            self._button(canvas_row, f"{size}×{size}", lambda n=size: self.set_canvas_size(n),
                         side="left", padx=(5, 0))
        self.grid_canvas_button = self._button(canvas_row, "用输入尺寸", self.use_grid_canvas,
                                               side="left", padx=(12, 0))
        self.subject_canvas_button = self._button(canvas_row, "裁到主体大小", self.use_subject_canvas,
                                                  side="left", padx=(8, 0))
        threshold = self._setting("alpha_threshold", 1)
        self.alpha_threshold = tk.StringVar(value=str(threshold if 0 <= threshold <= 254 else 1))
        threshold_row = ttk.Frame(target_step)
        threshold_row.pack(fill="x", pady=(8, 0))
        ttk.Label(threshold_row, text="透明噪点阈值").pack(side="left", padx=(0, 8))
        self.alpha_threshold_input = ttk.Spinbox(threshold_row, from_=0, to=254,
                                                 textvariable=self.alpha_threshold, width=5)
        self.alpha_threshold_input.pack(side="left")
        self.controls.append((self.alpha_threshold_input, "normal"))
        ttk.Label(threshold_row, text="0 关闭；忽略透明度不超过此值的外围杂点，仅用于主体裁边。",
                  foreground="#555", wraplength=650).pack(side="left", padx=12)
        self.subject_caption = ttk.Label(target_step, text=info_text(None), foreground="#555",
                                         wraplength=820)
        self.subject_caption.pack(anchor="w", pady=(6, 0))
        self.scale_caption = ttk.Label(target_step, text=scaling_text(None, None)[0],
                                       foreground="#555", wraplength=820)
        self.scale_caption.pack(anchor="w", pady=(5, 0))
        self.algorithm_step = ttk.LabelFrame(opts, text="3. 缩放算法", padding=8)
        self.algorithm_step.pack(fill="x", pady=(6, 0))
        algorithm_row = ttk.Frame(self.algorithm_step)
        algorithm_row.pack(fill="x")
        self.resample_input = ttk.Combobox(algorithm_row, textvariable=self.resample,
                                          values=tuple(RESAMPLERS), width=23, state="readonly")
        self.resample_input.pack(side="left")
        self.controls.append((self.resample_input, "readonly"))
        self.algorithm_help = ttk.Label(algorithm_row, foreground="#555", wraplength=600)
        self.algorithm_help.pack(side="left", padx=12, fill="x", expand=True)
        self.palette = tk.StringVar(value=self._setting("palette", "32 色"))
        if self.palette.get() not in PALETTES:
            self.palette.set("32 色")
        self.detail = tk.StringVar(value=self._setting("detail", "适中"))
        if self.detail.get() not in DETAILS:
            self.detail.set("适中")
        pixel_row = self.pixel_row = ttk.Frame(self.algorithm_step)
        pixel_row.pack(fill="x", pady=(8, 0))
        ttk.Label(pixel_row, text="目标像素颜色").pack(side="left")
        self.palette_input = ttk.Combobox(pixel_row, textvariable=self.palette,
                                          values=tuple(PALETTES), width=10, state="readonly")
        self.palette_input.pack(side="left", padx=(8, 16))
        ttk.Label(pixel_row, text="细节保护").pack(side="left")
        self.detail_input = ttk.Combobox(pixel_row, textvariable=self.detail,
                                         values=tuple(DETAILS), width=8, state="readonly")
        self.detail_input.pack(side="left", padx=8)
        self.controls.extend(((self.palette_input, "readonly"), (self.detail_input, "readonly")))
        self.output_dir = tk.StringVar(value=self._setting("output_dir", ""))
        self.export_step = ttk.LabelFrame(opts, text="保存", padding=8)
        self.export_step.pack(fill="x", pady=(6, 0))
        destination = ttk.Frame(self.export_step)
        destination.pack(fill="x")
        ttk.Label(destination, text="保存位置").pack(side="left")
        self.destination_label = ttk.Label(destination, text="", foreground="#555", width=55)
        self.destination_label.pack(side="left", fill="x", expand=True, padx=8)
        self._button(destination, "选择位置…", self.choose_output, side="left", padx=(0, 8))
        self._button(destination, "恢复默认", self.default_output, side="left")
        self.update_destination()
        self.update_grid_state()

        actions = ttk.Frame(root)
        actions.grid(row=5, column=0, sticky="ew", pady=(10, 6))
        self.run_button = self._button(actions, "开始处理全部", self.start, side="left")
        self.cancel_button = ttk.Button(actions, text="取消", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        ttk.Button(actions, text="打开输出文件夹", command=self.open_output).pack(side="right")
        self.progress = ttk.Progressbar(root, mode="determinate")
        self.progress.grid(row=6, column=0, sticky="ew")
        self.status = ttk.Label(root, text="就绪 · 原图保持不变，重名结果自动编号")
        self.status.grid(row=7, column=0, sticky="w", pady=4)
        details = ttk.Frame(root)
        details.grid(row=8, column=0, sticky="ew")
        self.details = tk.Text(details, height=2, wrap="word", state="disabled", font=("Microsoft YaHei UI", 9))
        scrollbar = ttk.Scrollbar(details, command=self.details.yview)
        self.details.configure(yscrollcommand=scrollbar.set)
        self.details.pack(side="left", fill="x", expand=True)
        scrollbar.pack(side="right", fill="y")

    def update_grid_state(self):
        auto = self.mode.get() == "自动识别"
        self.method_input.configure(state="readonly" if not self.busy and auto else "disabled")
        self.source_help.configure(text=("自动识别图片的像素网格并处理，网格识别准确时效果最好；指定输出分辨率需配合缩放算法。" if auto else
                                        "跳过网格还原，直接使用原图；目标尺寸在第 2 步设置。"))
        layout, resample = LAYOUTS[self.layout.get()], RESAMPLERS[self.resample.get()]
        self.layout_help.configure(text=LAYOUT_HELP[layout])
        self.algorithm_help.configure(text=RESAMPLE_HELP[resample])
        canvas_state = "normal" if not self.busy and LAYOUTS[self.layout.get()] in ("keep", "fit", "canvas_fit") else "disabled"
        self.canvas_width_input.configure(state=canvas_state, to=canvas_limit(layout))
        self.canvas_height_input.configure(state=canvas_state, to=canvas_limit(layout))
        self.alpha_threshold_input.configure(state="disabled" if self.busy else "normal")
        converting = not self.busy and LAYOUTS[self.layout.get()] in ("fit", "canvas_fit")
        self.resample_input.configure(state="readonly" if converting else "disabled")
        pixel_state = "readonly" if converting and RESAMPLERS[self.resample.get()] == "pixel" else "disabled"
        self.palette_input.configure(state=pixel_state)
        self.detail_input.configure(state=pixel_state)
        if layout in ("fit", "canvas_fit"):
            if not self.algorithm_step.winfo_manager():
                self.algorithm_step.pack(fill="x", pady=(6, 0), before=self.export_step)
        else:
            self.algorithm_step.pack_forget()
        if layout in ("fit", "canvas_fit") and resample == "pixel":
            if not self.pixel_row.winfo_manager():
                self.pixel_row.pack(fill="x", pady=(8, 0))
        else:
            self.pixel_row.pack_forget()
        info = self.current_info
        self.grid_canvas_button.configure(state="normal" if not self.busy and info else "disabled")
        self.subject_canvas_button.configure(state="normal" if not self.busy and info and info.subject else "disabled")

    def set_canvas_size(self, size):
        if self.layout.get() == "保持原画布":
            self.layout.set("主体等比例缩放 · 改画布")
        self.canvas_width.set(str(size))
        self.canvas_height.set(str(size))

    def use_grid_canvas(self):
        info = self.current_info
        if not self.busy and info:
            if LAYOUTS[self.layout.get()] not in ("keep", "fit", "canvas_fit"):
                self.layout.set("主体不缩放 · 改画布")
            self.canvas_width.set(str(info.grid[0]))
            self.canvas_height.set(str(info.grid[1]))

    def use_subject_canvas(self):
        info = self.current_info
        if not self.busy and info and info.subject:
            self.layout.set("主体不缩放 · 改画布")
            self.canvas_width.set(str(info.subject[0]))
            self.canvas_height.set(str(info.subject[1]))

    def update_destination(self):
        self.destination_label.configure(text=self.output_dir.get() or "原图旁的 perfect_pixel_output 文件夹")

    def choose_output(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(title="选择统一输出位置", initialdir=self.initial_dir())
        if folder:
            self.output_dir.set(str(Path(folder).resolve()))
            self.update_destination()

    def default_output(self):
        self.output_dir.set("")
        self.update_destination()

    def initial_dir(self):
        path = self.settings.get("last_dir", str(HERE))
        return path if isinstance(path, str) and Path(path).is_dir() else str(HERE)

    def add_files(self):
        if self.busy:
            return
        chosen = filedialog.askopenfilenames(title="选择图片", initialdir=self.initial_dir(),
                   filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"), ("所有文件", "*.*")])
        if chosen:
            self.settings["last_dir"] = str(Path(chosen[0]).parent)
            added, skipped = self.append_files(chosen)
            self.status.configure(text=f"添加 {added} 张，跳过重复或不支持的文件 {skipped} 张")

    def append_files(self, paths):
        added = skipped = 0
        for value in paths:
            path = Path(value).resolve()
            key = path_key(path)
            if key in self.keys or path.suffix.lower() not in SUPPORTED:
                skipped += 1
                continue
            self.keys.add(key)
            self.files.append(path)
            self.tree.insert("", "end", iid=key, values=(path.name, "待处理", "—"))
            added += 1
        self.refresh_count()
        if added and not self.tree.selection():
            self.tree.selection_set(path_key(self.files[0]))
        return added, skipped

    def add_folder(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(title="选择文件夹（含子文件夹，跳过输出目录）", initialdir=self.initial_dir())
        if not folder:
            return
        self.settings["last_dir"] = folder
        self.set_busy(True)
        self.status.configure(text="正在扫描文件夹…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        output = Path(self.output_dir.get()) if self.output_dir.get() else None
        def scan():
            try:
                paths, warnings = scan_folder(folder, output, self.cancel_event)
                self.events.put(("scan_done", paths, warnings, self.cancel_event.is_set()))
            except Exception as exc:
                logging.exception("Folder scan failed")
                self.events.put(("scan_error", str(exc)))
        self.worker = threading.Thread(target=scan, daemon=True)
        self.worker.start()

    def refresh_count(self):
        self.count.configure(text=f"已选择 {len(self.files)} 张图片" if self.files else "尚未选择图片")

    def clear(self):
        if self.busy:
            return
        self.files.clear()
        self.keys.clear()
        self.results.clear()
        self.tree.delete(*self.tree.get_children())
        self.refresh_count()
        self.show_selection()

    def remove_selected(self):
        if self.busy:
            return
        selected = set(self.tree.selection())
        self.files = [p for p in self.files if path_key(p) not in selected]
        self.keys.difference_update(selected)
        for key in selected:
            self.results.pop(key, None)
            self.tree.delete(key)
        self.refresh_count()
        self.show_selection()

    def select_all(self, event):
        if event.widget == self.tree:
            self.tree.selection_set(self.tree.get_children())
            return "break"

    def set_busy(self, value):
        self.busy = value
        if value:
            self.cancel_event.clear()
            self.invalidate_preview()
        for widget, state in self.controls:
            widget.configure(state="disabled" if value else state)
        self.cancel_button.configure(state="normal" if value else "disabled")
        self.update_grid_state()

    def get_options(self, for_preview=False):
        layout = LAYOUTS[self.layout.get()]
        try:
            alpha_threshold = int(self.alpha_threshold.get())
        except ValueError:
            raise ValueError("透明噪点阈值必须是 0～254 的整数；0 表示关闭") from None
        canvas = None
        if layout in ("keep", "fit", "canvas_fit"):
            try:
                canvas = int(self.canvas_width.get()), int(self.canvas_height.get())
            except ValueError:
                raise ValueError(f"画布宽、高必须是 1～{canvas_limit(layout)} 的整数") from None
        options = Options(method=METHODS[self.method.get()],
                          output_dir=Path(self.output_dir.get()).resolve() if self.output_dir.get() and not for_preview else None,
                          layout=layout, canvas=canvas, resample=RESAMPLERS[self.resample.get()],
                          palette_size=PALETTES[self.palette.get()], detail=DETAILS[self.detail.get()],
                          direct=self.mode.get() == "原图直接转换", alpha_threshold=alpha_threshold)
        options.validate()
        return options

    def start(self):
        if self.busy:
            return
        if not self.files:
            messagebox.showinfo("先选图片", "请先添加一张或多张图片。", parent=self)
            return
        try:
            options = self.get_options()
        except ValueError as exc:
            messagebox.showerror("选项有误", str(exc), parent=self)
            return
        self.save_settings()
        files = tuple(self.files)
        self.set_busy(True)
        self.results.clear()
        self.clear_details()
        for path in files:
            self.tree.item(path_key(path), values=(path.name, "等待中", "—"), tags=())
        self.show_selection()
        self.progress.configure(mode="determinate", maximum=len(files), value=0)
        self.status.configure(text=f"开始处理，共 {len(files)} 张…")
        self.worker = threading.Thread(target=self.process, args=(files, options), daemon=True)
        self.worker.start()

    def process(self, files, options):
        succeeded = failed = processed = 0
        for index, path in enumerate(files, 1):
            if self.cancel_event.is_set():
                break
            self.events.put(("working", path, index, len(files)))
            try:
                result = process_file(path, options)
                succeeded += 1
                self.events.put(("result", path, result, None, index))
            except Exception as exc:
                failed += 1
                logging.exception("Processing failed: %s", path)
                self.events.put(("result", path, None, str(exc), index))
            processed += 1
        self.events.put(("done", succeeded, failed, len(files) - processed))

    def cancel(self):
        if self.busy:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status.configure(text="正在取消…当前图片处理完后停止，已生成的结果会保留")

    def clear_details(self):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")

    def add_detail(self, message):
        self.details.configure(state="normal")
        self.details.insert("end", message + "\n")
        self.details.see("end")
        self.details.configure(state="disabled")

    def poll(self):
        if self.closing:
            if self.worker is None or not self.worker.is_alive():
                self.destroy()
                return
        # Bound work per tick so a large batch cannot starve the Tk event loop.
        for _ in range(80):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if not self.closing:
                self.handle_event(event)
        self.poll_id = self.after(80, self.poll)

    def destroy(self):
        self.closing = True
        self.invalidate_preview()
        if getattr(self, "poll_id", None):
            self.after_cancel(self.poll_id)
            self.poll_id = None
        if hasattr(self, "preview_pool"):
            self.preview_pool.shutdown(wait=False, cancel_futures=True)
        super().destroy()

    def handle_event(self, event):
        kind, *args = event
        if kind == "working":
            path, index, total = args
            self.tree.item(path_key(path), values=(path.name, "处理中", "—"))
            if not self.cancel_event.is_set():
                self.status.configure(text=f"处理中 {index}/{total}：{path.name}")
        elif kind == "result":
            path, result, error, index = args
            key = path_key(path)
            self.results[key] = result if result else error
            if result:
                self.last_output = result.output.parent
                self.tree.item(key, values=(path.name, "成功", f"{result.width}×{result.height}"), tags=("ok",))
                self.add_detail(f"成功 · {path.name} → {result.width}×{result.height} · {result.seconds:.2f}s\n"
                                f"  {info_text(result.info)}\n  {result.output}")
            else:
                self.tree.item(key, values=(path.name, "失败", "—"), tags=("error",))
                self.add_detail(f"失败 · {path}\n  {error}")
            self.progress.configure(value=index)
            if key in self.tree.selection():
                self.show_selection()
        elif kind == "done":
            succeeded, failed, remaining = args
            for path in self.files:
                key = path_key(path)
                if key not in self.results:
                    self.tree.item(key, values=(path.name, "已取消", "—"))
            self.set_busy(False)
            text = f"{'已取消' if remaining else '完成'}：成功 {succeeded} 张，失败 {failed} 张，未处理 {remaining} 张"
            self.status.configure(text=text)
            self.add_detail(text)
            self.show_selection()
        elif kind in ("scan_done", "scan_error"):
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self.set_busy(False)
            if kind == "scan_done":
                paths, warnings, cancelled = args
                added, skipped = self.append_files(paths)
                self.status.configure(text=f"{'扫描已取消' if cancelled else '扫描完成'}：添加 {added} 张，跳过重复 {skipped} 张，目录访问失败 {len(warnings)} 处")
                for warning in warnings:
                    self.add_detail("扫描提醒 · " + warning)
            else:
                self.status.configure(text="扫描失败")
                self.add_detail("扫描失败 · " + args[0])
        elif kind == "preview":
            token, original, output, output_title, *extra = args
            if token != self.preview_token:
                return
            self.current_info = extra[0] if extra else None
            self.subject_caption.configure(text=info_text(self.current_info))
            try:
                scale_text, attention = scaling_text(self.current_info, self.get_options(for_preview=True))
            except ValueError:
                scale_text, attention = "缩放提示：请先修正参数。", False
            self.scale_caption.configure(text=scale_text, foreground="#9b4f00" if attention else "#555")
            self.update_grid_state()
            self.photos.clear()
            for value, view, caption, title in (
                (original, self.original_view, self.original_caption, "原图"),
                (output, self.output_view, self.output_caption, output_title),
            ):
                if isinstance(value, tuple):
                    encoded, dimensions = value
                    photo = tk.PhotoImage(data=encoded, master=self)
                    self.photos.append(photo)
                    view.configure(image=photo, text="")
                    caption.configure(text=f"{title} · {dimensions}")
                else:
                    view.configure(image="", text=value)
                    caption.configure(text=title)

    def invalidate_preview(self):
        self.preview_token += 1
        self.preview_cancel.set()
        if self.preview_future:
            self.preview_future.cancel()
        if self.preview_after_id:
            self.after_cancel(self.preview_after_id)
            self.preview_after_id = None

    def preview_options_changed(self, *_):
        self.update_grid_state()
        self.show_selection()

    def show_selection(self, _=None):
        if self.closing:
            return
        self.invalidate_preview()
        self.current_info = None
        self.subject_caption.configure(text=info_text(None))
        self.scale_caption.configure(text=scaling_text(None, None)[0], foreground="#555")
        self.update_grid_state()
        token = self.preview_token
        selected = self.tree.selection()
        if not selected:
            self.original_view.configure(image="", text="选择图片查看预览")
            self.output_view.configure(image="", text="选择图片后自动预览")
            self.original_caption.configure(text="原图")
            self.output_caption.configure(text="实时预览")
            self.photos.clear()
            return
        self.output_caption.configure(text="已保存结果" if self.busy else "实时预览 · 更新中…")
        self.output_view.configure(image="", text="正在更新预览…")
        # Collapse rapid typing and preset changes into one computation.
        self.preview_after_id = self.after(350, self.build_preview, token, selected[0])

    def build_preview(self, token, key):
        self.preview_after_id = None
        if self.closing or token != self.preview_token:
            return
        self.preview_cancel = threading.Event()
        cancelled = self.preview_cancel
        path = Path(key)
        result = self.results.get(key)
        busy = self.busy
        options = None
        option_error = None
        if not busy:
            try:
                options = self.get_options(for_preview=True)
            except (ValueError, KeyError) as exc:
                option_error = str(exc)
        view_w = min(400, max(140, self.original_view.winfo_width()))
        view_h = min(180, max(80, self.original_view.winfo_height()))
        def render():
            if cancelled.is_set():
                return
            if options is not None:
                try:
                    values = self.preview_renderer.render(path, options, view_w, view_h, cancelled)
                except Exception as exc:
                    values = (f"无法预览：{exc}", f"无法预览：{exc}", None)
                if values is not None and not cancelled.is_set():
                    original, output, info = values
                    self.events.put(("preview", token, original, output, "实时预览", info))
                return
            try:
                original = thumbnail(path, view_w, view_h)
            except Exception as exc:
                original = f"无法预览：{exc}"
            output = f"参数有误：{option_error}" if option_error else "批处理中，完成后显示"
            if busy and isinstance(result, str):
                output = result
            elif busy and result is not None:
                try:
                    output = thumbnail(result.output, view_w, view_h)
                except Exception as exc:
                    output = f"无法预览结果：{exc}"
            if not cancelled.is_set():
                info = result.info if busy and result is not None and not isinstance(result, str) else None
                self.events.put(("preview", token, original, output, "已保存结果" if busy else "实时预览", info))
        self.preview_future = self.preview_pool.submit(render)

    def open_output(self):
        selected = self.tree.selection()
        result = self.results.get(selected[0]) if selected else None
        if result is not None and not isinstance(result, str):
            dest = result.output.parent
        else:
            dest = self.last_output
        if dest is None or not dest.is_dir():
            messagebox.showinfo("暂无输出", "处理成功后可打开输出文件夹。", parent=self)
            return
        try:
            os.startfile(str(dest))
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc), parent=self)

    def save_settings(self):
        data = dict(self.settings)
        data.pop("width", None)
        data.pop("height", None)
        data.pop("scale", None)
        data.update(mode=self.mode.get(), method=self.method.get(),
                    layout=self.layout.get(), resample=self.resample.get(),
                    palette=self.palette.get(), detail=self.detail.get(),
                    output_dir=self.output_dir.get(), geometry=f"{self.winfo_width()}x{self.winfo_height()}")
        for key, variable in (("canvas_width", self.canvas_width), ("canvas_height", self.canvas_height)):
            try:
                data[key] = max(1, min(canvas_limit(LAYOUTS[self.layout.get()]), int(variable.get())))
            except ValueError:
                data[key] = 32
        try:
            data["alpha_threshold"] = max(0, min(254, int(self.alpha_threshold.get())))
        except ValueError:
            data["alpha_threshold"] = 1
        try:
            temp = SETTINGS.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(SETTINGS)
            self.settings = data
        except OSError as exc:
            logging.warning("Settings could not be saved: %s", exc)
            self.add_detail(f"设置未能保存 · {exc}")

    def close(self):
        if self.closing:
            return
        self.save_settings()
        self.closing = True
        self.invalidate_preview()
        self.preview_pool.shutdown(wait=False, cancel_futures=True)
        self.cancel_event.set()
        if self.busy and self.worker is not None and self.worker.is_alive():
            self.set_busy(True)
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status.configure(text="正在安全退出…当前图片处理完后关闭")
        else:
            self.destroy()

    def report_callback_exception(self, exc_type, exc, traceback):
        logging.error("UI callback failed", exc_info=(exc_type, exc, traceback))
        messagebox.showerror("界面出错", f"{exc}\n详情已记录到 perfect_pixel.log。", parent=self)


if __name__ == "__main__":
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
        HERE / "perfect_pixel.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
    App().mainloop()
