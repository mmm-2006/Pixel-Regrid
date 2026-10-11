import test from 'node:test'
import assert from 'node:assert/strict'
import { createTauriBridge, toBase64, shellPath } from '../src/tauriBridge.js'
import { processImage } from '../src/pixel/core.js'
import { makeImage } from '../src/pixel/image.js'
async function fixture({ block } = {}) {
  const source = makeImage(4, 4)
  for (let k = 0; k < source.data.length; k += 4) source.data.set([23, 79, 141, 128], k)
  const writes = [], settings = []; let close, destroyed = 0
  const api = await createTauriBridge({
    window: { async onDragDropEvent() {}, async onCloseRequested(fn) { close = fn }, async destroy() { destroyed++ } },
    async open() { return ['good', 'bad'] },
    async invoke(command, args) {
      if (command === 'load_settings') return {}
      if (command === 'cancel_scan') return
      if (command === 'store_settings') { settings.push(structuredClone(args.settings)); return }
      if (command === 'add_paths') return args.paths.map(key => ({ key, name: key, path: key }))
      if (command === 'read_image') { if (args.key === 'bad') throw new Error('损坏图片'); return { width: 4, height: 4, hasAlpha: true, data: toBase64(source.data) } }
      if (command === 'save_image') { writes.push(args); return `output_${writes.length}.png` }
      if (command === 'encode_preview') return 'data:image/png;base64,test'
      throw new Error(`unexpected command: ${command}`)
    },
    createLane() { return { cancel() {}, async run(source, options) { if (block) await block(); return { ok: true, ...processImage(source, options), milliseconds: 1 } } } },
  })
  await api.bootstrap(); await api.choose_files()
  return { api, writes, settings, close: event => close(event), destroyed: () => destroyed }
}
async function completed(api) {
  for (let i = 0; i < 100; i++) { const state = await api.get_state(); if (!state.busy) return state; await new Promise(resolve => setTimeout(resolve, 0)) }
  throw new Error('export did not complete')
}
test('JS desktop batch continues after decode failure and exports exact pixels', async () => {
  const f = await fixture()
  const options = { direct: true, layout: 'canvas_fit', width: 8, height: 8, resample: 'nearest' }
  assert.equal((await f.api.start_export(['bad', 'good'], options)).ok, true)
  options.width = 64
  const state = await completed(f.api)
  assert.deepEqual(state.files.map(f => f.status), ['success', 'error'])
  assert.deepEqual(state.progress, { done: 2, total: 2 })
  assert.equal(f.writes[0].width, 8)
  assert.deepEqual([...Buffer.from(f.writes[0].data, 'base64').slice(0, 4)], [23, 79, 141, 128])
  assert.equal(f.settings.at(-1).options.width, 8)
})
test('cancel and closing finish the active save and do not start remaining images', async () => {
  let release, enteredResolve
  const entered = new Promise(resolve => { enteredResolve = resolve })
  const blocked = new Promise(resolve => { release = resolve })
  const f = await fixture({ block: async () => { enteredResolve(); await blocked } })
  await f.api.start_export(['good', 'bad'], { direct: true })
  await entered
  assert.equal((await f.api.configure({})).ok, false)
  assert.equal((await f.api.remove_files(['good'])).ok, false)
  assert.equal((await f.api.start_export(['good'], {})).ok, false)
  let prevented = false; f.close({ preventDefault() { prevented = true } })
  assert.equal(prevented, true); assert.equal(f.destroyed(), 0)
  release(); const state = await completed(f.api)
  assert.deepEqual(state.files.map(f => f.status), ['success', 'cancelled'])
  assert.equal(f.writes.length, 1); assert.equal(f.destroyed(), 1)
})
test('invalid selection and removed stretch are rejected before export', async () => {
  const f = await fixture()
  assert.equal((await f.api.start_export(['unknown'], {})).ok, false)
  assert.equal((await f.api.configure({ layout: 'stretch' })).ok, false)
  assert.equal((await f.api.get_state()).busy, false)
  assert.equal(f.writes.length, 0)
})
test('Explorer receives normal drive and UNC paths rather than extended filesystem prefixes', () => {
  const slash = String.fromCharCode(92), drive = `C:${slash}图片${slash}output.png`, unc = `${slash}${slash}server${slash}images`
  assert.equal(shellPath(`${slash}${slash}?${slash}${drive}`), drive)
  assert.equal(shellPath(`${slash}${slash}?${slash}UNC${slash}server${slash}images`), unc)
  assert.equal(shellPath(drive), drive)
})
