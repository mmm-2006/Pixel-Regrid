// Float64 transforms support arbitrary image dimensions (radix-2 + Bluestein).
export const clamp = (x, a, b) => Math.max(a, Math.min(b, x))
export function roundEven(x) {
  const n = Math.floor(x), f = x - n
  return f === .5 ? n + Math.abs(n % 2) : Math.round(x)
}
export function median(values) {
  const a = [...values].sort((x, y) => x - y), n = a.length
  return n % 2 ? a[n >> 1] : (a[n / 2 - 1] + a[n / 2]) / 2
}
function radix(re, im, inverse = false) {
  const n = re.length
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1
    for (; j & bit; bit >>= 1) j ^= bit
    j ^= bit
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]] }
  }
  for (let len = 2; len <= n; len *= 2) {
    const angle = (inverse ? 2 : -2) * Math.PI / len, cr = Math.cos(angle), ci = Math.sin(angle)
    for (let start = 0; start < n; start += len) {
      let wr = 1, wi = 0
      for (let j = 0; j < len / 2; j++) {
        const a = start + j, b = a + len / 2
        const tr = wr * re[b] - wi * im[b], ti = wr * im[b] + wi * re[b]
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti
        const next = wr * cr - wi * ci; wi = wr * ci + wi * cr; wr = next
      }
    }
  }
  if (inverse) for (let i = 0; i < n; i++) { re[i] /= n; im[i] /= n }
}
export function fft(re, im = new Float64Array(re.length)) {
  const n = re.length
  if (!(n & (n - 1))) { radix(re, im); return [re, im] }
  let size = 1
  while (size < 2 * n - 1) size *= 2
  const ar = new Float64Array(size), ai = new Float64Array(size)
  const br = new Float64Array(size), bi = new Float64Array(size)
  for (let i = 0; i < n; i++) {
    const angle = Math.PI * (i * i % (2 * n)) / n, c = Math.cos(angle), s = Math.sin(angle)
    ar[i] = re[i] * c + im[i] * s; ai[i] = im[i] * c - re[i] * s
    br[i] = c; bi[i] = s
    if (i) { br[size - i] = c; bi[size - i] = s }
  }
  radix(ar, ai); radix(br, bi)
  for (let i = 0; i < size; i++) {
    const t = ar[i] * br[i] - ai[i] * bi[i]
    ai[i] = ar[i] * bi[i] + ai[i] * br[i]; ar[i] = t
  }
  radix(ar, ai, true)
  for (let i = 0; i < n; i++) {
    const angle = Math.PI * (i * i % (2 * n)) / n, c = Math.cos(angle), s = Math.sin(angle)
    re[i] = ar[i] * c + ai[i] * s; im[i] = ai[i] * c - ar[i] * s
  }
  return [re, im]
}

// Standard sRGB/D65 Lab, encoded to OpenCV's 8-bit Lab range. OpenCV's
// integer lookup-table conversion can differ by 1 unit; parity reports track it.
export function lab(r, g, b) {
  const linear = x => { x /= 255; return x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4 }
  r = linear(r); g = linear(g); b = linear(b)
  const f = x => x > .008856451679 ? Math.cbrt(x) : 7.787037037 * x + 16 / 116
  const x = f((.412453 * r + .357580 * g + .180423 * b) / .950456)
  const y = f(.212671 * r + .715160 * g + .072169 * b)
  const z = f((.019334 * r + .119193 * g + .950227 * b) / 1.088754)
  return [clamp(roundEven((116 * y - 16) * 255 / 100), 0, 255),
    clamp(roundEven(500 * (x - y) + 128), 0, 255), clamp(roundEven(200 * (y - z) + 128), 0, 255)]
}
export const distance = (a, b) => a.reduce((s, v, i) => s + (v - b[i]) ** 2, 0)
export function weightedMedian(values) {
  values.sort((a, b) => a[0] - b[0])
  const middle = values.reduce((s, a) => s + a[1], 0) / 2
  let sum = 0
  for (const [v, w] of values) { sum += w; if (sum >= middle) return v }
  return values.at(-1)[0]
}
