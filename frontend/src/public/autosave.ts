/**
 * Saved progress on the respondent's device (docs/ux/SAVED-PROGRESS-SCREENS.md): answers and the
 * current page go to localStorage while the respondent types and come back when the form is
 * opened again. A lazy chunk, fetched in parallel with the form, so the public bundle stays small.
 *
 * Never stored: sensitive questions, signatures, files (their upload session ends with the page
 * load) and hidden questions (they come from the link). Every storage call may throw (private
 * mode, partitioned or sandboxed frames, a full quota): progress is then simply not kept.
 */
import { buildIndex } from '@/logic/form-index'
import type { Element, Form } from '@/schema'

import type { LiveForm } from './api'

export { ProgressNotice } from './progress-notice'

type Answers = Record<string, unknown>
/** Kinds of answers that are never stored but were filled in. */
export type Skipped = 'files' | 'signatures' | 'private'

interface Record1 {
  v: 1
  version: number
  savedAt: number
  expires: number
  page: string
  answers: Answers
  /** Question type (or "repeater") of every stored answer, to drop answers whose question changed. */
  types: Record<string, string>
  skipped: Skipped[]
}

export interface Restored {
  answers: Answers
  /** The saved page, when the form has not changed since. */
  page?: string
  savedAt: number
  /** Saved for another published version. */
  changed: boolean
  /** Some saved answers no longer fit the form. */
  dropped: boolean
  skipped: Skipped[]
}

const PREFIX = 'justforms:progress:'
const DAY = 86_400_000
export const SAVE_DELAY = 500

function store(): Storage | null {
  try {
    return window.localStorage ?? null
  } catch {
    return null
  }
}

/** FNV-1a: keeps the respondent's email out of the storage key. Separation, not secrecy. */
function hash(s: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193)
  return (h >>> 0).toString(36)
}

export function progressKey(live: Pick<LiveForm, 'formId' | 'accessMode' | 'respondentEmail'>): string {
  const who = live.accessMode !== 'public' && live.respondentEmail ? `:${hash(live.respondentEmail.toLowerCase())}` : ''
  return `${PREFIX}${live.formId}${who}`
}

const filled = (v: unknown) =>
  v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && v.length === 0)

/** Why a question's answer is never stored, or null when it may be. */
function never(el: Element): Skipped | 'hidden' | null {
  if (el.kind !== 'field') return null
  if (el.type === 'file') return 'files'
  if (el.type === 'signature') return 'signatures'
  if (el.type === 'hidden') return 'hidden'
  return el.sensitive ? 'private' : null
}

const typeOf = (el: Element) => (el.kind === 'field' ? el.type : el.kind)

/** The answers that may be stored, their question types, and the kinds that were left out. */
export function keepable(form: Form, answers: Answers) {
  const index = buildIndex(form).elements
  const types: Record<string, string> = {}
  const skipped = new Set<Skipped>()
  const pick = (key: string, value: unknown): boolean => {
    const el = index.get(key)?.element
    if (!el || el.kind === 'content' || el.kind === 'section') return false
    const why = never(el)
    if (why) {
      if (why !== 'hidden' && filled(value)) skipped.add(why)
      return false
    }
    types[key] = typeOf(el)
    return true
  }
  const out: Answers = {}
  for (const [key, value] of Object.entries(answers)) {
    if (!pick(key, value)) continue
    if (index.get(key)?.element.kind === 'repeater') {
      if (!Array.isArray(value)) continue
      out[key] = value.map((row) =>
        Object.fromEntries(Object.entries((row ?? {}) as Answers).filter(([k, v]) => pick(k, v))),
      )
    } else out[key] = value
  }
  return { answers: out, types, skipped: [...skipped].sort() }
}

/** Saved answers that still fit `form`: same question, same type, still storable. */
export function fitting(form: Form, saved: Pick<Record1, 'answers' | 'types'>) {
  const index = buildIndex(form).elements
  let dropped = false
  const fits = (key: string) => {
    const el = index.get(key)?.element
    const ok = !!el && !never(el) && saved.types[key] === typeOf(el)
    if (!ok) dropped = true
    return ok
  }
  const out: Answers = {}
  for (const [key, value] of Object.entries(saved.answers)) {
    if (!fits(key)) continue
    out[key] = Array.isArray(value)
      ? value.map((row) => Object.fromEntries(Object.entries((row ?? {}) as Answers).filter(([k]) => fits(k))))
      : value
  }
  return { answers: out, dropped }
}

/** Removes expired records of every form, and every record of `formId` when given. */
function sweep(s: Storage, now: number, formId?: string) {
  for (let i = s.length - 1; i >= 0; i--) {
    const key = s.key(i)
    if (!key?.startsWith(PREFIX)) continue
    if (formId && (key === PREFIX + formId || key.startsWith(`${PREFIX}${formId}:`))) {
      s.removeItem(key)
      continue
    }
    try {
      const rec = JSON.parse(s.getItem(key) ?? '') as Partial<Record1>
      if (rec.v !== 1 || typeof rec.expires !== 'number' || rec.expires <= now) s.removeItem(key)
    } catch {
      s.removeItem(key)
    }
  }
}

