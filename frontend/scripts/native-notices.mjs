import { execFileSync } from 'node:child_process'
import { readFile, readdir, writeFile, mkdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { gzipSync } from 'node:zlib'

const root = fileURLToPath(new URL('../../', import.meta.url))
const project = join(root, 'frontend/src-tauri')
const supplements = join(root, 'frontend/scripts/license-supplements')
const output = join(project, 'gen/license-notices.gz')
const manifestPath = join(project, 'gen/license-notices.json')
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const inputs = ['LICENSE', 'THIRD_PARTY_NOTICES.md', 'frontend/package-lock.json',
  'frontend/src-tauri/Cargo.toml', 'frontend/src-tauri/Cargo.lock', 'frontend/scripts/native-notices.mjs',
  ...(await readdir(supplements)).sort().map(name => `frontend/scripts/license-supplements/${name}`)]
const hashes = Object.fromEntries(await Promise.all(inputs.map(async name => [name, hash(await readFile(join(root, name)))])))

if (process.argv.includes('--check')) {
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  if (JSON.stringify(hashes) !== JSON.stringify(manifest.inputs) || hash(await readFile(output)) !== manifest.bundle) {
    throw new Error('Embedded licenses are stale. Run npm run licenses (or npm run licenses -- --mirror).')
  }
} else {
  const args = ['metadata', '--locked', '--format-version', '1', '--filter-platform', 'x86_64-pc-windows-msvc']
  if (process.argv.includes('--mirror')) args.unshift('--config', 'source.crates-io.replace-with="rsproxy"', '--config', 'source.rsproxy.registry="sparse+https://rsproxy.cn/index/"')
  if (process.argv.includes('--offline')) args.unshift('--offline')
  const metadata = JSON.parse(execFileSync('cargo', args, { cwd: project, encoding: 'utf8', maxBuffer: 20_000_000 }))
  const used = new Set(metadata.resolve.nodes.map(node => node.id))
  const sections = ['Pixel Regrid — License and third-party notices\nSource: https://github.com/mmm-2006/Pixel-Regrid\nIncludes runtime and build dependencies.\n']
  for (const name of ['LICENSE', 'THIRD_PARTY_NOTICES.md']) sections.push(`${name}\n\n${await readFile(join(root, name), 'utf8')}`)
  async function licenses(folder, name, version, description) {
    const files = (await readdir(folder, { withFileTypes: true }))
      .filter(entry => entry.isFile() && /^(licen[sc]e|copying|notice|copyright)([._-]|$)/i.test(entry.name))
      .map(entry => entry.name).sort()
    const bodies = await Promise.all(files.map(async file => `${file}\n${await readFile(join(folder, file), 'utf8')}`))
    if (!bodies.length) {
      // Some published crates omit upstream license files. Exact-version copies are retained in source.
      bodies.push(await readFile(join(supplements, `${name}-${version}.txt`), 'utf8'))
    }
    sections.push(`${'='.repeat(72)}\n${name} ${version}\n${description}\n\n${bodies.join('\n\n')}`)
  }
  for (const p of metadata.packages.filter(p => p.source && used.has(p.id)).sort((a, b) => a.name.localeCompare(b.name) || a.version.localeCompare(b.version))) {
    await licenses(dirname(p.manifest_path), p.name, p.version, `License: ${p.license || 'see license file'}\nRepository: ${p.repository || p.homepage || ''}`)
  }
  for (const name of ['@tauri-apps/api', '@tauri-apps/plugin-dialog']) {
    const folder = join(root, 'frontend/node_modules', name)
    const p = JSON.parse(await readFile(join(folder, 'package.json'), 'utf8'))
    await licenses(folder, name, p.version, `License: ${p.license}`)
  }
  const bundle = gzipSync(Buffer.from(sections.join('\n\n')), { level: 9 })
  await mkdir(dirname(output), { recursive: true })
  await writeFile(output, bundle)
  await writeFile(manifestPath, JSON.stringify({ inputs: hashes, bundle: hash(bundle) }, null, 2))
  console.log(`Embedded licenses: ${bundle.length} compressed bytes`)
}
