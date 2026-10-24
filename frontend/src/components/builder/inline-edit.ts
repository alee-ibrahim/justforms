/**
 * Pure helpers behind inline editing on the canvas (docs/ux/INLINE-EDIT-AND-LOGO-SCREENS.md §1):
 * keys naming each editable text, and the changes a commit makes. Each helper returns a new form
 * (or the same one when nothing changes), so one commit is one `store.edit`, one undo step.
 */
import type { Element, Form, Option } from '@/schema'

import { isAutoKey, keyFromLabel, renameId, uniqueId, updateElement, updatePage } from './tree'

export type ElementText = 'label' | 'title' | 'description' | 'placeholder' | 'addLabel' | 'text'
export type SettingsText = 'title' | 'description' | 'submitLabel' | 'nextLabel' | 'backLabel' | 'successMessage'

export const textKey = {
  element: (id: string, part: ElementText) => `el:${id}:${part}`,
  option: (id: string, value: string) => `opt:${id}:${value}`,
  /** A new option being typed after position `index` (-1: at the start). */
  newOption: (id: string, index: number) => `opt-new:${id}:${index}`,
  page: (pageId: string, part: 'title' | 'description') => `page:${pageId}:${part}`,
  settings: (part: SettingsText) => `form:${part}`,
}

/** Texts that are dropped from the draft when left empty (required ones stay, even empty). */
const OPTIONAL = new Set(['description', 'placeholder', 'addLabel', 'title', 'submitLabel', 'nextLabel', 'backLabel', 'successMessage'])

function withText<T extends object>(obj: T, key: string, text: string, required: boolean): T {
  const out = { ...obj } as Record<string, unknown>
  if (!required && OPTIONAL.has(key) && text.trim() === '') delete out[key]
  else out[key] = text
  return out as T
}

/** Set one text of an element. A Latin label also names the key while it is the automatic one;
 * returns the (possibly renamed) id. */
export function setElementText(form: Form, id: string, part: ElementText, text: string): { form: Form; id: string } {
  let next = updateElement(form, id, (el) => {
    const required = (part === 'label' && (el.kind === 'field' || el.kind === 'repeater')) || (part === 'text' && el.kind === 'content')
    return withText(el, part, text, required) as Element
  })
  let newId = id
  if (next !== form && (part === 'label' || part === 'title')) {
    const el = findById(next, id)
    const key = keyFromLabel(text)
    if (el && key && isAutoKey(el) && el.kind !== 'content') {
      newId = uniqueId(next, key)
      next = renameId(next, id, newId)
    }
  }
  return { form: next, id: newId }
}

function findById(form: Form, id: string): Element | undefined {
  let found: Element | undefined
  const walk = (els: Element[] | undefined) => {
    for (const el of els ?? []) {
      if (el.id === id) found = el
      if (el.kind === 'section' || el.kind === 'repeater') walk(el.elements)
    }
  }
  for (const p of form.pages) walk(p.elements)
  return found
}

export function setPageText(form: Form, pageId: string, part: 'title' | 'description', text: string): Form {
  const index = form.pages.findIndex((p) => p.id === pageId)
  return index < 0 ? form : updatePage(form, index, (p) => withText(p, part, text, false))
}

export function setSettingsText(form: Form, part: SettingsText, text: string): Form {
  return { ...form, settings: withText(form.settings, part, text, part === 'title') }
}

// -- options ---------------------------------------------------------------------------------

type Choice = Extract<Element, { options: Option[] }>

/** Change one question's options; the same form back when nothing changes (no undo step). */
function withOptions(form: Form, id: string, change: (options: Option[], el: Choice) => Option[] | null): Form {
  let changed = false
  const next = updateElement(form, id, (el) => {
    if (!('options' in el) || !Array.isArray(el.options)) return el
    const options = change(el.options, el as Choice)
    if (!options || options.length === 0) return el
    changed = true
    return { ...el, options: options as [Option, ...Option[]] } as Element
  })
  return changed ? next : form
}

/** A value no option uses yet: `option_{n}`. */
export function nextOptionValue(options: Option[]): string {
  const used = new Set(options.map((o) => o.value))
  let n = options.length + 1
  while (used.has(`option_${n}`)) n++
  return `option_${n}`
}

export function renameOption(form: Form, id: string, value: string, label: string): Form {
  return withOptions(form, id, (options) =>
    options.some((o) => o.value === value && o.label !== label) ? options.map((o) => (o.value === value ? { ...o, label } : o)) : null,
  )
}

/** Insert an option after position `after` (-1: first). Returns the new option's value. */
export function insertOption(form: Form, id: string, after: number, label: string): { form: Form; value: string } {
  let value = ''
  const next = withOptions(form, id, (options) => {
    value = nextOptionValue(options)
    const out = [...options]
    out.splice(Math.max(0, Math.min(after + 1, out.length)), 0, { value, label })
    return out
  })
  return { form: next, value }
}

/** Remove an option; a question keeps at least one. */
export function removeOption(form: Form, id: string, value: string): Form {
  return withOptions(form, id, (options) => (options.length > 1 ? options.filter((o) => o.value !== value) : null))
}

export function moveOption(form: Form, id: string, value: string, delta: number): Form {
  return withOptions(form, id, (options) => {
    const from = options.findIndex((o) => o.value === value)
    const to = from + delta
    if (from < 0 || to < 0 || to >= options.length) return null
    const out = [...options]
    const [moved] = out.splice(from, 1)
    out.splice(to, 0, moved)
    return out
  })
}

export function setAllowOther(form: Form, id: string, on: boolean): Form {
  let changed = false
  const next = updateElement(form, id, (el) => {
    if (el.kind !== 'field' || (el.type !== 'single_choice' && el.type !== 'multi_choice')) return el
    if (!!el.allowOther === on) return el
    changed = true
    const out = { ...el } as Record<string, unknown>
    if (on) out.allowOther = true
    else delete out.allowOther
    return out as unknown as Element
  })
  return changed ? next : form
}

/** Put focus back on an idle editable text (after Enter or Esc). */
export function focusInlineText(key: string) {
  window.requestAnimationFrame(() =>
    document.querySelector<HTMLElement>(`[data-inline-text="${CSS.escape(key)}"]`)?.focus({ preventScroll: true }),
  )
}

/** Question types whose answer box shows a placeholder, edited in place on the canvas. */
export const PLACEHOLDER_TYPES: ReadonlySet<string> = new Set(['short_text', 'long_text', 'email', 'phone', 'number'])
