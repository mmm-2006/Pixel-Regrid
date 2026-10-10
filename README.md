# Perfect Pixel · 像素画整理

本地桌面工具，用来还原 AI 像素风图片的色块网格，调整主体和画布，并批量导出指定尺寸的 PNG。

界面使用 **pywebview + Vue 3**。Windows 下由 WebView2 渲染独立桌面窗口；前端资源随程序存放在本地，不使用 CDN，不上传图片。图像处理使用 Python、NumPy、OpenCV 和 perfect-pixel。

## 功能

- 图片拖入、文件选择和递归文件夹扫描；自动跳过输出目录和重复路径。
- 原图与结果并排预览、滚轮缩放、拖动平移、实际像素显示、像素网格和透明背景。
- 网格还原、物品图标、方块贴图预设；16、32、64、128 像素尺寸快捷选择。
- 主体裁边、主体等比例缩放、整图等比例缩放、铺满画布和保留主体大小。
- 最近邻、结构保护和 k-centroid 三种缩放算法。
- 导出选中或全部图片，处理进度、取消、错误记录；原图保留，重名结果自动编号。

## 从源码运行（Windows）

需要 Python 3.13、Node.js 22.12 或更高版本，以及 [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)。Node.js 只用于前端开发和构建。

在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location frontend
npm ci
npm run build
Set-Location ..
.\.venv\Scripts\python.exe launch.py
```

之后可直接双击 `启动PerfectPixel.bat`。启动不会联网安装依赖；修改前端后需要重新执行 `npm run build`。`frontend/dist` 是生成文件，不提交到 Git。

旧 Tkinter 界面暂时保留供回退和回归测试使用：

```powershell
.\.venv\Scripts\python.exe launch.py --legacy
```

## 使用

添加图片后，先选择用途预设，再检查实时预览。预设会调整相关参数，不会自动保存输出。

“自动识别网格”用于具有一致色块网格的图片；识别不准确时可选择“原图直接转换”。识别得到的像素格数和最终画布尺寸是不同的概念，指定 32×32 画布不会强制重新识别成 32×32 网格。

默认输出到每张原图旁的 `perfect_pixel_output` 目录，也可以选择统一保存位置。旧版参数会自动迁移，设置保存在 `perfect_pixel_settings.json`，错误写入 `perfect_pixel.log`。

Ctrl 点击多选，Shift 点击连续选择。Ctrl+O 添加图片，Ctrl+A 全选，Delete 移除列表里的选中项；F 适应窗口，1 显示实际像素。移除列表项不会删除原图。

并排预览各自以适应窗口为基准同步缩放和平移；选择 1:1 后，两边都按实际像素显示。超大图片的预览最长边限制为 2048 像素并明确标注，导出仍使用完整输入。像素网格只在每个像素显示足够大且预览未抽样时显示。

批处理使用点击导出时的参数快照。取消和退出会等待当前图片保存完成，已经生成的文件会保留。详细算法说明见 `使用说明.txt`。

## 开发与测试

```powershell
# 使用项目内临时目录，兼容受限环境
$env:TEMP = Join-Path (Get-Location) '.test_tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

Set-Location frontend
npm test
npm run build
```

`npm run dev` 可用于浏览器内检查前端样式；文件对话框、图片处理等功能需要 pywebview 桌面桥接，不在普通浏览器中提供。

项目结构：

```text
launch.py                 启动、日志与错误提示
pixel_desktop.py          桌面窗口、文件操作、预览缓存与任务桥接
pixel_ui_shared.py        共用选项名称与图片说明
pixel_core.py             图像处理与安全输出
pixel_retarget.py         结构保护缩放
pixel_k_centroid.py       局部主色缩放
frontend/src/             Vue 界面、预览画布与样式
tests/                    算法、旧界面与桌面桥接测试
```

## Windows 打包

提供 `build_windows.ps1` 作为源码打包入口。它先构建前端，再使用 PyInstaller 生成目录形式的应用，保留 WebView2 和 Python 的必要资源。需要先在 `.venv` 中安装 PyInstaller：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\build_windows.ps1
```

生成目录为 `dist/PerfectPixel`，发布时应打包整个目录。用户无需安装 Python、Node.js 或 npm，但 Windows 需要 WebView2 Runtime。此打包脚本需在发布前于干净 Windows 环境验证；源码运行与测试和发布包验证分别进行。

第三方许可与来源见 `THIRD_PARTY_NOTICES.md`。项目自身的开源许可证需要在正式发布前确定。
