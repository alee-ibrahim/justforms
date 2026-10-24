// Fails if the initial JavaScript (entry plus static imports) of a public page goes over its
// gzip budget (DESIGN 18): the public form (120 KB) and the document pages for verify and
// approver links (95 KB; the approver page is a lazy chunk). Lazy chunks (calendar, signature
// pad, phonetic keyboard, approver page) are not counted. Run after `vite build`.
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const BUDGETS = { 'form.html': 120 * 1024, 'doc.html': 95 * 1024 }
const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../dist')

let failed = false
for (const [page, budget] of Object.entries(BUDGETS)) {
  const html = readFileSync(path.join(dist, page), 'utf8')
  const entries = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+\.js)"/g)].map((m) => m[1])

  const seen = new Set()
  const queue = [...entries]
  while (queue.length) {
    const file = queue.shift()
    if (seen.has(file)) continue
    seen.add(file)
    const code = readFileSync(path.join(dist, file), 'utf8')
    // Static imports only: `import ... from "./x.js"` and `import "./x.js"`, not `import("./x.js")`.
    for (const m of code.matchAll(/(?:^|[;\n}])\s*import\s*(?:[^'"()]*?from\s*)?["'](\.\/[^"']+\.js)["']/g))
      queue.push(path.posix.join(path.posix.dirname(file), m[1]))
  }

  let total = 0
  console.log(page)
  for (const file of seen) {
    const size = gzipSync(readFileSync(path.join(dist, file))).length
    total += size
    console.log(`${(size / 1024).toFixed(1).padStart(7)} KB  ${file}`)
  }
  console.log(`${(total / 1024).toFixed(1).padStart(7)} KB  total (budget ${budget / 1024} KB gzip)\n`)
  if (total > budget) {
    console.error(`${page} is over budget.`)
    failed = true
  }
}
if (failed) process.exit(1)
