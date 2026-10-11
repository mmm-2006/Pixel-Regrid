# 开发指南

Pixel Regrid 保留两套实现，共用 Vue 界面：JavaScript 版通过 Tauri 提供桌面接口，
图片算法在 Worker 中执行；Python 版通过 pywebview 调用 NumPy、OpenCV 和 perfect-pixel。

## 环境与目录

Windows 开发需要 Node.js 22.12 或更高版本和 WebView2 Runtime。
JavaScript 桌面构建还需要 Rust、Visual Studio C++ 构建工具及 Windows SDK；Python 版使用 Python 3.13。

| 目录 | 内容 |
|---|---|
| `frontend/src/` | Vue 界面、JavaScript 算法与桌面桥接 |
| `frontend/src-tauri/` | Rust 文件接口、图片编解码与桌面外壳 |
| `python/` | Python 算法、桌面接口与回归测试 |
| `scripts/` | 构建、打包、对照与展示图生成脚本 |
| `test-images/` | 测试原图和已有处理示例，`samples.json` 指定算法对照样本 |
| `docs/` | 使用说明、算法评估与发布记录 |
| `dist/` | 本地构建产物，不提交到 Git |

## JavaScript 版

在仓库根目录执行：

```powershell
Set-Location frontend
npm ci
npm run desktop:dev
```

`npm run dev` 仅用于浏览器内调试界面，完整文件操作需在桌面版中验证。
生成发行目录和版本化 ZIP：

```powershell
Set-Location ..
.\scripts\build_javascript.ps1
.\scripts\package_release.ps1
```

程序位于 `dist/PixelRegrid-JS/`，ZIP 和 `SHA256SUMS.txt` 位于 `dist/`。
Rust 官方源下载较慢时，可对本次构建使用 `build_javascript.ps1 -UseRustMirror`。
打包脚本会检查版本号，并拒绝覆盖已有的版本化发布目录和 ZIP。
更多桌面接口说明与已知限制见 [JavaScript 指南](JAVASCRIPT_PROTOTYPE.md)。

## Python 版

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python/requirements.txt
Set-Location frontend
npm ci
npm run build
Set-Location ..
.\.venv\Scripts\python.exe launch.py
```

也可双击 `启动PixelRegrid-Python.bat`。前端修改后需重新执行 `npm run build`。
旧 Tkinter 界面可通过 `launch.py --legacy` 启动。
PyPI 下载较慢时，可在安装命令末尾添加 `--index-url https://pypi.tuna.tsinghua.edu.cn/simple`。

Python 打包：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\scripts\build_windows.ps1
```

分发时需携带整个 `dist/PixelRegrid-Python/`，该版本的发布包尚需独立验证。

## 测试

在仓库根目录执行，以下命令不启动桌面窗口：

```powershell
.\.venv\Scripts\python.exe scripts/test_python.py
.\.venv\Scripts\python.exe scripts/compare_javascript.py
node frontend/scripts/compare.mjs
Set-Location frontend
npm test
npm run build
Set-Location src-tauri
cargo test --locked --release --features custom-protocol
```

算法对照使用构造样例、自制扰动图，以及 `test-images/samples.json` 中的四张原图。
详细结果写入 `prototype-results/`，缺少样本时会提示并跳过。
仓库保留已有处理示例，新生成的 `perfect_pixel_output/` 文件默认忽略。
完整 Python 测试还包含会打开 Tkinter 窗口的 `test_gui.py`，可按需手动运行：

```powershell
Set-Location python
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

GitHub Actions 配置位于 [ci.yml](../.github/workflows/ci.yml)。
历史测试结果见 [对照报告](JAVASCRIPT_EVALUATION.md) 和 [发布验证](RELEASE_VALIDATION.md)。

## 设置与展示素材

Python 的设置和日志位于仓库根目录，沿用 `perfect_pixel_settings.json` 和 `perfect_pixel.log`。
JavaScript 使用应用数据目录，标识为 `local.pixelregrid.desktop`；新设置不存在时读取旧实验版设置。
设置、日志、依赖目录和构建产物均不提交到 Git。

README 效果图由 `scripts/create_demo.py` 生成，自制扰动样例经过实际 Python 算法处理。
界面图由 `scripts/capture_readme.py` 在无头浏览器中渲染真实 Vue 前端，使用隔离的演示桥接数据。
更新展示图需先安装 Python 依赖并构建前端；界面图生成还需要 Chrome 或 Edge。
