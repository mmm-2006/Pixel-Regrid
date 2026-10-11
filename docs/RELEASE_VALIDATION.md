# v0.1.0-beta.1 发布验证

验证日期：2026-10-11。目标为 Windows x64 JavaScript 桌面包；Python 实现继续保留在源码中。

## 环境与方法

- Windows 11 家庭版中文版，10.0.26100，x64。
- Python 3.13.0、Node.js 24.14.1、Rust/Cargo 1.98.1，已安装 Visual Studio C++ 构建工具与 Windows SDK。
- 从 Git 暂存区导出独立源码目录，未复制现有 `.venv`、`node_modules`、`target`、构建产物或设置。
  当次验证未包含 `test-images/` 样本（当时尚未纳入 Git）。
- 新建 Python 虚拟环境；官方 PyPI 下载发生 SSL 超时，改用清华 PyPI 镜像完成安装。`pip check` 无依赖冲突。
- `npm ci` 根据 `package-lock.json` 安装；Rust 根据 `Cargo.lock` 使用此前下载的 rsproxy 缓存，全新 `target` 编译。
- 复用本机工具链和下载缓存；这是干净源码/依赖安装验证，不是重装系统或干净 Windows 虚拟机验证。

## 自动验证结果

| 检查 | 结果 |
|---|---|
| Python 非窗口回归 | 58 项通过 |
| JavaScript 单元测试 | 14 项通过 |
| Rust 桌面测试 | 4 项通过 |
| Vite 前端生产构建 | 通过 |
| 锁定依赖的 Rust release 构建 | 通过，使用 `custom-protocol` 嵌入前端资源 |
| Python/JavaScript 对照 | 43 例，38 例完全匹配或同为预期错误，5 例存在差异，要求完全一致的项目无失败 |

当次对照仅使用生成的透明/网格样例和随源码提供的自制扰动图片，未读取 `test-images/` 样本。
差异集中在限色、结构保护与 k-centroid，并未把这些差异判定为等价。
详细算法差异及历史个人图片测量见 [JavaScript 评估](JAVASCRIPT_EVALUATION.md)。

初次 Python 回归中的“批处理遇错继续”测试曾出现正常图片被标记为失败；单独复现和完整重跑均通过，
目前未定位到可重复原因。测试已补充失败时的批处理错误详情，后续 CI 如再次出现可据此排查。

## 展示与产物

README 界面图由真实 Vue 前端在隔离的无头浏览器中渲染，使用演示桥接数据。
首次验证使用自制扰动样例；当前 README 展示使用测试集中的 AI 冰淇淋与附魔台顶面，
由实际 JavaScript 算法生成网格化、缩放和裁剪结果。
测试图片现随源码提供；设置和日志不提交，桌面发布包不包含测试图片。

发布包包含 EXE、使用说明、版本说明、验证记录、项目 MIT 许可证与第三方许可。
ZIP 的 SHA-256 放在旁边的 `SHA256SUMS.txt`，发布时二者应一起上传。

## 仍需手动验证

- 本次没有启动或自动操作用户的桌面应用。此前用户试用反馈未发现问题，但不替代新包完整回归。
- 新生成 EXE 的文件选择、拖放、批量导出和取消，应在发布前人工确认。
- 未验证缺少 WebView2 的机器、干净 Windows 虚拟机、所有图片格式及色彩配置文件。
- Python 源码安装与测试已验证，Python 的 PyInstaller 发布包尚未完成独立发布验证。
- GitHub Actions 工作流已提供；本地验证不代表云端工作流已经运行。公开发布仍需上传 ZIP 与校验文件。

## 复现

按 README 安装两套源码的依赖后，运行：

```powershell
python scripts/test_python.py
python scripts/compare_javascript.py
node frontend/scripts/compare.mjs
Set-Location frontend
npm test
npm run build
Set-Location src-tauri
cargo test --locked --release --features custom-protocol
cargo build --locked --release --features custom-protocol
```

上述构建完成后回到仓库根目录，可运行 `scripts/build_javascript.ps1` 收集发行目录，
再运行 `scripts/package_release.ps1` 生成版本化 ZIP；不要将 `dist/` 提交到 Git。
