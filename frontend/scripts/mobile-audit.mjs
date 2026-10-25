#!/usr/bin/env node
/**
 * Mobile layout audit: drives a running JustForms (studio, public form, verify and approver
 * pages) with real mobile emulation (isMobile, hasTouch, deviceScaleFactor) in light and dark,
 * screenshots every state and flags:
 *
 * - page-overflow   the document scrolls sideways
 * - offscreen       an element sticks out past the viewport edge (outside any scroller)
 * - clipped-text    text cut off by an overflow-hidden box without an ellipsis
 * - narrow          a form, card, dialog, drawer or sheet narrower than --min-form-width
 * - small-target    an interactive element whose tap area (incl. ::before/::after hit areas and
 *                   its <label>) is smaller than --min-target in either direction
 * - hidden-control  an interactive element cut off by a clipping or scrolling box (e.g. a
 *                   table's action menu off to the side); mark intentional scrollers with
 *                   data-scroll-x ("swipe for more columns") to exempt them
 * - truncated       (warning only) text shortened with an ellipsis
 *
 * Usage (stack running, e.g. `just dev` + mailpit, or the compose stack with --profile dev):
 *   node scripts/mobile-audit.mjs --base http://localhost:5173 --email admin@example.org \
 *     --mailpit http://127.0.0.1:8025 [--path /v/<token>] [--path /a/<token>] \
 *     [--devices "Pixel 7,iPhone 14"] [--schemes light,dark] [--only builder] [--out dir]
 *
 * Signing in uses the local sign-in code flow; the code is read from Mailpit's API. The session
 * is cached in the temp directory and reused while valid (sign-in codes are rate limited). Exit code 1 when any error was found.
 * Writes <out>/report.json and <out>/report.md.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { parseArgs } from 'node:util'

import { chromium, devices as pwDevices, request as pwRequest } from 'playwright'

const { values: args } = parseArgs({
  options: {
    base: { type: 'string', default: process.env.MOBILE_AUDIT_BASE ?? 'http://localhost:5173' },
    email: { type: 'string', default: process.env.MOBILE_AUDIT_EMAIL },
    mailpit: { type: 'string', default: process.env.MOBILE_AUDIT_MAILPIT ?? 'http://127.0.0.1:8025' },
    path: { type: 'string', multiple: true, default: [] },
    devices: { type: 'string' },
    schemes: { type: 'string', default: 'light,dark' },
    only: { type: 'string' },
    out: { type: 'string', default: path.join(os.tmpdir(), 'justforms-mobile-audit') },
    'min-target': { type: 'string', default: '44' },
    'min-form-width': { type: 'string', default: '240' },
    'no-screenshots': { type: 'boolean', default: false },
    help: { type: 'boolean', default: false },
  },
})

if (args.help) {
  console.log(fs.readFileSync(new URL(import.meta.url), 'utf8').split('*/')[0])
  process.exit(0)
}

const BASE = args.base.replace(/\/$/, '')
const OUT = path.resolve(args.out)
const MIN_TARGET = Number(args['min-target'])
const MIN_FORM = Number(args['min-form-width'])
fs.mkdirSync(OUT, { recursive: true })

/** Portrait phones at 320/360/390/412, a 768 tablet and a landscape phone. */
const DEVICE_SET = {
  'Galaxy S9+': pwDevices['Galaxy S9+'], // 320
  'Galaxy S8': pwDevices['Galaxy S8'], // 360
  'iPhone 14': pwDevices['iPhone 14'], // 390
  'Pixel 7': pwDevices['Pixel 7'], // 412
  'iPad Mini': pwDevices['iPad Mini'], // 768
  'Pixel 7 landscape': pwDevices['Pixel 7 landscape'],
}
const deviceNames = args.devices ? args.devices.split(',').map((s) => s.trim()) : Object.keys(DEVICE_SET)
for (const d of deviceNames) if (!DEVICE_SET[d] && !pwDevices[d]) throw new Error(`unknown device ${d}`)
const schemes = args.schemes.split(',').map((s) => s.trim())

// -- sign-in -----------------------------------------------------------------------------------

