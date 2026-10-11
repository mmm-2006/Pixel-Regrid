import { WorkerLane } from './workerLane.js'
import { invoke as nativeInvoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { open as nativeOpen } from '@tauri-apps/plugin-dialog'
import { DEFAULTS, validateOptions, explain } from './pixel/core.js'
import { nearest } from './pixel/image.js'
export function toBase64(bytes) {
  let text = ''
  for (let start = 0; start < bytes.length; start += 32768) text += String.fromCharCode(...bytes.subarray(start, start + 32768))
  return btoa(text)
}
export function fromBase64(text) { return Uint8Array.from(atob(text), char => char.charCodeAt(0)) }
export function shellPath(path) {
  const slash = String.fromCharCode(92), prefix = slash + slash + '?' + slash
  if (path.startsWith(prefix + 'UNC' + slash)) return slash + slash + path.slice(8)
  return path.startsWith(prefix) ? path.slice(4) : path
}
export async function createTauriBridge(runtime = {}) {
  const invoke = runtime.invoke || nativeInvoke, open = runtime.open || nativeOpen
  const currentWindow = runtime.window || getCurrentWindow()
  const state = { ok: true, revision: 0, files: [], busy: false, cancelling: false, closing: false,
    progress: { done: 0, total: 0 }, status: 'JavaScript 实验版就绪', details: [], output_dir: '' }
  let options = { ...DEFAULTS }, settings = {}, lastOutput = '', cached = null, previewGeneration = 0, sourceSerial = 0
  const createLane = runtime.createLane || (() => new WorkerLane())
  const previewLane = createLane(), exportLane = createLane()
  const touch = (status = state.status) => { state.revision++; state.status = status }
  const snapshot = () => structuredClone(state)
  const idle = () => { if (state.busy || state.closing) throw new Error('请等待当前任务结束') }
  const saveSettings = () => invoke('store_settings', { settings: { ...settings, options, output_dir: state.output_dir } })
  const fileAt = key => { const file = state.files.find(file => file.key === key); if (!file) throw new Error('请先导入图片'); return file }
  async function readSource(key) {
    fileAt(key)
    if (cached?.key === key) return cached.source
    const raw = await invoke('read_image', { key }), source = { ...raw, cacheKey: `${key}:${++sourceSerial}`, data: fromBase64(raw.data) }
    cached = { key, source }; return source
  }
  async function imagePreview(image, limit = 2048) {
    const scale = Math.min(1, limit / Math.max(image.width, image.height))
    const smaller = scale < 1 ? nearest(image, Math.max(1, Math.round(image.width * scale)), Math.max(1, Math.round(image.height * scale))) : image
    const src = await invoke('encode_preview', { data: toBase64(smaller.data), width: smaller.width, height: smaller.height })
    return { src, width: image.width, height: image.height, limited: scale < 1 }
  }
  function append(entries) {
    let added = 0
    for (const entry of entries) if (!state.files.some(file => file.key === entry.key)) { state.files.push({ ...entry, status: 'pending', output: null, size: null, error: null }); added++ }
    touch(`添加 ${added} 张图片`); return snapshot()
  }
  async function exportFiles(keys, input) {
    const current = validateOptions(input), files = [...new Set(keys)].map(fileAt)
    if (!files.length) throw new Error('请先添加图片')
    state.busy = true; state.cancelling = false; options = current
    try { await saveSettings() } catch (error) { state.busy = false; throw error }
    state.details = []; state.progress = { done: 0, total: files.length }
    files.forEach(file => Object.assign(file, { status: 'waiting', output: null, error: null, size: null }))
    touch('开始导出…')
    void (async () => {
      let success = 0, failed = 0
      try {
        for (const file of files) {
          if (state.cancelling) break
          file.status = 'working'; touch(`处理中 ${state.progress.done + 1}/${files.length}：${file.name}`)
          try {
            const source = await readSource(file.key), result = await exportLane.run(source, current)
            if (!result.ok) throw new Error(result.error || '处理已取消')
            const image = result.image, output = await invoke('save_image', { key: file.key, data: toBase64(image.data), width: image.width, height: image.height, outputDir: state.output_dir })
            lastOutput = output; success++
            Object.assign(file, { status: 'success', output, size: [image.width, image.height] })
            state.details.push(`成功 · ${file.name} → ${image.width}×${image.height} · 算法 ${result.milliseconds.toFixed(0)} ms\n${output}`)
          } catch (error) { failed++; Object.assign(file, { status: 'error', error: error.message }); state.details.push(`失败 · ${file.path}\n${error.message}`) }
          state.progress.done++; touch()
        }
        files.filter(file => file.status === 'waiting').forEach(file => { file.status = 'cancelled' })
        touch(`${state.cancelling ? '已取消' : '完成'}：成功 ${success} 张，失败 ${failed} 张，未处理 ${files.length - state.progress.done} 张`)
      } finally { state.busy = false; touch(); if (state.closing) await currentWindow.destroy() }
    })()
    return snapshot()
  }
  const methods = {
    async license_notices() { return { ok: true, text: await invoke('license_notices') } },
    async bootstrap() {
      settings = await invoke('load_settings')
      try { options = validateOptions(settings.options || {}) } catch { options = { ...DEFAULTS } }
      state.output_dir = typeof settings.output_dir === 'string' ? settings.output_dir : ''
      return { ...snapshot(), options }
    },
    async get_state(revision) { return revision === state.revision ? { ok: true, unchanged: true } : snapshot() },
    async configure(input) { idle(); options = validateOptions(input); await saveSettings(); return { ok: true } },
    async choose_files() {
      idle()
      const paths = await open({ multiple: true, filters: [{ name: '图片', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff'] }] })
      if (!paths) return { ok: true }
      return append(await invoke('add_paths', { paths: Array.isArray(paths) ? paths : [paths] }))
    },
    async choose_folder() {
      idle(); const folder = await open({ directory: true })
      if (!folder) return { ok: true }
      state.busy = true; state.cancelling = false; touch('正在扫描文件夹…')
      try {
        const scan = await invoke('scan_folder', { folder, outputDir: state.output_dir })
        append(scan.entries); state.details.push(...scan.warnings)
      } finally { state.busy = false; touch(); if (state.closing) await currentWindow.destroy() }
      return snapshot()
    },
    async remove_files(keys) { idle(); methods.cancel_preview(); state.files = state.files.filter(file => !keys.includes(file.key)); cached = null; touch('已移除选中图片'); return snapshot() },
    async choose_output(reset) {
      idle(); const folder = reset ? '' : await open({ directory: true })
      if (reset || folder) { state.output_dir = folder; await saveSettings(); touch() }
      return snapshot()
    },
    async cancel_preview() { previewGeneration++; previewLane.cancel(); return { ok: true } },
    async preview(key, input) {
      const generation = ++previewGeneration, current = validateOptions(input)
      previewLane.cancel()
      const source = await readSource(key)
      if (generation !== previewGeneration) return { ok: false, cancelled: true }
      const original = await imagePreview(source)
      if (generation !== previewGeneration) return { ok: false, cancelled: true }
      const result = await previewLane.run(source, current)
      if (generation !== previewGeneration || result.cancelled) return { ok: false, cancelled: true }
      if (!result.ok) return { ok: true, original, output: null, error: result.error, info: null }
      const output = await imagePreview(result.image)
      if (generation !== previewGeneration) return { ok: false, cancelled: true }
      return { ok: true, original, output, info: result.info, error: null, ...explain(result.info, current) }
    },
    async thumbnail(key) { return { ok: true, image: await imagePreview(await readSource(key), 64) } },
    async start_export(keys, input) { idle(); methods.cancel_preview(); return exportFiles(keys, input) },
    async cancel() { state.cancelling = true; await invoke('cancel_scan'); touch('正在取消，当前图片完成后停止…'); return snapshot() },
    async open_output(key) { const path = state.files.find(file => file.key === key)?.output || lastOutput; if (!path) throw new Error('处理成功后可打开输出文件夹'); await invoke('open_output', { path: shellPath(path) }); return { ok: true } },
  }
  const api = Object.fromEntries(Object.entries(methods).map(([name, fn]) => [name, async (...args) => {
    try { return await fn(...args) } catch (error) { return { ok: false, error: String(error.message || error) } }
  }]))
  await currentWindow.onDragDropEvent(async ({ payload }) => {
    if (payload.type !== 'drop' || state.busy) return
    try { append(await invoke('add_paths', { paths: payload.paths })) } catch (error) { state.details.push(String(error)); touch('添加图片失败，请查看处理记录') }
  })
  await currentWindow.onCloseRequested(event => {
    methods.cancel_preview()
    if (state.busy) { event.preventDefault(); state.closing = true; state.cancelling = true; invoke('cancel_scan').catch(() => {}); touch('正在安全退出，当前图片完成后关闭…') }
  })
  return api
}
