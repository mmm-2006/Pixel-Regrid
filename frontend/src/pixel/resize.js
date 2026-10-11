import { lab, distance, roundEven, clamp, weightedMedian } from './math.js'
import { makeImage, footprints, nearest } from './image.js'
import { clusters } from './grid.js'
const colorKey = (r, g, b) => (b << 16) | (g << 8) | r
const unpack = n => [n & 255, (n >> 8) & 255, (n >> 16) & 255]
function paletteLabels(image, limit) {
  const counts = new Map(), data = image.data
  for (let k = 0; k < data.length; k += 4) if (data[k + 3]) {
    const key = colorKey(data[k], data[k + 1], data[k + 2]); counts.set(key, (counts.get(key) || 0) + 1)
  }
  const unique = [...counts.keys()].sort((a, b) => a - b), colors = unique.map(unpack), labels = new Map()
  if (!limit || unique.length <= limit) { unique.forEach((key, i) => labels.set(key, i)); return { palette: colors, labels } }
  const bins = new Map()
  colors.forEach((rgb, i) => {
    const key = colorKey(...rgb.map(v => Math.floor(v / 8)))
    if (!bins.has(key)) bins.set(key, { members: [], weight: 0, sum: [0, 0, 0] })
    const bin = bins.get(key), count = counts.get(unique[i]); bin.members.push(i); bin.weight += count
    rgb.forEach((v, c) => { bin.sum[c] += v * count })
  })
  const entries = [...bins.entries()].sort((a, b) => a[0] - b[0]).map(([, v]) => v)
  const points = entries.map(bin => lab(...bin.sum.map(v => roundEven(v / bin.weight))))
  let groups = [entries.map((_, i) => i)]
  function moments(group) {
    const total = group.reduce((s, i) => s + entries[i].weight, 0)
    const center = [0, 1, 2].map(c => group.reduce((s, i) => s + points[i][c] * entries[i].weight, 0) / total)
    const variance = center.map((v, c) => group.reduce((s, i) => s + (points[i][c] - v) ** 2 * entries[i].weight, 0) / total)
    return { total, variance, score: group.length > 1 ? Math.max(...variance) * total : -1 }
  }
  while (groups.length < limit) {
    const momentsList = groups.map(moments), best = momentsList.reduce((a, v, i) => v.score > momentsList[a].score ? i : a, 0)
    if (momentsList[best].score <= 0) break
    const group = groups.splice(best, 1)[0], variance = momentsList[best].variance
    const axis = variance.indexOf(Math.max(...variance)), order = [...group].sort((a, b) => points[a][axis] - points[b][axis])
    let sum = 0, split = 0
    while (sum < momentsList[best].total / 2) sum += entries[order[split++]].weight
    split = clamp(split, 1, order.length - 1); groups.push(order.slice(0, split), order.slice(split))
  }
  const labs = colors.map(rgb => lab(...rgb)), palette = groups.map(group => {
    const members = group.flatMap(i => entries[i].members).sort((a, b) => a - b), total = members.reduce((s, i) => s + counts.get(unique[i]), 0)
    const center = [0, 1, 2].map(c => members.reduce((s, i) => s + labs[i][c] * counts.get(unique[i]), 0) / total)
    let best = members[0]
    for (const i of members) if (distance(labs[i], center) < distance(labs[best], center)) best = i
    return colors[best]
  })
  const paletteLab = palette.map(rgb => lab(...rgb))
  unique.forEach((key, i) => {
    let best = 0
    for (let k = 1; k < palette.length; k++) if (distance(labs[i], paletteLab[k]) < distance(labs[i], paletteLab[best])) best = k
    labels.set(key, best)
  })
  return { palette, labels }
}
function areaFootprints(length, target) {
  return Array.from({ length: target }, (_, i) => {
    const a = i * length / target, b = (i + 1) * length / target, values = []
    for (let k = Math.floor(a); k < Math.min(length, Math.ceil(b)); k++) values.push([k, Math.min(k + 1, b) - Math.max(k, a)])
    return values
  })
}
export function targetPixels(image, tw, th, paletteSize, detail) {
  const { width: w, height: h, data } = image
  if (w * h > 4_000_000) throw new Error('直接目标像素转换最多处理 400 万像素；请先还原网格或缩小原图')
  const out = makeImage(tw, th), { palette, labels } = paletteLabels(image, paletteSize)
  if (!palette.length) return out
  const ids = new Int32Array(w * h).fill(-1)
  const comparison = new Float32Array(w * h * 4), importance = new Float64Array(w * h)
  for (let i = 0; i < ids.length; i++) {
    const k = i * 4, a = data[k + 3]
    if (a) ids[i] = labels.get(colorKey(data[k], data[k + 1], data[k + 2]))
    const color = lab(data[k], data[k + 1], data[k + 2])
    color.forEach((v, c) => { comparison[k + c] = v * a / 255 }); comparison[k + 3] = a
  }
  if (tw === w && th === h) {
    for (let i = 0; i < ids.length; i++) if (ids[i] >= 0) { out.data.set(palette[ids[i]], i * 4); out.data[i * 4 + 3] = data[i * 4 + 3] }
    return out
  }
  function delta(i, j) { let sum = 0; for (let c = 0; c < 4; c++) sum += (comparison[i * 4 + c] - comparison[j * 4 + c]) ** 2; return Math.sqrt(sum) }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x
    const ridge = Math.max(Math.min(delta(i, y * w + Math.max(0, x - 1)), delta(i, y * w + Math.min(w - 1, x + 1))),
      Math.min(delta(i, Math.max(0, y - 1) * w + x), delta(i, Math.min(h - 1, y + 1) * w + x)))
    importance[i] = 1 + 3 * detail * clamp((ridge - 12) / 60, 0, 1)
  }
  const xs = areaFootprints(w, tw), ys = areaFootprints(h, th), winners = new Int32Array(tw * th).fill(-1), candidates = []
  for (let y = 0; y < th; y++) for (let x = 0; x < tw; x++) {
    const votes = new Map(), opacity = []; let area = 0, foregroundArea = 0, foreground = 0, background = 0
    for (const [sy, wy] of ys[y]) for (const [sx, wx] of xs[x]) {
      const i = sy * w + sx, mass = wx * wy, weighted = mass * importance[i]; area += mass
      if (ids[i] < 0) { background += weighted; continue }
      foregroundArea += mass; foreground += weighted; opacity.push([data[i * 4 + 3], mass])
      if (!votes.has(ids[i])) votes.set(ids[i], [0, 0])
      const vote = votes.get(ids[i]); vote[0] += weighted; vote[1] += mass
    }
    const fraction = foregroundArea / area, k = y * tw + x
    if (fraction < .45 && !(detail && fraction >= .12 && foreground > background)) { candidates[k] = null; continue }
    const center = ids[Math.min(h - 1, Math.floor((y + .5) * h / th)) * w + Math.min(w - 1, Math.floor((x + .5) * w / tw))]
    const sorted = [...votes.entries()].sort((a, b) => a[0] - b[0])
    let allowed = sorted.filter(([, vote]) => vote[1] / area >= Math.min(.08, fraction))
    if (!allowed.length) allowed = [sorted.reduce((a, b) => b[1][0] > a[1][0] ? b : a)]
    const values = allowed.map(([id, vote]) => [id, vote[0] / (foreground + background) + (id === center ? .015 : 0)])
    candidates[k] = values; winners[k] = values.reduce((a, b) => b[1] > a[1] ? b : a)[0]
    out.data[k * 4 + 3] = weightedMedian(opacity)
  }
  for (let pass = 0; pass < 2; pass++) {
    const updated = winners.slice()
    for (let y = 0; y < th; y++) for (let x = 0; x < tw; x++) {
      const k = y * tw + x, candidate = candidates[k]
      if (!candidate) continue
      let winner = -1, best = -Infinity
      for (const [id, score] of candidate) {
        let support = 0
        for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
          const nx = x + dx, ny = y + dy
          if (nx >= 0 && nx < tw && ny >= 0 && ny < th && winners[ny * tw + nx] === id) support++
        }
        if (score + support * .025 > best) { best = score + support * .025; winner = id }
      }
      updated[k] = winner
    }
    winners.set(updated)
  }
  for (let i = 0; i < winners.length; i++) if (winners[i] >= 0) out.data.set(palette[winners[i]], i * 4)
  return out
}
export function kCentroid(image, tw, th) {
  const { width: w, height: h, data } = image
  if (tw >= w && th >= h) {
    const out = nearest(image, tw, th)
    for (let k = 0; k < out.data.length; k += 4) if (!out.data[k + 3]) out.data.fill(0, k, k + 3)
    return out
  }
  if (w * h > 4_000_000) throw new Error('k-centroid 缩小最多处理 400 万像素')
  const out = makeImage(tw, th, image.hasAlpha), xs = footprints(w, tw), ys = footprints(h, th)
  for (let y = 0; y < th; y++) for (let x = 0; x < tw; x++) {
    const colors = [], weights = [], alpha = []; let total = 0, visible = 0
    for (const [sy, wy] of ys[y]) for (const [sx, wx] of xs[x]) {
      const k = (sy * w + sx) * 4, mass = wx * wy; total += mass
      if (data[k + 3] && mass > 0) { visible += mass; colors.push(Array.from(data.subarray(k, k + 3))); weights.push(mass); alpha.push(data[k + 3]) }
    }
    if (!colors.length || visible < total * .5 - 1e-10) continue
    const { centers, labels } = clusters(colors, 2), palette = centers.map(c => c.map(v => clamp(roundEven(v), 0, 255))), votes = [0, 0]
    colors.forEach((_, i) => { votes[labels[i]] += weights[i] * alpha[i] / 255 })
    let group = votes[1] > votes[0] ? 1 : 0
    if (Math.abs(votes[0] - votes[1]) <= 1e-12) group = palette[0].reduce((s, v, c) => s || v - palette[1][c], 0) <= 0 ? 0 : 1
    const k = (y * tw + x) * 4
    out.data.set(palette[group], k)
    out.data[k + 3] = weightedMedian(alpha.flatMap((a, i) => labels[i] === group ? [[a, weights[i]]] : []))
  }
  return out
}