async function mailpitCode(email, after) {
  const end = Date.now() + 60_000
  while (Date.now() < end) {
    const list = await (await fetch(`${args.mailpit}/api/v1/messages?limit=50`)).json()
    for (const m of list.messages ?? []) {
      if (new Date(m.Created).getTime() < after - 2000) continue
      if (!m.To?.some((t) => t.Address.toLowerCase() === email.toLowerCase())) continue
      const msg = await (await fetch(`${args.mailpit}/api/v1/message/${m.ID}`)).json()
      const hit = /\b(\d{6})\b/.exec(msg.Text ?? '')
      if (hit) return hit[1]
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
  throw new Error(`no sign-in code for ${email} in Mailpit (${args.mailpit})`)
}

async function mailpitLinks(re) {
  try {
    const list = await (await fetch(`${args.mailpit}/api/v1/messages?limit=100`)).json()
    for (const m of list.messages ?? []) {
      const msg = await (await fetch(`${args.mailpit}/api/v1/message/${m.ID}`)).json()
      const hit = re.exec(msg.Text ?? '')
      if (hit) return new URL(hit[0]).pathname
    }
  } catch {
    /* Mailpit is optional for discovery */
  }
  return null
}

const authFile = path.join(os.tmpdir(), `justforms-mobile-audit-auth-${new URL(BASE).host.replace(/\W+/g, '-')}.json`)

async function signIn() {
  if (fs.existsSync(authFile)) {
    const ctx = await pwRequest.newContext({ baseURL: BASE, storageState: authFile })
    const me = await ctx.get('/api/v1/auth/me')
    if (me.ok() && (await me.json())) return ctx
    await ctx.dispose()
  }
  if (!args.email) throw new Error('--email (or MOBILE_AUDIT_EMAIL) is required to sign in')
  const ctx = await pwRequest.newContext({ baseURL: BASE, extraHTTPHeaders: { Origin: BASE } })
  const t0 = Date.now()
  const req = await ctx.post('/api/v1/auth/local/request', { data: { email: args.email } })
  if (!req.ok()) throw new Error(`sign-in code request failed: ${req.status()}`)
  const code = await mailpitCode(args.email, t0)
  const verify = await ctx.post('/api/v1/auth/local/verify', { data: { email: args.email, code } })
  if (!verify.ok()) throw new Error(`sign-in failed: ${verify.status()}`)
  await ctx.storageState({ path: authFile })
  return ctx
}

// -- discovery ---------------------------------------------------------------------------------

async function discover(api) {
  const me = await (await api.get('/api/v1/auth/me')).json()
  const org = me.orgs[0]
  const forms = await (await api.get(`/api/v1/orgs/${org.id}/forms`)).json()
  const published = forms.filter((f) => f.currentVersion !== null)
  published.sort((a, b) => b.submissionCount - a.submissionCount)
  const form = published[0] ?? forms[0]
  if (!form) throw new Error('no forms in the first organisation: create one first')
  const publicForms = []
  for (const f of published.slice(0, 2)) {
    const live = await (await api.get(`/api/v1/public/forms/${f.slug}`)).json()
    publicForms.push({ path: `/${f.slug}`, lang: live.schema?.settings?.language ?? live.form?.settings?.language ?? 'en' })
  }
  let submissionId = null
  if (form.submissionCount > 0) {
    const page = await (await api.get(`/api/v1/forms/${form.id}/submissions?limit=5`)).json()
    submissionId = (page.items ?? page.results ?? [])[0]?.id ?? null
  }
  // An imported submission (copied files, long Jotform ids) on any published form, if there is one.
  let imported = null
  for (const f of published.slice(0, 10)) {
    if (!f.submissionCount) continue
    const page = await (await api.get(`/api/v1/forms/${f.id}/submissions?limit=200`)).json()
    const row = (page.items ?? []).find((r) => r.source === 'jotform_import')
    if (row) {
      imported = { formId: f.id, seq: row.seq }
      break
    }
  }
  const extra = [...args.path]
  if (!extra.some((p) => p.startsWith('/a/'))) {
    const a = await mailpitLinks(/https?:\/\/\S+\/a\/[A-Za-z0-9_-]+/)
    if (a) extra.push(a)
  }
  if (!extra.some((p) => p.startsWith('/login/invite/'))) {
    const i = await mailpitLinks(/https?:\/\/\S+\/login\/invite\/[A-Za-z0-9_-]+/)
    if (i) extra.push(i)
  }
  return { org, form, publicForms, submissionId, imported, extra }
}

// -- in-page checks ----------------------------------------------------------------------------

/* Runs in the page. Keep it self-contained. */
function pageAudit({ minTarget, minForm }) {
  const vw = document.documentElement.clientWidth
  const vh = window.innerHeight
  const out = []
  const seen = new Set()
  const css = (el, pseudo) => getComputedStyle(el, pseudo)
  const isVisible = (el) => {
    const r = el.getBoundingClientRect()
    if (r.width < 1 || r.height < 1) return false
    const s = css(el)
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) === 0) return false
    if (el.closest('[aria-hidden="true"], [inert], .sr-only')) return false
    if (s.position === 'absolute' && s.clip && s.clip.startsWith('rect(0')) return false
    return true
  }
  const label = (el) => {
    const slot = el.getAttribute('data-slot')
    const name =
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40)
    const id = el.id ? `#${el.id}` : ''
    return `${el.tagName.toLowerCase()}${id}${slot ? `[data-slot=${slot}]` : ''}${name ? ` "${name}"` : ''}`
  }
  const push = (type, el, detail) => {
    const key = `${type}|${label(el)}`
    if (seen.has(key)) return
    seen.add(key)
    out.push({ type, el: label(el), detail })
  }
  const clipsX = (s) => ['hidden', 'clip', 'auto', 'scroll'].includes(s.overflowX)

  const docW = document.documentElement.scrollWidth
  if (docW > vw + 1) out.push({ type: 'page-overflow', el: 'html', detail: `scrollWidth ${docW}px > viewport ${vw}px` })

  const all = [...document.body.querySelectorAll('*')].filter(isVisible)
  const offenders = new Set()
  for (const el of all) {
    const r = el.getBoundingClientRect()
    if (r.right <= vw + 1 && r.left >= -1) continue
    let clipped = false
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const s = css(a)
      if (clipsX(s) || s.position === 'fixed') {
        clipped = true
        break
      }
    }
    if (clipped) continue
    if (el.parentElement && offenders.has(el.parentElement)) {
      offenders.add(el)
      continue
    }
    offenders.add(el)
    push('offscreen', el, `x ${Math.round(r.left)}..${Math.round(r.right)} of ${vw}`)
  }

  for (const el of all) {
    const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())
    if (!hasText) continue
    const s = css(el)
    const overX = el.scrollWidth > el.clientWidth + 1 && ['hidden', 'clip'].includes(s.overflowX)
    const overY =
      el.scrollHeight > el.clientHeight + 2 && ['hidden', 'clip'].includes(s.overflowY) && s.webkitLineClamp === 'none'
    if (!overX && !overY) continue
    if (s.textOverflow === 'ellipsis' || s.webkitLineClamp !== 'none') {
      push('truncated', el, `${el.scrollWidth}px text in ${el.clientWidth}px`)
    } else {
      push('clipped-text', el, overX ? `${el.scrollWidth}px text in ${el.clientWidth}px` : `${el.scrollHeight}px text in ${el.clientHeight}px tall box`)
    }
  }

  if (vw >= 320) {
    const boxes = document.querySelectorAll(
      'form, [data-slot=card], [role=dialog], [role=alertdialog], [data-slot=drawer-content], [data-slot=sheet-content], [data-slot=popover-content]',
    )
    for (const el of boxes) {
      if (!isVisible(el)) continue
      const w = el.getBoundingClientRect().width
      const min = Math.min(minForm, Math.round(vw * 0.6))
      if (w < min && el.querySelector('input, textarea, select, button')) push('narrow', el, `${Math.round(w)}px wide (min ${min}px)`)
    }
  }

  const targets = document.querySelectorAll(
    'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=checkbox], [role=radio], [role=switch], [role=menuitem], [role=menuitemcheckbox], [role=menuitemradio], [role=option], [role=combobox], [role=slider], [tabindex="0"]',
  )
  for (const el of targets) {
    if (!isVisible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') continue
    const s = css(el)
    if (s.pointerEvents === 'none') continue
    // Hover cards only add detail for mouse users; touch never opens them.
    if (el.getAttribute('data-slot') === 'hover-card-trigger') continue
    // A focusable <span> carrying a tooltip (full hash, user agent) is a keyboard stop, not a tap target.
    if (el.tagName === 'SPAN' && el.getAttribute('data-slot') === 'tooltip-trigger' && !el.getAttribute('role')) continue
    // Links inside running text are exempt (WCAG 2.5.8 inline exception).
    if (el.tagName === 'A' && s.display === 'inline') {
      const p = el.parentElement
      if (p && (p.innerText || '').trim().length > (el.innerText || '').trim().length + 1) continue
    }
    // Native inputs hidden behind a custom control, or an element nested in a larger target.
    if (el.parentElement?.closest('button, a[href], label, [role=option], [role=menuitem]') && el.tagName !== 'INPUT') continue
    // Wrappers (a focusable span around a disabled button, a tab list) are judged by their children.
    if (el.querySelector('a[href], button, input, select, textarea, [role=tab], [role=button]')) continue
    const r = el.getBoundingClientRect()
    let t = r.top
    let b = r.bottom
    let l = r.left
    let rt = r.right
    for (const pseudo of ['::before', '::after']) {
      const p = css(el, pseudo)
      if (p.content === 'none' || p.position !== 'absolute' || p.display === 'none') continue
      const pt = parseFloat(p.top)
      const pb = parseFloat(p.bottom)
      const pl = parseFloat(p.left)
      const pr = parseFloat(p.right)
      if ([pt, pb, pl, pr].some(Number.isNaN)) continue
      t = Math.min(t, r.top + pt)
      b = Math.max(b, r.bottom - pb)
      l = Math.min(l, r.left + pl)
      rt = Math.max(rt, r.right - pr)
    }
    // An input inside an InputGroup: the whole group is the visual (and focusing) target.
    const group = el.getAttribute('data-slot') === 'input-group-control' || el.getAttribute('data-slot') === 'command-input' ? el.closest('[data-slot=input-group]') : null
    if (group) {
      const gr = group.getBoundingClientRect()
      t = Math.min(t, gr.top)
      b = Math.max(b, gr.bottom)
      l = Math.min(l, gr.left)
      rt = Math.max(rt, gr.right)
    }
    const lbl = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : el.closest('label')
    if (lbl && isVisible(lbl)) {
      const lr = lbl.getBoundingClientRect()
      t = Math.min(t, lr.top)
      b = Math.max(b, lr.bottom)
      l = Math.min(l, lr.left)
      rt = Math.max(rt, lr.right)
    }
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const as = css(a)
      if (!clipsX(as)) continue
      if (a.closest('[data-scroll-x]')) break
      const ar = a.getBoundingClientRect()
      if (r.right > ar.right + 1 || r.left < ar.left - 1) push('hidden-control', el, `x ${Math.round(r.left)}..${Math.round(r.right)} outside ${Math.round(ar.left)}..${Math.round(ar.right)} (${as.overflowX})`)
      break
    }
    const w = rt - l
    const h = b - t
    if (w + 0.5 < minTarget || h + 0.5 < minTarget) push('small-target', el, `${Math.round(w)}x${Math.round(h)}px`)
  }
  return { vw, vh, issues: out }
}

