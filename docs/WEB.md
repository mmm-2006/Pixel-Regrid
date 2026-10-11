# 网页版

在线地址：https://mmm-2006.github.io/Pixel-Regrid/

添加图片、选择文件夹或拖入图片，处理后点击导出。单张下载 PNG，多张打包 ZIP，
同名结果自动添加数字后缀。浏览器若没有自动开始下载，可点击“下载结果”。
文件夹中的图片会递归导入；拖入文件夹的兼容性因浏览器而异，建议使用“文件夹”按钮。

图片仅在浏览器内处理，不会上传到 GitHub 或其他服务器。
参数保存在当前浏览器，图片列表与导出结果在刷新或关闭页面后清除。
支持浏览器可解码的 PNG、JPEG、WebP、BMP、GIF 和 AVIF；动画图片仅取静态帧。
使用浏览器的图片编解码，半透明像素的颜色舍入可能与桌面 Rust 编解码略有差异。
适合使用桌面浏览器；大图与大批量任务建议使用桌面版。

## 本地开发与验证

```powershell
Set-Location frontend
npm ci
npm run dev
```

构建：`npm run build:web`。部署目录为 `frontend/dist-web/`，不提交构建产物。
Node 回归测试：`npm test`。安装了 Chrome 或 Edge 后，可运行
`npm run build:web`、`npm run test:browser`，使用独立的无头浏览器验证真实文件导入、Worker 处理和下载。
也可通过 `BROWSER_EXECUTABLE` 指定 Chromium 路径，`WEB_TEST_URL` 指定已部署网站。

## GitHub Pages

仓库 Settings → Pages → Build and deployment → Source 选择 **GitHub Actions**。
`.github/workflows/pages.yml` 会在 main 的前端代码变更后测试、构建并部署；也可手动运行。
源码使用相对资源路径，支持仓库子目录下的网站地址。
桌面前端位于 `frontend/dist/`，网页前端位于 `frontend/dist-web/`，两者互不覆盖。

网站发布不包含测试原图、Python、Rust 或用户设置，仅包含网页构建产物。
