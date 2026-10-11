import test from 'node:test'
import assert from 'node:assert/strict'
import { unzipSync } from 'fflate'
import { createBrowserBridge } from '../src/browserBridge.js'
import { processImage } from '../src/pixel/core.js'
import { makeImage } from '../src/pixel/image.js'

async function fixture(block) {
  const image = makeImage(4, 4)
  for (let i = 0; i < image.data.length; i += 4) image.data.set([20, 80, 140, 128], i)
  const downloads = [], stored = []
  const api = createBrowserBridge({
    storage: { getItem() { return '{}' }, setItem(key, value) { stored.push(JSON.parse(value)) } },
    async decode(file) { if (file.name === 'bad.png') throw new Error('损坏图片'); return image },
    async encode(result) { return new Blob([result.data]) },
    preview(result) { return { width: result.width, height: result.height, src: 'data:image/png;base64,test' } },
    download(blob, name) { downloads.push({ blob, name }) },
    createLane() { return { cancel() {}, async run(source, options) { if (block) await block(); return { ok: true, ...processImage(source, options) } } } },
  })
  await api.bootstrap()
  const state = await api.add_files([
    { name: 'same.png', size: 1, lastModified: 1, webkitRelativePath: 'a/same.png' },
    { name: 'same.png', size: 2, lastModified: 2, webkitRelativePath: 'b/same.png' },
    { name: 'bad.png', size: 3, lastModified: 1 },
    { name: 'README.md', size: 4, lastModified: 1 },
  ])
  return { api, state, downloads, stored }
}
async function completed(api) {
  for (let i = 0; i < 100; i++) {
    const state = await api.get_state()
    if (!state.busy) return state
    await new Promise(resolve => setTimeout(resolve, 0))
  }
  throw new Error('export did not complete')
}
test('web batch exports successful images once in a ZIP with distinct names, and continues after a corrupt file', async () => {
  const f = await fixture()
  assert.equal(f.state.files.length, 3)
  const options = { direct: true, layout: 'canvas_fit', width: 8, height: 8, resample: 'nearest' }
  assert.equal((await f.api.start_export(f.state.files.map(file => file.key), options)).ok, true)
  options.width = 64
  const state = await completed(f.api)
  assert.deepEqual(state.files.map(file => file.status), ['success', 'success', 'error'])
  assert.deepEqual(state.files[0].size, [8, 8]); assert.equal(f.stored.at(-1).width, 8)
  assert.equal(f.downloads.length, 1); assert.equal(f.downloads[0].name, 'pixel-regrid.zip')
  const entries = unzipSync(new Uint8Array(await f.downloads[0].blob.arrayBuffer()))
  assert.deepEqual(Object.keys(entries), ['same_regrid.png', 'same_regrid_2.png'])
  assert.deepEqual([...entries['same_regrid.png']].slice(0, 4), [20, 80, 140, 128])
  await f.api.open_output(); assert.equal(f.downloads.length, 2)
})
test('web cancellation finishes the active image, skips remaining ones, and downloads its PNG', async () => {
  let enteredResolve, release
  const entered = new Promise(resolve => { enteredResolve = resolve })
  const blocked = new Promise(resolve => { release = resolve })
  const f = await fixture(async () => { enteredResolve(); await blocked })
  await f.api.start_export(f.state.files.map(file => file.key), { direct: true })
  await entered
  assert.equal((await f.api.remove_files([f.state.files[0].key])).ok, false)
  assert.equal((await f.api.configure({})).ok, false)
  await f.api.cancel(); release()
  const state = await completed(f.api)
  assert.deepEqual(state.files.map(file => file.status), ['success', 'cancelled', 'cancelled'])
  assert.equal(f.downloads[0].name, 'same_regrid.png')
})
test('invalid selection and options do not start a web export; stale settings and denied storage are recoverable', async () => {
  const f = await fixture()
  assert.equal((await f.api.start_export(['missing'], {})).ok, false)
  assert.equal((await f.api.start_export([f.state.files[0].key], { width: 0 })).ok, false)
  assert.equal((await f.api.get_state()).busy, false)
  assert.equal(f.downloads.length, 0)
  assert.equal((await f.api.open_output()).ok, false)
  const api = createBrowserBridge({ storage: { getItem() { throw new Error('denied') }, setItem() { throw new Error('denied') } } })
  assert.equal((await api.bootstrap()).options.width, 32)
  assert.equal((await api.configure({ direct: true })).ok, true)
  api.dispose()
})
