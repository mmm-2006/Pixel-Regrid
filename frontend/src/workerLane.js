// Desktop and web use the same processing worker and cancellation semantics.
export class WorkerLane {
  constructor() { this.worker = null; this.pending = null; this.serial = 0 }
  cancel() {
    if (!this.pending) return
    this.worker?.terminate(); this.worker = null
    this.pending.resolve({ ok: false, cancelled: true }); this.pending = null
  }
  dispose() { this.cancel(); this.worker?.terminate(); this.worker = null }
  async run(source, options) {
    this.cancel()
    const worker = this.worker ||= new Worker(new URL('./pixel/worker.js', import.meta.url), { type: 'module' })
    const id = ++this.serial, copy = source.data.slice()
    return new Promise((resolve, reject) => {
      this.pending = { resolve, reject }
      const finish = (result, error) => {
        if (this.worker !== worker) return
        this.pending = null
        if (error) { worker.terminate(); this.worker = null }
        error ? reject(error) : resolve(result)
      }
      worker.onmessage = ({ data }) => { if (data.id === id) finish(data) }
      worker.onerror = event => finish(null, new Error(event.message || '处理线程失败'))
      worker.postMessage({ id, source: { ...source, data: copy }, options }, [copy.buffer])
    })
  }
}
