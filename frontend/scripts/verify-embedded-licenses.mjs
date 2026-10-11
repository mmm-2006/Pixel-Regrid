import { execFileSync } from 'node:child_process'
import { copyFile, mkdir, mkdtemp, readFile, readdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { gunzipSync } from 'node:zlib'
import assert from 'node:assert/strict'

const root = fileURLToPath(new URL('../../', import.meta.url))
execFileSync(process.execPath, [join(root, 'frontend/scripts/native-notices.mjs'), '--check'])
const source = resolve(process.argv[2] || join(root, 'frontend/src-tauri/target/release/pixel-regrid.exe'))
await mkdir(join(root, '.test_tmp'), { recursive: true })
const folder = await mkdtemp(join(root, '.test_tmp/single-exe-'))
const exe = join(folder, 'PixelRegrid-JS.exe')
await copyFile(source, exe)
const expected = gunzipSync(await readFile(join(root, 'frontend/src-tauri/gen/license-notices.gz')))
const actual = execFileSync(exe, ['--licenses'], { cwd: folder, maxBuffer: 10_000_000, timeout: 30_000 })
assert.deepEqual(actual, expected, 'Executable must return the complete embedded license text')
assert.deepEqual(await readdir(folder), ['PixelRegrid-JS.exe'], 'No external license or runtime files should be required')
console.log(`Single-EXE licenses verified: ${actual.length} bytes of text, no companion files`)
