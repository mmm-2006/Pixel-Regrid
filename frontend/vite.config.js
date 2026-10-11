import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'

export default defineConfig(({ mode }) => ({
  plugins: [vue(), ...(mode === 'web' ? [{
    name: 'web-license-notices',
    generateBundle() {
      for (const [source, fileName] of [['LICENSE', 'LICENSE.txt'], ['THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_NOTICES.txt']]) {
        this.emitFile({ type: 'asset', fileName, source: readFileSync(new URL(`../${source}`, import.meta.url), 'utf8') })
      }
    },
  }] : [])],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
}))
