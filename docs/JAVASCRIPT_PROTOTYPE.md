# JavaScript 轻量化实验

JavaScript 版从 `codex/javascript-prototype` 合并到主分支，与 Python 版并存。
Python 源码位于 `python/`，原来的 `launch.py` 和双击启动方式保留。

Vue 界面继续使用。Tauri 提供窗口、文件对话框、图片格式解码、PNG 编码、
扫描目录和安全保存；网格检测、取色、结构保护、k-centroid 和画布布局在
JavaScript Web Worker 中运行。发行包不包含 Python、NumPy、OpenCV 或 Node.js，
Windows 使用系统 WebView2。

## 开发和构建

开发环境需要 Node.js、Rust、Visual Studio C++ 构建工具、Windows SDK。

```powershell
cd frontend
npm ci
npm run desktop:dev
npm run desktop:build
```

根目录执行 `scripts/build_javascript.ps1` 会构建并将 EXE 复制到 `dist/PixelRegrid-JS`。
首次构建会下载 Rust 依赖；官方源无法连接时可使用
`./scripts/build_javascript.ps1 -UseRustMirror`，仅这次构建使用 rsproxy，不修改全局配置。
实验版偏好设置写入独立的应用数据目录，不读写 Python 版设置。
应用标识为 `local.pixelregrid.desktop`；新设置文件不存在时，会读取旧标识
`local.perfectpixel.javascript-prototype` 下的设置，后续保存到新目录。

## 自动验证

以下测试均不启动或自动操作桌面窗口。

```powershell
# 根目录，Python 仅用于生成现有实现的对照数据
.\.venv\Scripts\python.exe scripts/compare_javascript.py
node frontend/scripts/compare.mjs

cd frontend
npm test
cd src-tauri
cargo test --release --features custom-protocol
```

对照覆盖透明裁边、画布布局、最近邻分数尺寸、自动/指定网格、中心/中位数/多数色取样、
颜色预算、三种缩放、全透明图片、无效尺寸，以及随源码提供的 `docs/assets/demo-original.png`。
本机存在测试图片时，还会读取 `test-images/samples.json` 指定的四张 PNG；CI 不依赖这些个人图片。
原图只读，像素参考与详细结果保存在被 Git 忽略的 `prototype-results/`。

JavaScript 单元测试还覆盖 FFT 的任意长度变换、后台线程缓存及像素数据传输、
批处理遇错继续、参数快照、取消和关闭等待当前保存。Rust 测试核对 PNG 编解码
是否保留半透明和完全透明像素的 RGB，并拒绝读取未导入的文件。

## 实验限制

- k-centroid 使用确定性的双聚类实现，未复制 Pillow MAXCOVERAGE 的初始化和量化细节。
  多数色取样同样采用确定性聚类，不能保证与 OpenCV 聚类逐像素一致。
- Lab 颜色转换使用标准 sRGB/D65 计算，和 OpenCV 8 位查表计算存在细微差异，
  可能改变调色板选色和局部投票；对照报告会保留这些差异。
- 纯 JavaScript 大图 FFT 当前比 Python/NumPy 慢。已缓存还原网格，改画布尺寸不必重复识别，
  但首次识别仍需要优化。识别取消通过终止 Worker 生效，导出取消等待当前图片完成。
- 实验版自动网格识别最多处理 400 万像素，直接转换的读取上限仍为 3200 万像素。
- 图片按导入后的读取缓存使用；外部修改原图后应移除并重新导入。
- Rust 格式解码与 OpenCV 的 JPEG、WebP、TIFF、色彩配置文件处理仍需进一步对照。
- 用户已进行桌面手动试用并反馈没有发现问题；编译与算法测试不代表完整的发布兼容性验证。

JavaScript 版继续保留实验限制，不替代 Python 版。测量结果见
[JAVASCRIPT_EVALUATION.md](JAVASCRIPT_EVALUATION.md)。