export interface Progress {
  restored: Restored | null
  /** Debounced; straight away when the page changed. */
  save(answers: Answers, page: string): void
  flush(): void
  clear(): void
  /** The form was republished while open (409 on submit). */
  update(live: LiveForm): void
}

let open: { dispose(): void } | null = null

/** Saved progress for this form and respondent; null when off or storage is unavailable. */
export function openProgress(live: LiveForm, now = Date.now()): Progress | null {
  open?.dispose()
  open = null
  const form = live.schema
  const s = store()
  if (!form || !s) return null
  const days = live.saveProgress?.days
  try {
    sweep(s, now, days ? undefined : live.formId)
  } catch {
    return null
  }
  if (!days) return null
  const key = progressKey(live)
  let current = live
  let restored: Restored | null = null
  try {
    const raw = s.getItem(key)
    if (raw) {
      const rec = JSON.parse(raw) as Record1
      const { answers, dropped } = fitting(form, rec)
      const changed = rec.version !== live.version
      if (Object.keys(answers).length) {
        restored = {
          answers,
          page: changed ? undefined : rec.page,
          savedAt: rec.savedAt,
          changed,
          dropped,
          skipped: rec.skipped ?? [],
        }
      } else s.removeItem(key)
    }
  } catch {
    try {
      s.removeItem(key)
    } catch {
      /* storage gone */
    }
  }

  let pending: [Answers, string] | null = null
  let lastPage: string | null = restored?.page ?? null
  let timer: number | undefined

  const flush = () => {
    window.clearTimeout(timer)
    if (!pending) return
    const [all, page] = pending
    pending = null
    try {
      const kept = keepable(current.schema ?? form, all)
      if (!Object.keys(kept.answers).length) return s.removeItem(key)
      const at = Date.now()
      const rec: Record1 = { v: 1, version: current.version, savedAt: at, expires: at + days * DAY, page, ...kept }
      s.setItem(key, JSON.stringify(rec))
    } catch {
      /* full or unavailable: progress is not kept */
    }
  }
  const onHide = () => {
    if (document.visibilityState === 'hidden') flush()
  }
  document.addEventListener('visibilitychange', onHide)
  window.addEventListener('pagehide', flush)
  open = {
    dispose() {
      flush()
      document.removeEventListener('visibilitychange', onHide)
      window.removeEventListener('pagehide', flush)
    },
  }

  return {
    restored,
    save(answers, page) {
      pending = [answers, page]
      window.clearTimeout(timer)
      if (page !== lastPage) {
        lastPage = page
        flush()
      } else timer = window.setTimeout(flush, SAVE_DELAY)
    },
    flush,
    clear() {
      pending = null
      window.clearTimeout(timer)
      try {
        s.removeItem(key)
      } catch {
        /* storage gone */
      }
    },
    update(next) {
      current = next
    },
  }
}

const rtf = typeof Intl !== 'undefined' && Intl.RelativeTimeFormat ? new Intl.RelativeTimeFormat('en', { numeric: 'auto' }) : null
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['day', DAY],
  ['hour', 3_600_000],
  ['minute', 60_000],
]

/** "a moment ago", "5 minutes ago", "yesterday". */
export function ago(then: number, now = Date.now()): string {
  const diff = now - then
  for (const [unit, ms] of UNITS)
    if (diff >= ms) return rtf ? rtf.format(-Math.floor(diff / ms), unit) : `${Math.floor(diff / ms)} ${unit}s ago`
  return 'a moment ago'
}

const SKIP_WORDS: Record<Skipped, string> = { files: 'files', signatures: 'signatures', private: 'private answers' }

/** "Files and signatures aren't saved on this device, so add them again." */
export function skippedText(skipped: Skipped[]): string | null {
  if (!skipped.length) return null
  const words = skipped.map((k) => SKIP_WORDS[k])
  const list = words.length === 1 ? words[0] : `${words.slice(0, -1).join(', ')} and ${words.at(-1)}`
  const again =
    skipped.length > 1 ? 'add them again' : skipped[0] === 'files' ? 'attach them again' : skipped[0] === 'signatures' ? 'sign again' : 'fill them in again'
  return `${list[0].toUpperCase()}${list.slice(1)} aren't saved on this device, so ${again}.`
}

export function restoredText(r: Restored, now = Date.now()): string[] {
  const out = [`We restored your progress from ${ago(r.savedAt, now)}.`]
  if (r.changed)
    out.push(r.dropped ? 'The form has changed since, and some answers no longer apply.' : 'The form has changed since, so check your answers.')
  const skip = skippedText(r.skipped)
  if (skip) out.push(skip)
  return out
}