// -- scenarios ---------------------------------------------------------------------------------

const wait = (ms) => new Promise((r) => setTimeout(r, ms))

async function settle(page) {
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})
  await page.evaluate(() => document.fonts.ready)
  await wait(350)
}

async function clickIf(page, locator) {
  const l = locator.first()
  if ((await l.count()) === 0 || !(await l.isVisible().catch(() => false))) return false
  await l.click({ timeout: 5000 }).catch(() => {})
  await wait(400)
  return true
}

async function closeOverlays(page) {
  for (let i = 0; i < 3; i++) {
    if ((await page.locator('[role=dialog], [role=alertdialog], [role=menu], [data-slot=popover-content]').count()) === 0) break
    await page.keyboard.press('Escape')
    await wait(300)
  }
}

/**
 * Each scenario: a URL and states to check. `states` get the page after navigation and return
 * after setting up the state; `null` means "check the page as loaded".
 */
function scenarios(d) {
  const f = d.form
  const formPath = `/forms/${f.id}`
  const list = []
  const add = (name, url, states = [['', null]], opts = {}) => list.push({ name, url, states, ...opts })

  add('sign-in', '/login', [
    ['email', null],
    [
      'code',
      async (page) => {
        // Answer the code request locally: no email, no rate-limit hit.
        await page.route('**/api/v1/auth/local/request', (r) => r.fulfill({ status: 202, body: '' }))
        await page.fill('#email', 'nobody@example.org')
        await page.getByRole('button', { name: /sign-in code/i }).click()
        await page.waitForSelector('#code', { timeout: 10_000 })
      },
    ],
    [
      'error',
      async (page) => {
        await page.goto(`${BASE}/login?error=sso_failed`)
        await settle(page)
      },
    ],
  ], { anonymous: true })
  add('not-found', '/forms/00000000-0000-0000-0000-000000000000/edit')
  add('forms-list', '/forms', [
    ['', null],
    ['user-menu', async (page) => void (await clickIf(page, page.getByRole('button', { name: 'Account' })))],
    ['help', async (page) => void (await clickIf(page, page.getByRole('button', { name: 'Keyboard shortcuts' })))],
    ['create-dialog', async (page) => void (await clickIf(page, page.getByRole('button', { name: /new form|create form/i })))],
  ])
  add('builder', `${formPath}/edit`, [
    ['', null],
    ['add-question', async (page) => void (await clickIf(page, page.getByRole('button', { name: 'Add question' })))],
    [
      'inspector',
      async (page) => {
        await closeOverlays(page)
        await clickIf(page, page.locator('[aria-label="Form canvas"] [data-block], [aria-label="Form canvas"] [role=button]').nth(1))
      },
    ],
    ['form-menu', async (page) => {
      await closeOverlays(page)
      await clickIf(page, page.getByRole('button', { name: 'More form actions' }))
    }],
    ['nav-menu', async (page) => {
      await closeOverlays(page)
      await clickIf(page, page.getByRole('button', { name: /^Edit$/ }))
    }],
    ['ai', async (page) => {
      await closeOverlays(page)
      await clickIf(page, page.getByRole('button', { name: 'AI assistant' }))
    }],
  ])
  // Jotform import (JOTFORM-IMPORT-SCREENS): source tabs, the result with its report, and the
  // responses import up to the column-mapping step (a tiny CSV; nothing is imported).
  add('jotform-import', '/forms/import/jotform', [
    ['', null],
    ['api', async (page) => void (await clickIf(page, page.getByRole('tab', { name: 'API key' })))],
    [
      'result',
      async (page) => {
        await clickIf(page, page.getByRole('tab', { name: 'Source code' }))
        await page.fill(
          '#jf-html',
          '<title>Audit sample</title><ul><li class="form-line jf-required" data-type="control_textbox" id="id_3">' +
            '<label id="label_3" for="input_3">Full name<span class="form-required">*</span></label>' +
            '<input type="text" id="input_3" name="q3_fullName" /></li>' +
            '<li class="form-line" data-type="control_matrix" id="id_4"><label id="label_4">Grid</label></li></ul>',
        )
        await page.getByRole('button', { name: 'Read form' }).click()
        await page.getByRole('heading', { name: 'Check the result' }).waitFor({ timeout: 15_000 })
      },
    ],
  ], { fullPage: true })
  if (f.role === 'owner' && f.currentVersion !== null)
    add('responses-import', `${formPath}/submissions/import`, [
      ['', null],
      [
        'map',
        async (page) => {
          await page.setInputFiles('#jf-export', {
            name: 'audit.csv',
            mimeType: 'text/csv',
            buffer: Buffer.from(['Submission Date,Submission ID,Anything', '2025-01-02 10:00:00,1,x', ''].join(String.fromCharCode(10))),
          })
          await page.getByRole('heading', { name: /Step 2 of 3/ }).waitFor({ timeout: 15_000 })
        },
      ],
    ], { fullPage: true })
  add('org-settings', '/settings', [
    ['', null],
    ['preview-dark', async (page) => void (await clickIf(page, page.getByRole('tab', { name: 'Dark' })))],
  ], { fullPage: true })
  // Organisation settings › Form theme and People (PEOPLE-SCREENS).
  add('org-form-theme', '/settings/form-theme', undefined, { fullPage: true })
  add('people', '/settings/people', [
    ['', null],
    ['invite', async (page) => void (await clickIf(page, page.getByRole('button', { name: 'Invite people' })))],
    [
      'row-menu',
      async (page) => {
        await closeOverlays(page)
        await clickIf(page, page.getByRole('button', { name: /^Actions for / }))
      },
    ],
    [
      'role',
      async (page) => {
        await closeOverlays(page)
        await clickIf(page, page.getByRole('button', { name: /^Actions for / }))
        await clickIf(page, page.getByRole('menuitem', { name: 'Change role' }))
      },
    ],
  ], { fullPage: true })
  add('preview', `${formPath}/preview`)
  add('share', `${formPath}/share`)
  add('settings', `${formPath}/settings`, [
    ['', null],
    [
      'bottom',
      async (page) => {
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
        await wait(300)
      },
    ],
  ], { fullPage: true })
  add('submissions', `${formPath}/submissions?status=all`, [
    ['', null],
    ['filters', async (page) => void (await clickIf(page, page.getByRole('button', { name: /^Filter/ })))],
    ['export', async (page) => {
      await closeOverlays(page)
      await clickIf(page, page.getByRole('button', { name: /export/i }))
    }],
    ['bulk', async (page) => {
      await closeOverlays(page)
      await clickIf(page, page.getByRole('checkbox', { name: /^Select #/ }))
      await clickIf(page, page.getByRole('checkbox', { name: /^Select #/ }).nth(1))
    }],
  ])
  add('submissions-cards', `${formPath}/submissions?status=all`, [
    ['', async (page) => void (await clickIf(page, page.getByRole('radio', { name: 'Cards' })))],
  ], { fullPage: true })
  // The submission's own page (SUBMISSIONS-VIEWER-SCREENS 1): the form view, its tabs, a file preview.
  const viewerSteps = [
    ['', null],
    ['details', async (page) => void (await clickIf(page, page.getByRole('tab', { name: 'Details' })))],
    ['activity', async (page) => void (await clickIf(page, page.getByRole('tab', { name: /^Activity/ })))],
    [
      'file-preview',
      async (page) => {
        await clickIf(page, page.getByRole('tab', { name: 'Answers' }))
        await clickIf(page, page.locator('article button[aria-haspopup=dialog]').first())
      },
    ],
  ]
  if (d.submissionId) add('submission-detail', `${formPath}/submissions?open=${d.submissionId}`, viewerSteps, { fullPage: true })
  if (d.imported)
    add('submission-imported', `/forms/${d.imported.formId}/submissions/${d.imported.seq}`, viewerSteps, { fullPage: true })
  for (const p of d.publicForms) {
    add(`public-${p.lang}`, p.path, [
      ['', null],
      [
        'errors',
        async (page) => {
          await clickIf(page, page.getByRole('button', { name: /^(Next|Submit)$/ }))
        },
      ],
      [
        // Saved progress (SAVED-PROGRESS-SCREENS): type, reload, the restored notice.
        'restored',
        async (page) => {
          await page.getByRole('textbox').first().fill('Test answer')
          await wait(800)
          await page.reload({ waitUntil: 'domcontentloaded' })
          await page.getByRole('button', { name: 'Start over' }).waitFor({ timeout: 5000 })
        },
      ],
      ['start-over', async (page) => void (await clickIf(page, page.getByRole('button', { name: 'Start over' })))],
    ], { anonymous: true, fullPage: true })
  }
  add('public-not-found', '/no-such-form', undefined, { anonymous: true })
  for (const p of d.extra)
    add(
      p.startsWith('/v/')
        ? 'verify'
        : p.startsWith('/a/')
          ? 'approver'
          : p.startsWith('/login/invite/')
            ? 'invite'
            : `page${p.replace(/[^A-Za-z0-9]+/g, '-').slice(0, 80)}`,
      p,
      undefined,
      // Studio pages (/forms/...) are audited signed in.
      { anonymous: !p.startsWith('/forms/'), fullPage: true },
    )
  return args.only ? list.filter((s) => s.name.includes(args.only)) : list
}

// -- main --------------------------------------------------------------------------------------

const api = await signIn()
const data = await discover(api)
await api.dispose()
const browser = await chromium.launch()
const report = []
let errors = 0

for (const deviceName of deviceNames) {
  const { defaultBrowserType: _b, ...device } = DEVICE_SET[deviceName] ?? pwDevices[deviceName]
  for (const scheme of schemes) {
    const dir = path.join(OUT, `${deviceName.replace(/\W+/g, '-')}-${scheme}`)
    fs.mkdirSync(dir, { recursive: true })
    const authed = await browser.newContext({ ...device, colorScheme: scheme, storageState: authFile })
    const anon = await browser.newContext({ ...device, colorScheme: scheme })
    for (const sc of scenarios(data)) {
      const page = await (sc.anonymous ? anon : authed).newPage()
      try {
        await page.goto(BASE + sc.url, { waitUntil: 'domcontentloaded' })
        await settle(page)
        for (const [stateName, setup] of sc.states) {
          if (setup) {
            await closeOverlays(page)
            await setup(page).catch((e) => console.warn(`  ${sc.name}/${stateName}: setup failed: ${e.message.split('\n')[0]}`))
            await settle(page)
          }
          const res = await page.evaluate(pageAudit, { minTarget: MIN_TARGET, minForm: MIN_FORM })
          const name = stateName ? `${sc.name}-${stateName}` : sc.name
          const shot = path.join(dir, `${name}.png`)
          if (!args['no-screenshots']) await page.screenshot({ path: shot, fullPage: !!sc.fullPage && !stateName })
          const errs = res.issues.filter((i) => i.type !== 'truncated')
          errors += errs.length
          report.push({ device: deviceName, scheme, state: name, url: page.url().replace(BASE, ''), viewport: res.vw, screenshot: shot, issues: res.issues })
          console.log(`${errs.length ? 'FAIL' : 'ok  '} ${deviceName} ${scheme} ${name}${errs.length ? ` (${errs.length})` : ''}`)
          for (const i of errs) console.log(`       ${i.type}: ${i.el} ${i.detail}`)
        }
      } catch (e) {
        errors++
        report.push({ device: deviceName, scheme, state: sc.name, url: sc.url, issues: [{ type: 'error', el: '', detail: e.message }] })
        console.log(`ERR  ${deviceName} ${scheme} ${sc.name}: ${e.message.split('\n')[0]}`)
      } finally {
        await page.close()
      }
    }
    await authed.close()
    await anon.close()
  }
}
await browser.close()

fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1))
const byKey = new Map()
for (const r of report)
  for (const i of r.issues) {
    const k = `${r.state} | ${i.type} | ${i.el}`
    const e = byKey.get(k) ?? { n: 0, where: new Set(), detail: i.detail }
    e.n++
    e.where.add(`${r.device}/${r.scheme}`)
    byKey.set(k, e)
  }
const md = ['# Mobile audit', '', `Base: ${BASE}`, `Errors: ${errors}`, '', '| State / type / element | Seen on | Detail |', '|---|---|---|']
for (const [k, e] of [...byKey].sort()) md.push(`| ${k.replace(/\|/g, '/')} | ${[...e.where].join(', ')} | ${e.detail} |`)
fs.writeFileSync(path.join(OUT, 'report.md'), md.join('\n') + '\n')
console.log(`\n${errors} error(s). Report: ${path.join(OUT, 'report.md')}`)
process.exit(errors ? 1 : 0)
