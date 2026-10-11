# 本地图片测试

原 `1/`、`2/` 的测试原图统一放在本目录，生成结果合并到
`perfect_pixel_output/`，保留已有文件名和输出子目录。
整理时保留了全部 6 张原图及 35 个输出文件，没有修改图片内容。

图片和生成结果仅在本机使用，不提交到 Git。`samples.json` 指定 Python/JavaScript
对照使用的 4 张样本，保留历史分组编号以便复现已有报告；编号不代表目录。
缺少本地样本时，对照脚本仍运行构造案例，并明确提示跳过的图片。

从项目根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/compare_javascript.py
node frontend/scripts/compare.mjs
```
