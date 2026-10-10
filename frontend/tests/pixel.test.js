import test from 'node:test'
import assert from 'node:assert/strict'
import { fft, roundEven } from '../src/pixel/math.js'
import { makeImage, bounds, nearest } from '../src/pixel/image.js'
import { processImage } from '../src/pixel/core.js'
import { targetPixels, kCentroid } from '../src/pixel/resize.js'
test('FFT matches a direct transform for prime, odd and power-of-two dimensions', () => {
  for (const n of [1, 2, 3, 5, 7, 8, 11, 16, 17, 32]) {
    const values = Float64Array.from({ length: n }, (_, i) => Math.sin(i * .7) + i / 7)
    const [re, im] = fft(values.slice())
    for (let k = 0; k < n; k++) {
      let r = 0, v = 0
      for (let j = 0; j < n; j++) { r += values[j] * Math.cos(2 * Math.PI * j * k / n); v -= values[j] * Math.sin(2 * Math.PI * j * k / n) }
      assert.ok(Math.abs(re[k] - r) < 1e-9); assert.ok(Math.abs(im[k] - v) < 1e-9)
    }
  }
})
test('rounding matches NumPy ties-to-even geometry', () => {
  assert.deepEqual([.5, 1.5, 2.5, 3.5, -.5, -1.5].map(roundEven), [0, 2, 2, 4, 0, -2])
})
test('nearest-neighbor coordinate accumulation matches OpenCV 5 at fractional ties', () => {
  const source = makeImage(8, 1)
  for (let x = 0; x < 8; x++) source.data.set([x, x, x, 255], x * 4)
  const out = nearest(source, 6, 1)
  assert.deepEqual([...out.data].filter((_, i) => i % 4 === 0), [0, 2, 3, 4, 5, 7])
})
test('whole-image fit preserves proportion and alpha while subject crop ignores faint noise', () => {
  const image = makeImage(6, 4); image.data.set([9, 31, 151, 1], 0)
  image.data.set([17, 81, 233, 128], (1 * 6 + 2) * 4)
  assert.deepEqual(bounds(image, 1), [2, 1, 3, 2])
  const result = processImage(image, { direct: true, layout: 'canvas_fit', resample: 'nearest', width: 6, height: 6 })
  assert.equal(result.image.height, 6); assert.deepEqual([...result.image.data.slice(0, 24)], Array(24).fill(0))
  const keep = processImage(image, { direct: true, layout: 'keep', width: 1, height: 1 })
  assert.deepEqual([...keep.image.data], [17, 81, 233, 128])
})
test('dominant-cluster votes ignore hidden RGB and preserve observed alpha', () => {
  const source = makeImage(4, 1)
  source.data.set([255, 255, 0, 0, 17, 81, 233, 128, 17, 81, 233, 128, 17, 81, 233, 255])
  const out = kCentroid(source, 1, 1)
  assert.deepEqual([...out.data], [17, 81, 233, 128])
  const reversed = { ...source, data: new Uint8Array([...source.data.slice(12), ...source.data.slice(8, 12), ...source.data.slice(4, 8), ...source.data.slice(0, 4)]) }
  assert.deepEqual(kCentroid(reversed, 1, 1).data, out.data)
})
test('structure protection keeps source colors and alpha and stays deterministic', () => {
  const source = makeImage(16, 16)
  for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) source.data.set(x === 8 ? [255, 0, 0, 128] : [0, 0, 255, 255], (y * 16 + x) * 4)
  const out = targetPixels(source, 8, 8, 8, 2), again = targetPixels(source, 8, 8, 8, 2)
  assert.deepEqual(out.data, again.data)
  const colors = new Set()
  for (let k = 0; k < out.data.length; k += 4) { colors.add([...out.data.slice(k, k + 3)].join()); assert.ok([128, 255].includes(out.data[k + 3])) }
  assert.ok(colors.has('255,0,0')); assert.ok([...colors].every(v => ['255,0,0', '0,0,255'].includes(v)))
})
test('fully transparent canvases work and invalid layouts cannot enable removed stretch', () => {
  const source = makeImage(2, 2)
  assert.throws(() => processImage(source, { direct: true, layout: 'keep' }))
  assert.throws(() => processImage(source, { direct: true, layout: 'stretch' }))
  assert.throws(() => processImage(source, { direct: true, width: NaN }))
  const out = processImage(source, { direct: true, layout: 'canvas_fit', width: 8, height: 8, resample: 'pixel' }).image
  assert.equal(out.data.some(Boolean), false)
})
