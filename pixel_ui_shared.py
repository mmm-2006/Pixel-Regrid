"""Labels and image explanations shared by the desktop interfaces."""
from pixel_core import SCALE_CHANGE_THRESHOLD, scaling_info

METHODS = {"中心取样 · 快速": "center", "中位数 · 去噪": "median", "多数色 · 较慢": "majority"}
LAYOUTS = {"保持原画布": "original",
           "主体不缩放 · 改画布": "keep", "主体等比例缩放 · 改画布": "fit",
           "整图等比例缩放 · 保留原留白": "canvas_fit",
           "方块铺满 · 改尺寸": "stretch"}
RESAMPLERS = {"目标像素 · 结构保护": "pixel", "像素硬边 · 最近邻": "nearest",
              "k-centroid · 局部主色": "k-centroid"}
PALETTES = {"保留颜色": 0, "8 色": 8, "16 色": 16, "32 色": 32, "64 色": 64}
DETAILS = {"关闭": 0, "适中": 1, "较强": 2}
LAYOUT_HELP = {
    "original": "保留完整网格或原图，不改变尺寸。要输出 32×32，请选择下方尺寸预设。",
    "keep": "主体像素保持原样，居中放入目标画布；画布不能小于主体。",
    "fit": "先裁透明留白，再等比例缩放主体；适合物品图标。",
    "canvas_fit": "主体和原有留白一起等比例缩放；比例不同时补透明边。",
    "stretch": "整张图铺满目标宽高；适合方块贴图，宽高比例不同时会拉伸。",
}
RESAMPLE_HELP = {
    "pixel": "优先保护细线与小色块；减少颜色数可能丢失高光，较强保护也可能保留噪点。",
    "nearest": "保持像素硬边和原有颜色；缩小可能丢失细线。",
    "k-centroid": "选择局部主色，得到明确色块；少量高光和细线可能被舍弃。",
}


def info_text(info):
    if info is None:
        return "主体尺寸：等待识别"
    gw, gh = info.grid
    source = f"网格 {gw}×{gh}" if info.recovery == "grid" else f"原图 {gw}×{gh}"
    if info.subject is None:
        return f"{source} · 未检测到主体（完全透明或低于透明阈值，请尝试设为 0）"
    sw, sh = info.subject
    suffix = "" if info.has_alpha else "（无透明通道，按整图计）"
    if info.has_alpha and info.alpha_threshold:
        suffix += f" · 裁边忽略透明度 ≤ {info.alpha_threshold}"
    if info.recovery == "fallback":
        suffix += " · 网格识别失败，已直接转换"
    return f"{source} · 主体 {sw}×{sh} · 最小画布 {sw}×{sh}{suffix}"


def scaling_text(info, options):
    if info is None:
        return "缩放提示：等待识别。", False
    if options.layout in ("original", "keep"):
        return "缩放提示：主体未缩放，裁边或补透明画布不计入尺寸变化。", False
    if info.recovery != "grid":
        prefix = "网格识别失败，已从原图转换" if info.recovery == "fallback" else "原图直接转换"
        return f"缩放提示：{prefix}；原图分辨率不代表真实像素格数，不套用 10% 网格变化判断，请比较预览。", False
    scale = scaling_info(info, options)
    if scale is None:
        return "缩放提示：没有可用于主体缩放评估的像素。", False
    kind = "主体" if options.layout == "fit" else "整图"
    source, target = scale.source, scale.target
    change_text = " · ".join(f"{axis}{'缩小' if change < 0 else '放大' if change > 0 else '变化'} {abs(change):.1%}"
                             for axis, change in zip(("宽", "高"), scale.changes))
    text = (f"缩放提示（{SCALE_CHANGE_THRESHOLD}% 经验阈值）：{kind} {source[0]}×{source[1]} → "
            f"{target[0]}×{target[1]} · {change_text}。\n")
    if scale.exceeds_threshold:
        if any((source - target) * 100 > source * SCALE_CHANGE_THRESHOLD
               for source, target in zip(scale.source, scale.target)):
            text += ("尺寸变化超过 10%：可能丢失细线、高光，或出现断线、杂点；"
                     "请让 AI 降低主体的原生像素分辨率（减少像素格数、简化细节），"
                     "或多生成几版进行“抽卡”挑选。")
        else:
            text += "尺寸变化超过 10%：放大不会补回细节，非整数倍放大可能使像素块粗细不均；请检查预览。"
    else:
        text += "尺寸变化在 10% 以内；这只反映尺寸变化，仍需检查细线、高光和网格还原效果。"
    return text, scale.exceeds_threshold


