// Adapt the browser worker message surface for algorithm tests in Node.js.
import { parentPort } from 'node:worker_threads'
globalThis.self = { postMessage: (data, transfer) => parentPort.postMessage(data, transfer) }
await import('../src/pixel/worker.js')
parentPort.on('message', data => self.onmessage({ data }))
