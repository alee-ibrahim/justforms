import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

import { themeFonts } from './theme-fonts.ts'

/**
 * Dev server, mirroring nginx.conf: public forms live at /{slug} and load the separate form
 * entry (old /f/{org}/{slug} links redirect); verify and approver links (/v/{token},
 * /a/{token}) the document entry. Studio routes and Vite's own paths are left alone.
 */
const STUDIO = /^\/(login|forms|settings)(\/|$)/
const SLUG = /^\/[a-z0-9][a-z0-9-]{0,99}\/?$/
const OLD_FORM_LINK = /^\/f\/[^/]+\/([a-z0-9][a-z0-9-]{0,99})\/?$/

function publicFormEntry(): Plugin {
  return {
    name: 'justforms-public-form-entry',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const [path, query = ''] = (req.url ?? '/').split('?')
        const old = OLD_FORM_LINK.exec(path)
        if (old) {
          res.statusCode = 301
          res.setHeader('Location', `/${old[1]}${query ? `?${query}` : ''}`)
          res.end()
          return
        }
        if (path.startsWith('/v/') || path.startsWith('/a/')) req.url = '/doc.html'
        else if (SLUG.test(path) && !STUDIO.test(path) && path !== '/') req.url = '/form.html'
        next()
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), publicFormEntry(), themeFonts()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  build: {
    rolldownOptions: {
      // Two apps: the studio (index.html) and the public form (form.html, budget 120 KB gzip).
      // The document pages (doc.html: verify and approver links) are a separate build
      // (vite.doc.config.ts), so they never change how the public form is split into chunks.
      input: {
        studio: path.resolve(import.meta.dirname, 'index.html'),
        form: path.resolve(import.meta.dirname, 'form.html'),
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
