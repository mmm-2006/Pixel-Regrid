import { zipSync } from 'fflate'
import { DEFAULTS, validateOptions, explain } from './pixel/core.js'
import { nearest } from './pixel/image.js'
import { WorkerLane } from './workerLane.js'

const IMAGE_FILE = /\.(png|jpe?g|webp|bmp|gif|avif)$/i
const SETTINGS_KEY = 'pixel-regrid.web.options'

function pickFiles(folder) {
  return new Promise(resolve => {
    const input = document.createElement('input')
    input.type = 'file'; input.multiple = true
    input.accept = 'image/png,image/jpeg,image/webp,image/bmp,image/gif,image/avif'
    if (folder) input.webkitdirectory = true
    input.hidden = true
    const finish = files => { input.remove(); resolve(files) }
    input.addEventListener('change', () => finish([...input.files]), { once: true })
    input.addEventListener('cancel', () => finish([]), { once: true })
    document.body.append(input); input.click()
  })
}

async function decodeFile(file) {
  let bitmap
  try {
    bitmap = await createImageBitmap(file, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' })
    const { width, height } = bitmap
    if (width * height > 32_000_000) throw new Error('图片总像素不能超过 3200 万')
    const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height
    const context = canvas.getContext('2d', { willReadFrequently: true })
    context.drawImage(bitmap, 0, 0)
    const data = new Uint8Array(context.getImageData(0, 0, width, height).data)
    let hasAlpha = false
    for (let i = 3; i < data.length; i += 4) if (data[i] < 255) { hasAlpha = true; break }
    return { width, height, data, hasAlpha }
  } catch (error) {
    throw new Error(error.message.includes('3200') ? error.message : `无法读取 ${file.name}，请确认图片未损坏且浏览器支持该格式。`)
  } finally { bitmap?.close() }
}

function canvasFor(image) {
  const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height
  canvas.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(image.data), image.width, image.height), 0, 0)
  return canvas
}
async function encodePng(image) {
  return new Promise((resolve, reject) => canvasFor(image).toBlob(blob => blob ? resolve(blob) : reject(new Error('PNG 编码失败')), 'image/png'))
}
function imagePreview(image, limit = 2048) {
  const scale = Math.min(1, limit / Math.max(image.width, image.height))
  const smaller = scale < 1 ? nearest(image, Math.max(1, Math.round(image.width * scale)), Math.max(1, Math.round(image.height * scale))) : image
  return { src: canvasFor(smaller).toDataURL('image/png'), width: image.width, height: image.height, limited: scale < 1 }
}
function download(blob, name) {
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url; link.download = name; document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
export function outputName(file, used) {
  const base = file.name.replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').replace(/^\.+/, '_') || 'image'
  let name = `${base}_regrid.png`, suffix = 2
  while (used.has(name.toLowerCase())) name = `${base}_regrid_${suffix++}.png`
  used.add(name.toLowerCase()); return name
}

export function createBrowserBridge(runtime = {}) {
  const decode = runtime.decode || decodeFile, encode = runtime.encode || encodePng
  const render = runtime.preview || imagePreview, save = runtime.download || download
  let storage = runtime.storage
  if (!storage) { try { storage = globalThis.localStorage } catch { /* Private or embedded browsing may deny storage access. */ } }
  const lane = () => runtime.createLane ? runtime.createLane() : new WorkerLane()
  const previewLane = lane(), exportLane = lane()
  const state = { ok: true, revision: 0, files: [], busy: false, cancelling: false, closing: false,
    progress: { done: 0, total: 0 }, status: '网页版就绪 · 图片仅在本地处理', details: [], output_dir: '' }
  const sources = new Map()
  let options = { ...DEFAULTS }, serial = 0, cached = null, previewGeneration = 0, lastDownload = null
  const snapshot = () => structuredClone(state)
  const touch = status => { state.revision++; if (status) state.status = status }
  const idle = () => { if (state.busy) throw new Error('请等待当前任务结束') }
  const persist = () => { try { storage?.setItem(SETTINGS_KEY, JSON.stringify(options)) } catch { /* Storage may be disabled; processing still works. */ } }
  const fileAt = key => { const file = state.files.find(file => file.key === key); if (!file) throw new Error('请先导入图片'); return file }
  async function readSource(key) {
    fileAt(key)
    if (cached?.key === key) return cached.source
    const source = { ...await decode(sources.get(key)), cacheKey: key }
    cached = { key, source }; return source
  }
  const methods = {
    async bootstrap() {
      try { options = validateOptions(JSON.parse(storage?.getItem(SETTINGS_KEY) || '{}')) } catch { options = { ...DEFAULTS } }
      return { ...snapshot(), options }
    },
    async get_state(revision) { return revision === state.revision ? { ok: true, unchanged: true } : snapshot() },
    async configure(input) { idle(); options = validateOptions(input); persist(); return { ok: true } },
    async add_files(files) {
      idle(); let added = 0, skipped = 0
      for (const file of files) {
        if (!IMAGE_FILE.test(file.name)) { skipped++; continue }
        const path = file.webkitRelativePath || file.name
        if (state.files.some(entry => entry.path === path && entry.bytes === file.size && entry.modified === file.lastModified)) continue
        const key = `web-${++serial}`; sources.set(key, file)
        state.files.push({ key, name: file.name, path, bytes: file.size, modified: file.lastModified, status: 'pending', output: null, size: null, error: null }); added++
      }
      touch(`添加 ${added} 张图片${skipped ? `，跳过 ${skipped} 个不支持的文件` : ''}`); return snapshot()
    },
    async choose_files() { idle(); return methods.add_files(await (runtime.pick || pickFiles)(false)) },
    async choose_folder() { idle(); return methods.add_files(await (runtime.pick || pickFiles)(true)) },
    async remove_files(keys) {
      idle(); methods.cancel_preview()
      keys.forEach(key => sources.delete(key)); state.files = state.files.filter(file => !keys.includes(file.key)); cached = null
      touch('已移除选中图片'); return snapshot()
    },
    async cancel_preview() { previewGeneration++; previewLane.cancel(); return { ok: true } },
    async preview(key, input) {
      const generation = ++previewGeneration, current = validateOptions(input)
      previewLane.cancel()
      const source = await readSource(key)
      if (generation !== previewGeneration) return { ok: false, cancelled: true }
      const original = await render(source)
      if (generation !== previewGeneration) return { ok: false, cancelled: true }
      const result = await previewLane.run(source, current)
      if (generation !== previewGeneration || result.cancelled) return { ok: false, cancelled: true }
      if (!result.ok) return { ok: true, original, output: null, error: result.error, info: null }
      const output = await render(result.image)
      if (generation !== previewGeneration) return { ok: false, cancelled: true }
      return { ok: true, original, output, info: result.info, error: null, ...explain(result.info, current) }
    },
    async thumbnail(key) { return { ok: true, image: await render(await readSource(key), 64) } },
    async start_export(keys, input) {
      idle(); const current = validateOptions(input), files = [...new Set(keys)].map(fileAt)
      if (!files.length) throw new Error('请先添加图片')
      methods.cancel_preview(); options = current; persist()
      state.busy = true; state.cancelling = false; state.details = []; state.progress = { done: 0, total: files.length }
      files.forEach(file => Object.assign(file, { status: 'waiting', output: null, size: null, error: null }))
      lastDownload = null; touch('开始导出…')
      void (async () => {
        const outputs = [], names = new Set(); let failed = 0
        try {
          for (const file of files) {
            if (state.cancelling) break
            file.status = 'working'; touch(`处理中 ${state.progress.done + 1}/${files.length}：${file.name}`)
            try {
              const result = await exportLane.run(await readSource(file.key), current)
              if (!result.ok) throw new Error(result.error || '处理已取消')
              const blob = await encode(result.image), name = outputName(file, names)
              outputs.push({ name, blob }); Object.assign(file, { status: 'success', output: name, size: [result.image.width, result.image.height] })
              state.details.push(`成功 · ${file.name} → ${result.image.width}×${result.image.height}\n${name}`)
            } catch (error) { failed++; Object.assign(file, { status: 'error', error: error.message }); state.details.push(`失败 · ${file.path}\n${error.message}`) }
            state.progress.done++; touch()
          }
          files.filter(file => file.status === 'waiting').forEach(file => { file.status = 'cancelled' })
          if (outputs.length === 1) lastDownload = outputs[0]
          else if (outputs.length > 1) {
            const entries = Object.create(null)
            for (const output of outputs) entries[output.name] = new Uint8Array(await output.blob.arrayBuffer())
            // PNGs are already compressed. Store entries without recompressing them.
            lastDownload = { name: 'pixel-regrid.zip', blob: new Blob([zipSync(entries, { level: 0 })], { type: 'application/zip' }) }
          }
          touch(`${state.cancelling ? '已取消' : '完成'}：成功 ${outputs.length} 张，失败 ${failed} 张，未处理 ${files.length - state.progress.done} 张`)
          if (lastDownload) {
            try { save(lastDownload.blob, lastDownload.name) }
            catch { touch('结果已生成，请点击“下载结果”保存') }
          }
        } catch (error) {
          state.details.push(`导出失败 · ${error.message}`); touch(`导出失败：${error.message}`)
        } finally { state.busy = false; touch() }
      })()
      return snapshot()
    },
    async cancel() { state.cancelling = true; touch('正在取消，当前图片完成后停止…'); return snapshot() },
    async open_output() {
      idle(); if (!lastDownload) throw new Error('请先导出图片')
      save(lastDownload.blob, lastDownload.name); return { ok: true }
    },
  }
  return { kind: 'browser', dispose() { previewLane.dispose?.(); exportLane.dispose?.(); sources.clear(); cached = null; lastDownload = null },
    ...Object.fromEntries(Object.entries(methods).map(([name, fn]) => [name, async (...args) => {
      try { return await fn(...args) } catch (error) { return { ok: false, error: String(error.message || error) } }
    }])) }
}
