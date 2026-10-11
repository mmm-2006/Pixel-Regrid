import { readFile, writeFile } from 'node:fs/promises'
import { processImage } from '../src/pixel/core.js'
const dest = new URL('../../prototype-results/', import.meta.url)
const cases = JSON.parse(await readFile(new URL('references.json', dest), 'utf8'))
const results = []; let failures = 0
for (const item of cases) {
  const source = { ...item.source, data: new Uint8Array(Buffer.from(item.source.data, 'base64')) }
  const start = performance.now(); let result, error
  try { result = processImage(source, item.options) } catch (exception) { error = exception.message }
  const jsMs = performance.now() - start
  const row = { name: item.name, exact_required: item.exact_required, python_ms: item.python_ms, javascript_ms: jsMs }
  if (item.error) {
    row.same_error_outcome = Boolean(error); row.python_error = item.error; row.javascript_error = error
    if (!error) failures++
  } else if (error) { row.javascript_error = error; if (item.exact_required) failures++ }
  else {
    const expected = Buffer.from(item.expected.data, 'base64'), actual = result.image.data
    row.python_size = [item.expected.width, item.expected.height]; row.javascript_size = [result.image.width, result.image.height]
    row.same_size = row.python_size.join() === row.javascript_size.join()
    row.python_grid = item.expected.grid; row.javascript_grid = result.info.grid
    row.same_grid = row.python_grid.join() === row.javascript_grid.join()
    row.same_recovery = item.expected.recovery === result.info.recovery
    if (row.same_size) {
      let same = 0, sameAlpha = 0, errorSum = 0, maxDelta = 0
      for (let k = 0; k < actual.length; k += 4) {
        let exact = true
        for (let c = 0; c < 4; c++) { const delta = Math.abs(actual[k + c] - expected[k + c]); errorSum += delta; maxDelta = Math.max(delta, maxDelta); if (delta) exact = false }
        if (exact) same++
        if (actual[k + 3] === expected[k + 3]) sameAlpha++
      }
      row.exact_pixels = same / (actual.length / 4); row.exact_alpha = sameAlpha / (actual.length / 4)
      row.mean_channel_delta = errorSum / actual.length; row.max_channel_delta = maxDelta
    }
    row.exact = row.same_size && row.exact_pixels === 1 && row.same_recovery && row.same_grid
    if (item.exact_required && !row.exact) failures++
  }
  results.push(row)
  console.log(`${row.exact || row.same_error_outcome ? 'MATCH' : item.exact_required ? 'FAIL' : 'DIFF'} ${item.name}: ${jsMs.toFixed(1)} ms / Python ${item.python_ms.toFixed(1)} ms${row.exact_pixels != null ? `; pixels ${(row.exact_pixels * 100).toFixed(2)}%` : ''}${error ? `; ${error}` : ''}`)
}
const summary = { cases: cases.length, required_failures: failures,
  exact_matches: results.filter(r => r.exact || r.same_error_outcome).length,
  differences: results.filter(r => !r.exact && !r.same_error_outcome).length,
  note: '单次算法计时，不含图片解码、线程启动、IPC、PNG 编码。真实图片结果属于实验评估，差异不会被当作通过等价性验证。', results }
await writeFile(new URL('comparison.json', dest), JSON.stringify(summary, null, 2))
console.log(`\n${summary.exact_matches}/${summary.cases} exact matches; ${failures} required failures; ${summary.differences} differences`)
process.exitCode = failures ? 1 : 0
