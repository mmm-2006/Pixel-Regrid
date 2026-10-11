import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFile, mkdir, copyFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { dirname, resolve, extname, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { unzipSync } from 'fflate'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const output = resolve(root, '.test_tmp/browser-smoke')
await mkdir(output, { recursive: true })
const executablePath = process.env.BROWSER_EXECUTABLE || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/chromium', '/usr/bin/google-chrome',
].find(existsSync)
assert.ok(executablePath, 'Set BROWSER_EXECUTABLE to an installed Chromium browser')
const server = createServer(async (req, res) => {
  try {
    const relative = decodeURIComponent(new URL(req.url, 'http://localhost').pathname).replace(/^\/Pixel-Regrid\//, '') || 'index.html'
    const path = resolve(root, 'frontend/dist-web', relative)
    if (!path.startsWith(resolve(root, 'frontend/dist-web') + sep)) throw new Error('Invalid path')
    const mime = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.png': 'image/png' }[extname(path)] || 'application/octet-stream'
    res.writeHead(200, { 'Content-Type': mime }); res.end(await readFile(path))
  } catch { res.writeHead(404); res.end() }
})
let browser
try {
  const url = process.env.WEB_TEST_URL || await new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}/Pixel-Regrid/`)))
  browser = await chromium.launch({ executablePath, headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, acceptDownloads: true })
  const errors = [], requests = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => requests.push({ url: request.url(), method: request.method() }))
  await page.goto(url)
  await page.getByRole('button', { name: '添加图片', exact: true }).waitFor()
  await page.waitForFunction(() => !document.querySelector('.import-actions button').disabled)
  assert.equal(await page.getByRole('button', { name: '切换像素网格' }).getAttribute('aria-pressed'), 'true')
  const metadata = JSON.parse(await readFile(resolve(root, 'docs/assets/examples.json'), 'utf8'))
  const ice = metadata.examples.find(example => example.name === 'ice-cream-grid')
  const table = metadata.examples.find(example => example.name === 'enchanting-table-grid')
  const upload = async paths => {
    const chooser = page.waitForEvent('filechooser')
    await page.getByRole('button', { name: '添加图片', exact: true }).click()
    await (await chooser).setFiles(paths)
  }
  await upload(resolve(root, ice.source))
  await page.waitForFunction(() => document.querySelector('.preview-info')?.textContent.includes('网格 42×42'))
  await page.getByRole('button', { name: '透明噪点阈值说明' }).hover()
  assert.equal(await page.getByRole('tooltip').isVisible(), true)
  await page.mouse.move(500, 30)
  assert.equal(await page.getByRole('tooltip').isVisible(), false)
  const pngDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出全部', exact: true }).click()
  const png = await pngDownload; const pngPath = resolve(output, 'ice-grid.png')
  await png.saveAs(pngPath)
  const pngBytes = await readFile(pngPath)
  assert.equal(pngBytes.readUInt32BE(16), 42); assert.equal(pngBytes.readUInt32BE(20), 42)
  await page.getByRole('button', { name: '裁到主体大小', exact: true }).click()
  await page.waitForFunction(() => [...document.querySelectorAll('.image-heading small')].at(-1)?.textContent.includes('20 × 35'))
  await page.getByRole('button', { name: '网格还原', exact: true }).click()
  const tableSource = table?.source || metadata.examples.find(example => example.source.includes('advanced_enchanting_table_top_diamond_ai')).source
  await upload(resolve(root, tableSource))
  const zipDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出全部', exact: true }).click()
  const zip = await zipDownload; const zipPath = resolve(output, 'batch.zip')
  await zip.saveAs(zipPath)
  const entries = unzipSync(new Uint8Array(await readFile(zipPath)))
  assert.equal(Object.keys(entries).length, 2)
  const sizes = Object.values(entries).map(bytes => { const b = Buffer.from(bytes); return [b.readUInt32BE(16), b.readUInt32BE(20)] })
  assert.ok(sizes.some(size => size[0] === 42 && size[1] === 42))
  assert.ok(sizes.some(size => size[0] === 30 && size[1] === 30))
  await page.getByRole('listbox').getByRole('option').nth(1).click()
  await page.getByRole('button', { name: '32 × 32', exact: true }).click()
  await page.getByRole('combobox', { name: '缩放算法' }).selectOption('k-centroid')
  await page.waitForFunction(() => [...document.querySelectorAll('.image-heading small')].at(-1)?.textContent.includes('32 × 32') && !document.querySelector('.updating'))
  const resizedDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: /^导出选中/ }).click()
  const resized = await resizedDownload; const resizedPath = resolve(output, 'table-32.png')
  await resized.saveAs(resizedPath)
  const resizedBytes = await readFile(resizedPath)
  assert.equal(resizedBytes.readUInt32BE(16), 32); assert.equal(resizedBytes.readUInt32BE(20), 32)
  await page.waitForFunction(() => !document.querySelector('.updating'))
  await page.screenshot({ path: resolve(output, 'web.png') })
  await page.reload()
  await page.waitForFunction(() => !document.querySelector('.import-actions button').disabled)
  assert.equal(await page.getByRole('combobox', { name: '缩放算法' }).inputValue(), 'k-centroid')
  assert.equal(await page.getByRole('listbox').getByRole('option').count(), 0)
  const folder = resolve(output, 'folder')
  await mkdir(resolve(folder, 'nested'), { recursive: true })
  await copyFile(pngPath, resolve(folder, 'grid.png'))
  await copyFile(resizedPath, resolve(folder, 'nested/grid.png'))
  const folderChooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: '文件夹', exact: true }).click()
  await (await folderChooser).setFiles(folder)
  await page.waitForFunction(() => document.querySelectorAll('.file-row').length === 2)
  await page.evaluate(base64 => {
    const data = Uint8Array.from(atob(base64), char => char.charCodeAt(0))
    const transfer = new DataTransfer(); transfer.items.add(new File([data], 'dropped.png', { type: 'image/png' }))
    document.querySelector('.app-shell').dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer: transfer }))
  }, pngBytes.toString('base64'))
  await page.waitForFunction(() => document.querySelectorAll('.file-row').length === 3)
  assert.deepEqual(errors, [])
  assert.ok(requests.every(request => request.method === 'GET'), 'Image processing must not upload files')
  assert.ok(requests.every(request => request.url.startsWith(new URL(url).origin)), 'Processing must not contact third-party servers')
  console.log('Browser smoke passed: real image/folder/drop import, 42×42 grid restoration, 20×35 crop, 30×30 → 32×32 k-centroid, PNG/ZIP downloads, local-only processing, persisted options, hover help and default grid.')
} finally {
  await browser?.close()
  await new Promise(resolve => server.close(resolve))
}
