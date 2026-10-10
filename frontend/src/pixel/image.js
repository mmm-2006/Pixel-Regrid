import { clamp, roundEven } from './math.js'
export const DEFAULTS = Object.freeze({ direct: false, method: 'center', layout: 'original', width: 32,
  height: 32, resample: 'pixel', palette_size: 32, detail: 1, alpha_threshold: 1 })
export function validateOptions(input) {
  const o = { ...DEFAULTS, ...input }
  if (typeof o.direct !== 'boolean') throw new Error('输入方式有误')
  if (!['original', 'keep', 'fit', 'canvas_fit'].includes(o.layout)) throw new Error('输出方式有误')
  if (!['center', 'median', 'majority'].includes(o.method)) throw new Error('未知取样方式')
  if (!['nearest', 'pixel', 'k-centroid'].includes(o.resample)) throw new Error('未知缩放算法')
  const limit = o.layout === 'keep' ? 8192 : 1024
  for (const key of ['width', 'height']) if (!Number.isInteger(o[key]) || o[key] < 1 || o[key] > limit) throw new Error(`画布宽、高必须是 1～${limit} 的整数`)
  if (o.width * o.height > 32_000_000) throw new Error('画布总像素不能超过 3200 万')
  if (![0, 8, 16, 32, 64].includes(o.palette_size)) throw new Error('颜色数有误')
  if (![0, 1, 2].includes(o.detail)) throw new Error('细节保护有误')
  if (!Number.isInteger(o.alpha_threshold) || o.alpha_threshold < 0 || o.alpha_threshold > 254) throw new Error('透明噪点阈值必须是 0～254 的整数')
  return o
}
export function makeImage(width, height, hasAlpha = true) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width * height > 32_000_000) throw new Error('图片总像素不能超过 3200 万')
  const data = new Uint8Array(width * height * 4)
  if (!hasAlpha) for (let i = 3; i < data.length; i += 4) data[i] = 255
  return { width, height, hasAlpha, data }
}
export function bounds(image, threshold) {
  const { width: w, height: h, data } = image
  if (!image.hasAlpha) return [0, 0, w, h]
  let x0 = w, y0 = h, x1 = 0, y1 = 0
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (data[(y * w + x) * 4 + 3] > threshold) {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x + 1); y1 = Math.max(y1, y + 1)
  }
  return x1 ? [x0, y0, x1, y1] : null
}
export function imageInfo(image, recovery, threshold) {
  const b = bounds(image, threshold)
  return { grid: [image.width, image.height], subject: b ? [b[2] - b[0], b[3] - b[1]] : null,
    has_alpha: image.hasAlpha, recovery, alpha_threshold: threshold }
}
export function crop(image, b) {
  const out = makeImage(b[2] - b[0], b[3] - b[1], image.hasAlpha)
  for (let y = 0; y < out.height; y++) out.data.set(image.data.subarray(((y + b[1]) * image.width + b[0]) * 4,
    ((y + b[1]) * image.width + b[2]) * 4), y * out.width * 4)
  return out
}
export function nearest(image, width, height) {
  const out = makeImage(width, height, image.hasAlpha)
  const positions = (length, target) => {
    const scale = length / target, values = []; let position = scale / 2
    for (let i = 0; i < target; i++, position += scale) values.push(Math.min(length - 1, Math.floor(position)))
    return values
  }
  const xs = positions(image.width, width), ys = positions(image.height, height)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    // Match OpenCV 5 / Pillow: accumulate half-pixel coordinates in Float64.
    const sx = xs[x], sy = ys[y]
    out.data.set(image.data.subarray((sy * image.width + sx) * 4, (sy * image.width + sx) * 4 + 4), (y * width + x) * 4)
  }
  return out
}
export function fittedSize(width, height, cw, ch) {
  const factor = Math.min(cw / width, ch / height)
  return [Math.min(cw, Math.max(1, roundEven(width * factor))), Math.min(ch, Math.max(1, roundEven(height * factor)))]
}
export function onCanvas(image, width, height) {
  const out = makeImage(width, height), x = Math.floor((width - image.width) / 2), y = Math.floor((height - image.height) / 2)
  for (let row = 0; row < image.height; row++) out.data.set(image.data.subarray(row * image.width * 4, (row + 1) * image.width * 4), ((row + y) * width + x) * 4)
  return out
}
export function footprints(length, target) {
  return Array.from({ length: target }, (_, i) => {
    if (target >= length) return [[Math.min(length - 1, Math.floor((i + .5) * length / target)), 1]]
    const a = i * length / target, b = (i + 1) * length / target, values = []
    for (let k = Math.floor(a); k < Math.min(length, Math.ceil(b)); k++) values.push([k, Math.max(0, Math.min(k + 1, b) - Math.max(k, a))])
    return values
  })
}
