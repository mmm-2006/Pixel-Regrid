// Generate showcase pixels using the same algorithm modules as the desktop worker.
import { readFile, writeFile } from 'node:fs/promises'
import { prepareImage, layoutPrepared, explain } from '../src/pixel/core.js'
import { imageInfo, fittedSize } from '../src/pixel/image.js'

const inputs = JSON.parse(await readFile(process.argv[2], 'utf8'))
const examples = []
for (const input of inputs) {
  const source = { ...input.image, data: new Uint8Array(Buffer.from(input.image.data, 'base64')) }
  const base = { direct: false, method: 'center', layout: 'original', resample: 'pixel',
    width: 32, height: 32, palette_size: 32, detail: 1, alpha_threshold: 1 }
  const prepared = prepareImage(source, base)
  if (prepared.recovery !== 'grid') throw new Error(`${input.name}: automatic grid recovery failed`)
  const restored = layoutPrepared(prepared.image, prepared.recovery, base)
  const variants = input.name === 'ice-cream'
    ? [['grid', {}], ['crop', { layout: 'keep', width: restored.info.subject[0], height: restored.info.subject[1] }],
      ['fit', { layout: 'fit', width: 20, height: 32 }]]
    : [['grid', {}], ['fit', { layout: 'canvas_fit', width: 32, height: 32, resample: 'k-centroid' }]]
  for (const [variant, changes] of variants) {
    const options = { ...base, ...changes }
    const result = layoutPrepared(prepared.image, prepared.recovery, options)
    const outputInfo = imageInfo(result.image, 'grid', options.alpha_threshold)
    examples.push({ name: `${input.name}-${variant}`, source: input.source, options, info: result.info,
      output_subject: outputInfo.subject,
      scaled_size: ['fit', 'canvas_fit'].includes(options.layout)
        ? fittedSize(...(options.layout === 'fit' ? result.info.subject : result.info.grid), options.width, options.height) : null,
      explanation: explain(result.info, options),
      image: { width: result.image.width, height: result.image.height,
        data: Buffer.from(result.image.data).toString('base64') } })
  }
}
await writeFile(process.argv[3], JSON.stringify(examples), 'utf8')
for (const item of examples) console.log(`${item.name}: grid ${item.info.grid.join('x')}, subject ${item.info.subject.join('x')}, output ${item.image.width}x${item.image.height}`)
