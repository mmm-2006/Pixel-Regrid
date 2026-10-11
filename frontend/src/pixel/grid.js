// Grid detection ported from perfect-pixel 0.1.4; see THIRD_PARTY_NOTICES.md.
import { fft, roundEven, clamp, median, distance } from './math.js'
import { makeImage } from './image.js'
export class GridError extends Error {}
function grayImage(image) {
  const gray = new Float64Array(image.width * image.height)
  for (let i = 0; i < gray.length; i++) {
    const a = image.hasAlpha ? image.data[i * 4 + 3] / 255 : 1
    const r = roundEven(image.data[i * 4] * a + 192 * (1 - a))
    const g = roundEven(image.data[i * 4 + 1] * a + 192 * (1 - a))
    const b = roundEven(image.data[i * 4 + 2] * a + 192 * (1 - a))
    gray[i] = (r * 4899 + g * 9617 + b * 1868 + 8192) >> 14
  }
  return gray
}
function gradient(gray, w, h) {
  const xs = new Float64Array(w), ys = new Float64Array(h)
  const reflect = (i, n) => i < 0 ? Math.min(1, n - 1) : i >= n ? Math.max(0, n - 2) : i
  const at = (x, y) => gray[reflect(y, h) * w + reflect(x, w)]
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const gx = at(x + 1, y - 1) + 2 * at(x + 1, y) + at(x + 1, y + 1) - at(x - 1, y - 1) - 2 * at(x - 1, y) - at(x - 1, y + 1)
    const gy = at(x - 1, y + 1) + 2 * at(x, y + 1) + at(x + 1, y + 1) - at(x - 1, y - 1) - 2 * at(x, y - 1) - at(x + 1, y - 1)
    xs[x] += Math.abs(gx); ys[y] += Math.abs(gy)
  }
  return [xs, ys]
}
function peak(v) {
  const center = Math.floor(v.length / 2), max = v.reduce((a, b) => Math.max(a, b), 0), candidates = []
  if (max < 1e-6) return null
  for (let i = 1; i < v.length - 1; i++) {
    let isPeak = true
    for (let j = 1; j < 6; j++) {
      if (i - j < 0 || i + j >= v.length) continue
      if (v[i - j + 1] < v[i - j] || v[i + j - 1] < v[i + j]) { isPeak = false; break }
    }
    if (!isPeak || v[i] < max * .35) continue
    let left = 0, right = 0
    for (let k = i; k > 0 && v[k] > v[k - 1]; k--) left = Math.abs(v[i] - v[k - 1])
    for (let k = i; k < v.length - 1 && v[k] > v[k + 1]; k++) right = Math.abs(v[i] - v[k + 1])
    candidates.push({ index: i, score: Math.max(left, right) })
  }
  const left = candidates.filter(a => a.index < center - 6 && a.index > center * .25).sort((a, b) => b.score - a.score)
  const right = candidates.filter(a => a.index > center + 6 && a.index < center * 1.75).sort((a, b) => b.score - a.score)
  return left.length && right.length ? Math.abs(right[0].index - left[0].index) / 2 : null
}
function smooth(v) {
  let min = Infinity, max = -Infinity
  for (const n of v) { min = Math.min(min, n); max = Math.max(max, n) }
  const weights = Array.from({ length: 17 }, (_, i) => Math.exp(-((i - 8) ** 2) / (2 * (17 / 6) ** 2)))
  const total = weights.reduce((a, b) => a + b, 0), out = new Float64Array(v.length)
  if (max - min < 1e-8) return out
  for (let i = 0; i < v.length; i++) for (let j = 0; j < 17; j++) {
    const k = i + j - 8
    if (k >= 0 && k < v.length) out[i] += (v[k] - min) / (max - min) * weights[j] / total
  }
  return out
}
function fftGrid(gray, w, h) {
  const re = Float64Array.from(gray), im = new Float64Array(re.length)
  for (let y = 0; y < h; y++) {
    const r = re.slice(y * w, (y + 1) * w), i = im.slice(y * w, (y + 1) * w)
    fft(r, i); re.set(r, y * w); im.set(i, y * w)
  }
  for (let x = 0; x < w; x++) {
    const r = new Float64Array(h), i = new Float64Array(h)
    for (let y = 0; y < h; y++) { r[y] = re[y * w + x]; i[y] = im[y * w + x] }
    fft(r, i)
    for (let y = 0; y < h; y++) { re[y * w + x] = r[y]; im[y * w + x] = i[y] }
  }
  const magnitude = new Float64Array(re.length)
  let min = Infinity, max = -Infinity
  for (let k = 0; k < re.length; k++) { const v = 1 - Math.log1p(Math.hypot(re[k], im[k])); magnitude[k] = v; min = Math.min(min, v); max = Math.max(max, v) }
  if (max - min < 1e-8) return [null, null]
  const rows = new Float64Array(h), cols = new Float64Array(w)
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const v = (magnitude[((y + Math.ceil(h / 2)) % h) * w + (x + Math.ceil(w / 2)) % w] - min) / (max - min)
    if (x < 2 * Math.floor(w / 2)) rows[y] += v
    if (y < 2 * Math.floor(h / 2)) cols[x] += v
  }
  const gw = peak(smooth(cols)), gh = peak(smooth(rows))
  return gw == null || gh == null ? [null, null] : [roundEven(gw), roundEven(gh)]
}
function gradientGrid(xs, ys, w, h) {
  const spacing = v => {
    const max = v.reduce((a, b) => Math.max(a, b), 0), peaks = []
    for (let i = 1; i < v.length - 1; i++) if (v[i] > v[i - 1] && v[i] > v[i + 1] && v[i] >= max * .2 && (!peaks.length || i - peaks.at(-1) >= 4)) peaks.push(i)
    return peaks.length < 4 ? null : median(peaks.slice(1).map((v, i) => v - peaks[i]))
  }
  const x = spacing(xs), y = spacing(ys)
  return x && y ? [roundEven(w / x), roundEven(h / y)] : [null, null]
}
function lines(length, count, projection) {
  const step = length / count
  function best(origin, range) {
    let found = roundEven(origin), score = -Infinity
    for (let k = -roundEven(range); k <= roundEven(range); k++) {
      const i = roundEven(origin + k)
      if (i <= 0 || i >= length - 1) continue
      if (projection[i] > projection[i - 1] && projection[i] > projection[i + 1] && projection[i] > score) { score = projection[i]; found = i }
    }
    return found
  }
  const center = best(length / 2, step), out = []
  let x = center, safety = 0
  while (x < length + step / 2 && safety++ < count * 4 + 16) { x = best(x, step * .25); out.push(x); x += step }
  x = center - step; safety = 0
  while (x > -step / 2 && safety++ < count * 4 + 16) { x = best(x, step * .25); out.push(x); x -= step }
  return out.sort((a, b) => a - b)
}
// Deterministic two-cluster substitute. OpenCV/Pillow use different initializers;
// this is an experimental algorithm, not asserted to reproduce their clusters.
export function clusters(samples, iterations = 6) {
  const ordered = [...samples].sort((a, b) => a.reduce((result, v, i) => result || v - b[i], 0))
  let centers = [ordered[0].slice(), ordered.at(-1).slice()], labels = new Int32Array(samples.length)
  for (let pass = 0; pass < iterations; pass++) {
    const sums = centers.map(c => Array(c.length).fill(0)), counts = [0, 0]
    samples.forEach((sample, i) => {
      const group = distance(sample, centers[0]) <= distance(sample, centers[1]) ? 0 : 1
      labels[i] = group; counts[group]++
      sample.forEach((v, k) => { sums[group][k] += v })
    })
    centers = centers.map((c, k) => counts[k] ? sums[k].map(v => v / counts[k]) : c)
  }
  return { centers, labels }
}
export function restoreGrid(image, options) {
  const { width: w, height: h, data } = image
  let xs, ys
  if (options.grid) {
    const [gw, gh] = options.grid
    if (gw > w || gh > h || gw < 1 || gh < 1) throw new Error('指定网格尺寸超出原图')
    xs = Array.from({ length: gw + 1 }, (_, i) => Math.floor(i * w / gw))
    ys = Array.from({ length: gh + 1 }, (_, i) => Math.floor(i * h / gh))
  } else {
    if (Math.min(w, h) < 16) throw new GridError('图片过小，无法可靠识别网格；请选择原图直接转换')
    if (w * h > 4_000_000) throw new GridError('网格识别最多处理 400 万像素，请缩小原图或直接转换')
    const gray = grayImage(image), [gx, gy] = gradient(gray, w, h)
    let [gw, gh] = fftGrid(gray, w, h)
    if (!gw || !gh || Math.min(w / gw, h / gh) < 4 || Math.max(w / gw, h / gh) > 20 || (w / gw) / (h / gh) > 1.5 || (h / gh) / (w / gw) > 1.5) [gw, gh] = gradientGrid(gx, gy, w, h)
    if (!gw || !gh) throw new GridError('自动识别网格失败；请选择原图直接转换')
    const px = w / gw, py = h / gh, size = px / py > 1.5 || py / px > 1.5 ? Math.min(px, py) : (px + py) / 2
    gw = roundEven(w / size); gh = roundEven(h / size)
    if (gw > Math.min(w, 1024) || gh > Math.min(h, 1024)) throw new GridError('识别网格过密；请选择原图直接转换')
    xs = lines(w, gw, gx); ys = lines(h, gh, gy)
    if (xs.length < 2 || ys.length < 2) throw new GridError('无法生成有效网格')
  }
  const out = makeImage(xs.length - 1, ys.length - 1, image.hasAlpha)
  function sample(x, y) {
    const k = (clamp(y, 0, h - 1) * w + clamp(x, 0, w - 1)) * 4, a = image.hasAlpha ? data[k + 3] / 255 : 1
    return [Math.fround(data[k] * a), Math.fround(data[k + 1] * a), Math.fround(data[k + 2] * a), data[k + 3]]
  }
  for (let y = 0; y < out.height; y++) for (let x = 0; x < out.width; x++) {
    let color
    if (options.method === 'center') color = sample(Math.floor((xs[x] + xs[x + 1]) / 2), Math.floor((ys[y] + ys[y + 1]) / 2))
    else {
      const values = []
      const x0 = clamp(xs[x], 0, w), x1 = clamp(xs[x + 1], 0, w), y0 = clamp(ys[y], 0, h), y1 = clamp(ys[y + 1], 0, h)
      for (let sy = y0; sy < Math.min(h, Math.max(y0 + 1, y1)); sy++) for (let sx = x0; sx < Math.min(w, Math.max(x0 + 1, x1)); sx++) values.push(sample(sx, sy))
      if (!values.length) color = [0, 0, 0, 0]
      else if (options.method === 'median') color = [0, 1, 2, 3].map(c => median(values.map(v => v[c])))
      else { const { centers, labels } = clusters(values); const ones = labels.reduce((a, b) => a + b, 0); color = centers[ones >= values.length - ones ? 1 : 0] }
    }
    const a = image.hasAlpha ? color[3] / 255 : 1, k = (y * out.width + x) * 4
    for (let c = 0; c < 3; c++) out.data[k + c] = clamp(roundEven(a ? Math.fround(color[c] / a) : 0), 0, 255)
    out.data[k + 3] = clamp(roundEven(color[3]), 0, 255)
  }
  return out
}
