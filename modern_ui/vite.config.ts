import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { createHash } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

export default defineConfig({
  base: './',
  plugins: [vue(), {
    name: 'kohya-ui-integrity',
    apply: 'build',
    writeBundle(options, bundle) {
      const sha256: Record<string, string> = {}
      for (const [name, output] of Object.entries(bundle)) {
        const contents = output.type === 'chunk' ? output.code : output.source
        sha256[name] = createHash('sha256').update(contents).digest('hex')
      }
      writeFileSync(resolve(options.dir || 'dist', 'ui-manifest.json'), JSON.stringify({ schema: 1, sha256 }, null, 2))
    },
  }],
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    emptyOutDir: true,
  },
})
