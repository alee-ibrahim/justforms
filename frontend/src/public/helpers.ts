/** Page-level helpers shared by the public form app and its access chunk. */
import { buildIndex } from '@/logic/form-index'
import type { Form } from '@/schema'

const parts = window.location.pathname.split('/').filter(Boolean)
/** The form's address (`/{slug}`); empty for any other path, which shows "not found". */
export const formSlug = parts.length === 1 && /^[a-z0-9][a-z0-9-]{0,99}$/.test(parts[0]) ? parts[0] : ''
const params = new URLSearchParams(window.location.search)
export const embed = params.get('embed') === '1'

/** Answers prefilled from link parameters (`prefillParam`). */
export function prefill(form: Form): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const info of buildIndex(form).elements.values()) {
    const el = info.element
    if (el.kind === 'field' && el.prefillParam && info.repeaterId === null) {
      const v = params.get(el.prefillParam)
      if (v !== null && v !== '') out[el.id] = v
    }
  }
  return out
}

/** Questions that are new or changed between two versions (marker wash after a 409). */
export function changedQuestions(before: Form, after: Form): Set<string> {
  const old = buildIndex(before).elements
  const out = new Set<string>()
  for (const [id, info] of buildIndex(after).elements) {
    const prev = old.get(id)
    if (!prev || JSON.stringify(prev.element) !== JSON.stringify(info.element)) out.add(id)
  }
  return out
}

export function postHeight() {
  if (window.parent === window) return
  window.parent.postMessage({ type: 'justforms:resize', height: document.documentElement.scrollHeight }, '*')
}
