import test from 'node:test'
import assert from 'node:assert/strict'
import { Worker } from 'node:worker_threads'
import { once } from 'node:events'
import { makeImage } from '../src/pixel/image.js'
test('actual processing worker retains cached pixels after transferable preview responses', async () => {
  const worker = new Worker(new URL('../scripts/worker-node.mjs', import.meta.url))
  try {
    const source = makeImage(4, 4)
    for (let k = 0; k < source.data.length; k += 4) source.data.set([17, 81, 233, 128], k)
    source.cacheKey = 'fixture'
    for (let id = 1; id <= 3; id++) {
      const response = once(worker, 'message')
      worker.postMessage({ id, source, options: { direct: true, layout: id === 3 ? 'keep' : 'original', width: 8, height: 8 } })
      const [result] = await response
      assert.equal(result.ok, true); assert.equal(result.id, id)
      assert.equal(result.image.width, id === 3 ? 8 : 4)
      assert.equal(result.image.data.some(v => v === 233), true)
    }
  } finally { await worker.terminate() }
})
