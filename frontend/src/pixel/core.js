import { validateOptions, imageInfo, bounds, crop, nearest, fittedSize, onCanvas } from './image.js'
import { GridError, restoreGrid } from './grid.js'
import { targetPixels, kCentroid } from './resize.js'
export { DEFAULTS, validateOptions } from './image.js'
export function prepareImage(source, input) {
  const o = validateOptions(input)
  if (source.data.length !== source.width * source.height * 4) throw new Error('图片像素数据长度有误')
  let prepared = source, recovery = o.direct ? 'direct' : 'grid'
  if (!o.direct) {
    try { prepared = restoreGrid(source, o) }
    catch (error) {
      if (!(error instanceof GridError) || o.grid || !['pixel', 'k-centroid'].includes(o.resample) || !['fit', 'canvas_fit'].includes(o.layout)) throw error
      recovery = 'fallback'
    }
  }
  return { image: prepared, recovery }
}
export function layoutPrepared(prepared, recovery, input) {
  const o = validateOptions(input), info = imageInfo(prepared, recovery, o.alpha_threshold)
  if (o.layout === 'original') return { image: prepared, info }
  const b = o.layout === 'canvas_fit' ? [0, 0, prepared.width, prepared.height] : bounds(prepared, o.alpha_threshold)
  if (!b) throw new Error('没有超过透明噪点阈值的主体，请降低阈值或设为 0')
  let subject = crop(prepared, b)
  if (o.layout === 'keep') {
    if (o.width < subject.width || o.height < subject.height) throw new Error(`主体 ${subject.width}×${subject.height}；画布至少为 ${subject.width}×${subject.height}`)
  } else {
    const [w, h] = fittedSize(subject.width, subject.height, o.width, o.height)
    subject = o.resample === 'nearest' ? nearest(subject, w, h) : o.resample === 'pixel'
      ? targetPixels(subject, w, h, o.palette_size, o.detail) : kCentroid(subject, w, h)
  }
  return { image: onCanvas(subject, o.width, o.height), info }
}
export function processImage(source, input) {
  const prepared = prepareImage(source, input)
  return layoutPrepared(prepared.image, prepared.recovery, input)
}
export function explain(info, o) {
  const source = info.recovery === 'grid' ? '网格' : '原图', [w, h] = info.grid
  const subject = info.subject ? `主体 ${info.subject.join('×')} · 最小画布 ${info.subject.join('×')}` : '未检测到主体'
  const info_text = `${source} ${w}×${h} · ${subject}${info.recovery === 'fallback' ? ' · 网格识别失败，已直接转换' : ''}`
  let scaling_text = '缩放提示：主体未缩放，裁边或补透明画布不计入尺寸变化。', attention = false
  if (['fit', 'canvas_fit'].includes(o.layout)) {
    if (info.recovery !== 'grid') scaling_text = '原图直接转换；原图分辨率不代表真实像素格数，请比较预览。'
    else {
      const input = o.layout === 'fit' ? info.subject : info.grid
      if (input) {
        const output = fittedSize(...input, o.width, o.height), changes = output.map((v, i) => (v - input[i]) / input[i])
        attention = output.some((v, i) => Math.abs(v - input[i]) * 100 > input[i] * 10)
        scaling_text = `${o.layout === 'fit' ? '主体' : '整图'} ${input.join('×')} → ${output.join('×')} · ${changes.map((v, i) => `${i ? '高' : '宽'}${v < 0 ? '缩小' : '放大'} ${(Math.abs(v) * 100).toFixed(1)}%`).join(' · ')}`
        if (attention) scaling_text += '。尺寸变化超过 10%，请检查细线与色块；缩小时可让 AI 减少原生像素格数或多生成几版挑选。'
      }
    }
  }
  return { info_text, scaling_text, attention }
}
