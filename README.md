# Perfect Pixel · 像素画整理

本地桌面工具，用来还原 AI 像素风图片的色块网格，调整主体和画布，并批量导出指定尺寸的 PNG。
界面简约，图片在本机处理，前端资源随程序存放，不使用 CDN。

## 两套桌面版本

主分支同时保留两套实现，共用 Vue 3 界面，独立启动、独立设置。

| 版本 | 实现 | 用途与启动方式 |
|---|---|---|
| Python 版 | pywebview + NumPy/OpenCV/perfect-pixel | 保留原有算法；双击 `启动PerfectPixel.bat` |
| JavaScript 版 | Tauri + Rust 文件/图片接口 + JavaScript Worker | 轻量化实现；双击 `启动JavaScript版.bat`（需已有构建产物） |

Windows 两套版本都需要 [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)，
打开独立桌面窗口，无需手动打开浏览器。JavaScript 版运行时不需要 Python 或 Node.js。
两套算法部分结果和性能仍有差异，见 [对照报告](docs/JAVASCRIPT_EVALUATION.md)。

## 功能

- 图片拖入、文件选择和递归文件夹扫描；自动跳过输出目录和重复路径。
- 原图与结果并排预览、滚轮缩放、拖动平移、实际像素显示、像素网格和透明背景。
- 网格还原、物品图标、方块贴图预设；16、32、64、128 像素尺寸快捷选择。
- 主体裁边、主体等比例缩放、整图等比例缩放和保留主体大小。
- 最近邻、结构保护和 k-centroid 三种缩放算法。
- 导出选中或全部图片，处理进度、取消、错误记录；原图保留，重名结果自动编号。

## 目录

```text
python/                   Python 源码、依赖清单与回归测试
frontend/src/             共用 Vue 界面，以及 JavaScript 图片算法
frontend/src-tauri/       Tauri/Rust 桌面外壳
frontend/tests/           JavaScript 自动测试
scripts/                  两套构建脚本、Python 对照数据生成脚本
docs/                     使用说明、JavaScript 构建指南与对照报告
图片测试/                 本机测试原图与输出，不提交图片到 Git
dist/                     两套版本的构建产物，不提交到 Git
launch.py                 原有 Python 启动命令的兼容入口
启动PerfectPixel.bat       原有 Python 双击启动入口
启动JavaScript版.bat       JavaScript 双击启动入口
```

原来的 `1/`、`2/` 已合并到 `图片测试/`，已有输出保留在其中的 `perfect_pixel_output/`。
本机虚拟环境仍位于 `.venv/`，Python 设置和日志仍保存在项目根目录，已有参数无需迁移。

## Python 版：源码运行

需要 Python 3.13、Node.js 22.12 或更高版本，以及 WebView2。Node.js 只用于前端开发和构建。
在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python/requirements.txt
Set-Location frontend
npm ci
npm run build
Set-Location ..
.\.venv\Scripts\python.exe launch.py
```

之后可直接双击 `启动PerfectPixel.bat`。启动不会联网安装依赖；修改前端后需要重新执行
`npm run build`。也可以直接运行 `python/launch.py`。
旧 Tkinter 界面保留供回退与手动回归使用：

```powershell
.\.venv\Scripts\python.exe launch.py --legacy
```

Python 打包入口：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\scripts\build_windows.ps1
```

生成 `dist/PerfectPixel/`，发布时需要整个目录。用户无需安装 Python、Node.js 或 npm，
但需要 WebView2。Python 发布包仍需在干净 Windows 环境验证。

## JavaScript 版：源码运行与打包

开发需要 Node.js、Rust、Visual Studio C++ 构建工具和 Windows SDK。

```powershell
Set-Location frontend
npm ci
npm run desktop:dev
```

打包时从项目根目录执行：

```powershell
.\scripts\build_javascript.ps1
```

生成 `dist/PerfectPixel-JS/PerfectPixel-JS.exe`，无需携带 Python 环境。
构建选项、测试方法和已知限制见 [JavaScript 指南](docs/JAVASCRIPT_PROTOTYPE.md)。

## 使用

添加图片后，先选择用途预设，再检查实时预览。预设会调整相关参数，不会自动保存输出。

“自动识别网格”用于具有一致色块网格的图片；识别不准确时可选择“原图直接转换”。
识别得到的像素格数和最终画布尺寸是不同的概念，指定 32×32 画布不会强制识别成 32×32 网格。

默认输出到每张原图旁的 `perfect_pixel_output/`，也可以选择统一保存位置。
Python 设置保存在根目录 `perfect_pixel_settings.json`，错误写入 `perfect_pixel.log`；
JavaScript 设置保存在独立的应用数据目录。

Ctrl 点击多选，Shift 点击连续选择。Ctrl+O 添加图片，Ctrl+A 全选，Delete 移除列表选中项；
F 适应窗口，1 显示实际像素。移除列表项不会删除原图。

并排预览同步缩放和平移。超大图片预览最长边限制为 2048 像素并标注，导出仍使用完整输入。
像素网格只在放大足够且预览未抽样时显示。批处理使用点击导出时的参数快照，取消和退出
会等待当前图片保存完成，已经生成的文件保留。详细算法说明见 [使用说明](docs/使用说明.txt)。

## 开发与测试

从项目根目录执行 Python 完整回归测试；其中 `test_gui.py` 会打开旧 Tkinter 测试窗口，请按需手动运行：

```powershell
$env:TEMP = Join-Path (Get-Location) '.test_tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
Push-Location python
try { ..\.venv\Scripts\python.exe -m unittest discover -s tests -v }
finally { Pop-Location }
```

JavaScript 自动测试和界面构建：

```powershell
Set-Location frontend
npm test
npm run build
```

`npm run dev` 可用于浏览器内检查界面样式；完整文件操作需要桌面桥接。
跨版本算法对照见 [本地图片测试说明](图片测试/README.md)。
第三方许可与来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
