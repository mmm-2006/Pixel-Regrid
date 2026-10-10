# JavaScript 迁移实验结果

日期：2026-10-11。分支：`codex/javascript-prototype`。

## 判断

Tauri + Vue + JavaScript Worker 的轻量化路线可构建成独立 Windows EXE，
不携带 Python、NumPy、OpenCV 或 Node.js；继续依赖系统 WebView2。
包体目标已验证，算法等价性和性能优化尚未完成，本分支暂不替换 main。

## 构建和测试

Windows x64 的 EXE 实测为 4,044,800 字节（约 4.04 MB / 3.86 MiB）。
Vue 页面和 Worker 已嵌入 EXE。外带文档及依赖许可证另占约 2.4 MB 文本空间；
完整测试 ZIP（含 EXE、文档和许可证）实测约 1.97 MB。
PE 导入表只出现 Windows 系统库，没有 Python、OpenCV 或 Node.js 动态库。

- Windows x64 release 构建成功，启用 LTO 和体积优化。
- JavaScript 测试：14 项通过，覆盖算法、真正的 Worker 消息/缓存传输、以及模拟原生接口的批处理流程。
- Rust 测试：3 项通过，覆盖 PNG 原始 RGBA 编解码、读取授权、重名输出不覆盖源图或旧结果。
- Python 对照：52 个案例（40 个构造案例、4 张真实图片各 3 种算法）。
  39 个案例逐像素和网格/恢复状态完全一致，3 个错误场景均被拒绝；10 个案例有差异。
  基础功能的必需对照全部通过；差异案例只用于记录实验结果，没有被声明为等价性通过。
- 4 张真实图片均为 1254×1254；在这些样本上，新旧网格尺寸和最近邻结果均一致。
- 原生窗口、文件对话框、拖放和实际 WebView2 Worker 尚未人工验证。

## 真实图片对照

下表按整个输出画布计算。相同透明像素也参与百分比；平均差值按全部 RGBA 通道计算。
高匹配比例不能排除少量关键细节不同，原始像素数据保存在本机忽略目录。

| 图片与算法 | RGBA 像素完全一致 | Alpha 完全一致 | 平均通道绝对差值（0～255） |
|---|---:|---:|---:|
| 1-advanced_enchanting_table_side_diamond_ai-nearest | 100.00% | 100.00% | 0.000 |
| 1-advanced_enchanting_table_side_diamond_ai-pixel | 26.17% | 100.00% | 1.007 |
| 1-advanced_enchanting_table_side_diamond_ai-k-centroid | 100.00% | 100.00% | 0.000 |
| 1-advanced_enchanting_table_top_diamond_ai-nearest | 100.00% | 100.00% | 0.000 |
| 1-advanced_enchanting_table_top_diamond_ai-pixel | 42.97% | 100.00% | 0.880 |
| 1-advanced_enchanting_table_top_diamond_ai-k-centroid | 100.00% | 100.00% | 0.000 |
| 2-ChatGPT 图像 2026年10月10日 20_53_16-nearest | 100.00% | 100.00% | 0.000 |
| 2-ChatGPT 图像 2026年10月10日 20_53_16-pixel | 88.18% | 100.00% | 0.364 |
| 2-ChatGPT 图像 2026年10月10日 20_53_16-k-centroid | 96.39% | 99.90% | 0.112 |
| 2-ChatGPT 图像 2026年10月10日 22_17_04-nearest | 100.00% | 100.00% | 0.000 |
| 2-ChatGPT 图像 2026年10月10日 22_17_04-pixel | 89.16% | 100.00% | 0.575 |
| 2-ChatGPT 图像 2026年10月10日 22_17_04-k-centroid | 94.34% | 100.00% | 0.266 |

差异主要来自 OpenCV 8 位 Lab 转换/选色与 JavaScript 标准 Lab 计算不同，
以及 k-centroid 未复刻 Pillow MAXCOVERAGE 的初始化。多数色算法也使用不同的
确定性初始化，此次样本一致不能证明所有图片都一致。

## 性能

单次 Node.js 算法计时，没有宣称代表 WebView2 的完整预览或导出耗时。
PNG 解码、编码、原生通信、界面渲染均不计入算法时间，Python/JS 计时未做统计重复。

在第一张 1254×1254 真实图片上，Node Worker 的首次识别加最近邻输出约
1273 ms；同一张图只改尺寸、复用还原网格时约
0.09～0.46 ms。
包括 Worker 收发在内的后续请求约 5 ms，仍不含原生解码和 PNG 编码。
Python 的同图片完整处理约 118 ms，说明当前 JS 首次识别明显较慢。

## 后续需要解决

1. 对齐调色板和聚类结果，或明确选择新的算法行为，并补充更多图片对照。
2. 优化纯 JS FFT/梯度计算，评估首次识别的实际 WebView2 性能。
3. 手动核对桌面导入、拖放、取消、关闭、保存位置及输出 PNG。
4. 对照 JPEG/WebP/TIFF、16 位图片和色彩配置文件的解码行为。

复现步骤见 [JAVASCRIPT_PROTOTYPE.md](JAVASCRIPT_PROTOTYPE.md)。
详细机器可读结果在 `prototype-results/comparison.json` 和 `worker-benchmark.json`。
