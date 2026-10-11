import { readFile, writeFile } from 'node:fs/promises'
import { Worker } from 'node:worker_threads'
import { once } from 'node:events'
const dest = new URL('../../prototype-results/', import.meta.url)
const references = JSON.parse(await readFile(new URL('references.json', dest), 'utf8'))
const reference = references.find(item => item.name.startsWith('real-') && item.options.resample === 'nearest')
if (!reference) throw new Error('需要至少一张本地 PNG 作为测量输入')
const source = { ...reference.source, cacheKey: reference.name, data: new Uint8Array(Buffer.from(reference.source.data, 'base64')) }
const worker = new Worker(new URL('./worker-node.mjs', import.meta.url)), results = []
try {
  for (const [index, width] of [32, 64, 16, 32].entries()) {
    const pending = once(worker, 'message'), start = performance.now()
    worker.postMessage({ id: index, source, options: { ...reference.options, width, height: width } })
    const [result] = await pending
    if (!result.ok) throw new Error(result.error)
    results.push({ size: width, cached: index > 0, algorithm_ms: result.milliseconds, worker_roundtrip_ms: performance.now() - start })
  }
} finally { await worker.terminate() }
await writeFile(new URL('worker-benchmark.json', dest), JSON.stringify({ name: reference.name,
  width: source.width, height: source.height, note: 'Node.js Worker 测量；不含原生解码、PNG 编码与 WebView2 渲染。', results }, null, 2))
console.table(results)
