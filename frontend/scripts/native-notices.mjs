import { execFileSync } from 'node:child_process'
import { readFile, readdir, writeFile, mkdir } from 'node:fs/promises'
import { dirname, resolve, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const project = fileURLToPath(new URL('../src-tauri/', import.meta.url))
const args = ['metadata', '--locked', '--format-version', '1', '--filter-platform', 'x86_64-pc-windows-msvc']
if (process.argv.includes('--mirror')) args.unshift('--config', 'source.crates-io.replace-with="rsproxy"', '--config', 'source.rsproxy.registry="sparse+https://rsproxy.cn/index/"', '--offline')
const metadata = JSON.parse(execFileSync('cargo', args, { cwd: project, encoding: 'utf8', maxBuffer: 20_000_000 }))
const used = new Set(metadata.resolve.nodes.map(node => node.id))
const sections = ['Perfect Pixel JS third-party notices\nIncludes Rust runtime/build dependencies and Tauri JavaScript adapters.\nApplication algorithm attribution is in THIRD_PARTY_NOTICES.md.\n']
async function licenses(folder, title, fallback) {
  const files = (await readdir(folder)).filter(name => /^(license|copying|notice|copyright)([._-]|$)/i.test(name))
  const bodies = []
  for (const file of files) {
    try { bodies.push(`${file}\n${await readFile(join(folder, file), 'utf8')}`) } catch {}
  }
  sections.push(`${'='.repeat(72)}\n${title}\n${fallback}\n\n${bodies.join('\n\n') || 'No standalone license text was included in this package; see the stated SPDX license and upstream repository.'}`)
}
for (const p of metadata.packages.filter(p => p.source && used.has(p.id)).sort((a, b) => a.name.localeCompare(b.name))) {
  await licenses(dirname(p.manifest_path), `${p.name} ${p.version}`, `License: ${p.license || 'see license file'}\nRepository: ${p.repository || p.homepage || ''}`)
}
for (const name of ['@tauri-apps/api', '@tauri-apps/plugin-dialog']) {
  const folder = fileURLToPath(new URL(`../node_modules/${name}/`, import.meta.url))
  const p = JSON.parse(await readFile(join(folder, 'package.json'), 'utf8'))
  await licenses(folder, `${name} ${p.version}`, `License: ${p.license}`)
}
const argument = process.argv.find(arg => arg.startsWith('--output='))
const output = argument ? argument.slice('--output='.length) : resolve(project, '../../dist/PerfectPixel-JS/RUST_NOTICES.txt')
await mkdir(dirname(output), { recursive: true })
await writeFile(output, sections.join('\n\n'), 'utf8')
console.log(`Third-party notices: ${output}`)
