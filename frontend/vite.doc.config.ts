import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * Second build: the document pages (doc.html: the /v/{token} verify page and the lazily loaded
 * /a/{token} approver page). Built on its own, after the studio and public form, into the same
 * dist/ so nginx serves it next to them; keeping it separate means it never changes how the
 * public form bundle is split (DESIGN 18). The dev server (vite.config.ts) serves it too.
 */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  build: {
    emptyOutDir: false,
    rolldownOptions: {
      input: { doc: path.resolve(import.meta.dirname, 'doc.html') },
    },
  },
})
