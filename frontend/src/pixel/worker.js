import { prepareImage, layoutPrepared, validateOptions } from './core.js'
let cachedKey = null, cached = null
self.onmessage = ({ data: { id, source, options } }) => {
  try {
    const start = performance.now(), o = validateOptions(options)
    const key = JSON.stringify([source.cacheKey, o.direct, o.method, o.grid,
      ['pixel', 'k-centroid'].includes(o.resample) && ['fit', 'canvas_fit'].includes(o.layout)])
    if (!source.cacheKey || key !== cachedKey) { cached = prepareImage(source, o); cachedKey = key }
    const result = layoutPrepared(cached.image, cached.recovery, o)
    if (result.image.data === cached.image.data) result.image = { ...result.image, data: result.image.data.slice() }
    self.postMessage({ id, ok: true, ...result, milliseconds: performance.now() - start }, [result.image.data.buffer])
  } catch (error) { self.postMessage({ id, ok: false, error: error.message }) }
}
