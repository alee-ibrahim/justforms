/**
 * Latin fonts a form theme can choose besides the bundled default, Inter (backend
 * app/theme/fonts.py): built into `/theme-fonts/{id}.css` plus content-hashed `.woff2` files from
 * the SIL OFL @fontsource packages, Latin and Latin Extended subsets only. They are plain CSS, so the public form's
 * JavaScript doesn't grow; a page fetches one only when its theme `@import`s it. The dev server
 * serves the same files.
 */
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import type { Plugin } from 'vite'

export const THEME_FONTS: Record<string, string> = {
  atkinson: '@fontsource-variable/atkinson-hyperlegible-next',
  'ibm-plex-sans': '@fontsource-variable/ibm-plex-sans',
  'source-serif-4': '@fontsource-variable/source-serif-4',
  'noto-sans': '@fontsource-variable/noto-sans',
}

const SUBSETS = /-(latin|latin-ext)-wght-normal\.woff2$/

interface Built {
  css: string
  files: Map<string, Buffer>
}

function build(root: string, id: string, pkg: string): Built {
  const dir = path.join(root, 'node_modules', pkg)
  const source = readFileSync(path.join(dir, 'index.css'), 'utf8')
  const files = new Map<string, Buffer>()
  const blocks: string[] = []
  for (const block of source.split(/(?=\/\*)/)) {
    const m = /url\(\.\/files\/([^)]+)\)/.exec(block)
    if (!m || !SUBSETS.test(m[1])) continue
    const data = readFileSync(path.join(dir, 'files', m[1]))
    const hash = createHash('sha256').update(data).digest('hex').slice(0, 10)
    const name = m[1].replace(/\.woff2$/, `-${hash}.woff2`)
    files.set(name, data)
    blocks.push(block.replace(m[0], `url(/theme-fonts/${name})`).trim())
  }
  const css = `/* ${id}: SIL Open Font License (${pkg}) */\n${blocks.join('\n\n')}\n`
  return { css, files }
}

export function themeFonts(): Plugin {
  let root = process.cwd()
  const cache = new Map<string, Built>()
  const get = (id: string) => {
    if (!cache.has(id)) cache.set(id, build(root, id, THEME_FONTS[id]))
    return cache.get(id)!
  }
  return {
    name: 'justforms-theme-fonts',
    configResolved(config) {
      root = config.root
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const m = /^\/theme-fonts\/([^/?]+)/.exec(req.url ?? '')
        if (!m) return next()
        const css = /^([a-z0-9-]+)\.css$/.exec(m[1])
        if (css && THEME_FONTS[css[1]]) {
          res.setHeader('Content-Type', 'text/css')
          res.end(get(css[1]).css)
          return
        }
        for (const id of Object.keys(THEME_FONTS)) {
          const file = get(id).files.get(m[1])
          if (file) {
            res.setHeader('Content-Type', 'font/woff2')
            res.end(file)
            return
          }
        }
        res.statusCode = 404
        res.end()
      })
    },
    generateBundle() {
      for (const id of Object.keys(THEME_FONTS)) {
        const built = get(id)
        this.emitFile({ type: 'asset', fileName: `theme-fonts/${id}.css`, source: built.css })
        for (const [name, data] of built.files)
          this.emitFile({ type: 'asset', fileName: `theme-fonts/${name}`, source: data })
      }
    },
  }
}
