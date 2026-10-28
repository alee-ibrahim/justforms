/**
 * Pure edits on a draft form: the element tree (pages, sections, repeaters), pages, keys and
 * logic references. Every function returns a new form and never mutates its input.
 */
import { buildIndex, iterLeaves } from '@/logic/form-index'
import { CUSTOM_ID, ID_PRESETS } from '@/renderer/id-presets'
import type {
  Condition,
  Element,
  FieldElement,
  FieldType,
  Form,
  NavigationRule,
  Option,
  Page,
} from '@/schema'

/** A list of elements: the top of a page, or the body of a section or repeater. */
export interface Container {
  pageIndex: number
  parentId: string | null
}
export interface Location extends Container {
  index: number
}

export const MAX_SECTION_DEPTH = 2

type Pages = Form['pages']

function withPages(form: Form, pages: Page[]): Form {
  return { ...form, pages: pages as Pages }
}

function mapList(
  els: Element[],
  parentId: string | null,
  fn: (list: Element[], parentId: string | null) => Element[],
): Element[] {
  const mapped = els.map((el) =>
    el.kind === 'section' || el.kind === 'repeater'
      ? { ...el, elements: mapList(el.elements ?? [], el.id, fn) }
      : el,
  )
  return fn(mapped, parentId)
}

/** Apply `fn` to every element list of one page (or all pages), bottom-up. */
function mapLists(
  form: Form,
  fn: (list: Element[], c: Container) => Element[],
  onlyPage?: number,
): Form {
  return withPages(
    form,
    form.pages.map((page, pageIndex) =>
      onlyPage !== undefined && pageIndex !== onlyPage
        ? page
        : {
            ...page,
            elements: mapList(page.elements ?? [], null, (list, parentId) =>
              fn(list, { pageIndex, parentId }),
            ),
          },
    ),
  )
}

export function childrenOf(form: Form, c: Container): Element[] {
  const page = form.pages[c.pageIndex]
  if (!page) return []
  if (c.parentId === null) return page.elements ?? []
  const found = findElement(form, c.parentId)
  return found && (found.el.kind === 'section' || found.el.kind === 'repeater')
    ? (found.el.elements ?? [])
    : []
}

export function findElement(form: Form, id: string): { el: Element; loc: Location } | null {
  let out: { el: Element; loc: Location } | null = null
  const walk = (els: Element[], pageIndex: number, parentId: string | null) => {
    els.forEach((el, index) => {
      if (out) return
      if (el.id === id) out = { el, loc: { pageIndex, parentId, index } }
      else if (el.kind === 'section' || el.kind === 'repeater')
        walk(el.elements ?? [], pageIndex, el.id)
    })
  }
  form.pages.forEach((p, i) => walk(p.elements ?? [], i, null))
  return out
}

/** All elements in document order (depth first), with their container. */
export function allElements(form: Form): { el: Element; loc: Location }[] {
  const out: { el: Element; loc: Location }[] = []
  const walk = (els: Element[], pageIndex: number, parentId: string | null) =>
    els.forEach((el, index) => {
      out.push({ el, loc: { pageIndex, parentId, index } })
      if (el.kind === 'section' || el.kind === 'repeater') walk(el.elements ?? [], pageIndex, el.id)
    })
  form.pages.forEach((p, i) => walk(p.elements ?? [], i, null))
  return out
}

export function insertElement(form: Form, el: Element, loc: Location): Form {
  return mapLists(
    form,
    (list, c) => {
      if (c.parentId !== loc.parentId) return list
      const next = [...list]
      next.splice(Math.min(Math.max(loc.index, 0), next.length), 0, el)
      return next
    },
    loc.pageIndex,
  )
}

export function removeElement(form: Form, id: string): Form {
  return mapLists(form, (list) => list.filter((el) => el.id !== id))
}

export function updateElement(form: Form, id: string, change: (el: Element) => Element): Form {
  return mapLists(form, (list) => list.map((el) => (el.id === id ? change(el) : el)))
}

/** Ids of an element and everything inside it. */
export function subtreeIds(el: Element): string[] {
  const ids = [el.id]
  if (el.kind === 'section' || el.kind === 'repeater')
    for (const child of el.elements ?? []) ids.push(...subtreeIds(child))
  return ids
}

function sectionDepthOf(el: Element): number {
  if (el.kind === 'section')
    return 1 + Math.max(0, ...(el.elements ?? []).map(sectionDepthOf))
  if (el.kind === 'repeater') return Math.max(0, ...(el.elements ?? []).map(sectionDepthOf))
  return 0
}

function containsKind(el: Element, test: (e: Element) => boolean): boolean {
  if (test(el)) return true
  return (el.kind === 'section' || el.kind === 'repeater') && (el.elements ?? []).some((c) => containsKind(c, test))
}

/** Why `el` can't go into container `c`, or null when it can. */
export function placementProblem(form: Form, el: Element, c: Container): string | null {
  if (c.parentId === null) return null
  if (subtreeIds(el).includes(c.parentId)) return "A block can't go inside itself"
  const index = buildIndex(form)
  const parent = index.elements.get(c.parentId)
  if (!parent) return null
  const inRepeater = parent.kind === 'repeater' || parent.repeaterId !== null
  if (inRepeater && containsKind(el, (e) => e.kind === 'repeater'))
    return "Repeaters can't contain repeaters"
  if (inRepeater && containsKind(el, (e) => e.kind === 'field' && e.type === 'signature'))
    return "Signatures can't go inside a repeater"
  const parentDepth = parent.sectionDepth + (parent.kind === 'section' ? 1 : 0)
  if (parentDepth + sectionDepthOf(el) > MAX_SECTION_DEPTH)
    return 'Sections can nest two levels deep'
  return null
}

/** Move `id` to `to` (index counted in the target list before the move). */
export function moveElement(form: Form, id: string, to: Location): Form {
  const found = findElement(form, id)
  if (!found) return form
  const { loc } = found
  let index = to.index
  if (loc.pageIndex === to.pageIndex && loc.parentId === to.parentId && loc.index < to.index) index--
  if (
    loc.pageIndex === to.pageIndex &&
    loc.parentId === to.parentId &&
    loc.index === index
  )
    return form
  return insertElement(removeElement(form, id), found.el, { ...to, index })
}

/** Move up/down among siblings. */
export function nudgeElement(form: Form, id: string, delta: -1 | 1): Form {
  const found = findElement(form, id)
  if (!found) return form
  const { loc } = found
  const len = childrenOf(form, loc).length
  const target = loc.index + delta
  if (target < 0 || target >= len) return form
  return moveElement(form, id, { ...loc, index: delta === 1 ? target + 1 : target })
}

// -- ids and keys ---------------------------------------------------------------------------

export function takenIds(form: Form): Set<string> {
  return new Set<string>([
    ...allElements(form).map((e) => e.el.id),
    ...form.pages.map((p) => p.id),
    'submit',
  ])
}

const TYPE_BASES = new Set([
  'short_text', 'long_text', 'email', 'phone', 'number', 'date', 'time', 'single_choice',
  'multi_choice', 'yes_no', 'rating', 'file', 'signature', 'hidden', 'section', 'repeater',
  'heading', 'paragraph', 'divider', 'image', 'page', 'id_number',
])

/** A free key from `base`: the base itself when it reads like a word, else `base_n`. */
export function uniqueId(form: Form, base: string, extra: Set<string> = new Set()): string {
  const taken = takenIds(form)
  const clean =
    base.toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/^[^a-z]+/, '').slice(0, 56) || 'q'
  const free = (id: string) => !taken.has(id) && !extra.has(id)
  if (!TYPE_BASES.has(clean) && free(clean)) return clean
  let n = 1
  while (!free(`${clean}_${n}`)) n++
  return `${clean}_${n}`
}

/** "Full name" -> "full_name"; null when the label has no Latin words (e.g. Thaana). */
export function keyFromLabel(label: string): string | null {
  const ascii = label
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  const key = ascii.replace(/^[^a-z]+/, '').split('_').slice(0, 5).join('_').slice(0, 40)
  return key && /^[a-z][a-z0-9_]*$/.test(key) ? key : null
}

/** True when the key is still the automatic one (type + number), so a label may rename it. */
export function isAutoKey(el: Element): boolean {
  const base =
    el.kind === 'field'
      ? el.type === 'short_text' && el.idPreset
        ? 'id_number'
        : el.type
      : el.kind === 'content'
        ? el.contentType
        : el.kind
  return new RegExp(`^${base}_\\d+$`).test(el.id)
}

// -- new elements ---------------------------------------------------------------------------

export type BlockType =
  | FieldType
  /** A short_text with an ID-number preset (renderer/id-presets.ts). */
  | 'id_number'
  | 'section'
  | 'repeater'
  | 'heading'
  | 'paragraph'
  | 'divider'

export function newElement(form: Form, type: BlockType, extra?: Set<string>): Element {
  const id = uniqueId(form, type, extra)
  switch (type) {
    case 'section':
      return { kind: 'section', id, title: '', elements: [] }
    case 'repeater':
      return { kind: 'repeater', id, label: '', elements: [] }
    case 'heading':
    case 'paragraph':
      return { kind: 'content', id, contentType: type, text: '' }
    case 'divider':
      return { kind: 'content', id, contentType: 'divider' }
    case 'single_choice':
    case 'multi_choice': {
      const options: [Option, ...Option[]] = [
        { value: 'option_1', label: 'Option 1' },
        { value: 'option_2', label: 'Option 2' },
      ]
      return { kind: 'field', id, type, label: '', options } as FieldElement
    }
    case 'file':
      return { kind: 'field', id, type, label: '', maxFiles: 1, maxSizeMb: 10 } as FieldElement
    case 'rating':
      return { kind: 'field', id, type, label: '', max: 5 } as FieldElement
    case 'id_number': {
      const preset = ID_PRESETS[0]
      return {
        kind: 'field',
        id,
        type: 'short_text',
        label: '',
        idPreset: preset?.id ?? CUSTOM_ID,
        ...(preset?.sensitive ? { sensitive: true } : {}),
      } as FieldElement
    }
    default:
      return { kind: 'field', id, type, label: '' } as FieldElement
  }
}

/** Deep copy with fresh ids (references inside the copy follow the new ids). */
export function cloneWithNewIds(form: Form, el: Element, extra = new Set<string>()): Element {
  const map = new Map<string, string>()
  const assign = (e: Element) => {
    const id = uniqueId(form, e.id.replace(/_\d+$/, ''), extra)
    extra.add(id)
    map.set(e.id, id)
    if (e.kind === 'section' || e.kind === 'repeater') (e.elements ?? []).forEach(assign)
  }
  assign(el)
  const copy = JSON.parse(JSON.stringify(el)) as Element
  return renameInElement(copy, map)
}

export function duplicateElement(form: Form, id: string): { form: Form; id: string } {
  const found = findElement(form, id)
  if (!found) return { form, id }
  const copy = cloneWithNewIds(form, found.el)
  return { form: insertElement(form, copy, { ...found.loc, index: found.loc.index + 1 }), id: copy.id }
}

export function wrapInSection(form: Form, id: string): { form: Form; id: string } {
  const found = findElement(form, id)
  if (!found) return { form, id }
  const section: Element = {
    kind: 'section',
    id: uniqueId(form, 'section'),
    title: '',
    elements: [found.el],
  }
  if (placementProblem(form, section, found.loc)) return { form, id }
  const removed = removeElement(form, id)
  return { form: insertElement(removed, section, found.loc), id: section.id }
}

// -- logic references -----------------------------------------------------------------------

function renameCondition(c: Condition, map: Map<string, string>): Condition {
  if ('field' in c) return map.has(c.field) ? { ...c, field: map.get(c.field)! } : c
  if ('all' in c) return { all: c.all.map((x) => renameCondition(x, map)) }
  if ('any' in c) return { any: c.any.map((x) => renameCondition(x, map)) }
  return { not: renameCondition(c.not, map) }
}

function renameInElement(el: Element, map: Map<string, string>): Element {
  const out: Element = { ...el, id: map.get(el.id) ?? el.id } as Element
  if (out.visibleIf) out.visibleIf = renameCondition(out.visibleIf, map)
  if (out.kind === 'field' && out.requiredIf) out.requiredIf = renameCondition(out.requiredIf, map)
  if (out.kind === 'section' || out.kind === 'repeater')
    out.elements = (out.elements ?? []).map((c) => renameInElement(c, map))
  return out
}

/** Change a key everywhere: the element itself and every condition that reads it. */
export function renameId(form: Form, from: string, to: string): Form {
  const map = new Map([[from, to]])
  const pages = form.pages.map((p) => ({
    ...p,
    visibleIf: p.visibleIf ? renameCondition(p.visibleIf, map) : p.visibleIf,
    next: p.next?.map((r) => ({ ...r, if: renameCondition(r.if, map) })),
    elements: (p.elements ?? []).map((el) => renameInElement(el, map)),
  }))
  return withPages(form, pages)
}

export interface RuleRef {
  /** Element or page that owns the rule. */
  ownerId: string
  kind: 'visibleIf' | 'requiredIf' | 'next'
}

function reads(c: Condition | null | undefined, ids: Set<string>): boolean {
  for (const leaf of iterLeaves(c)) if (ids.has(leaf.field)) return true
  return false
}

/** Rules (outside `ids` themselves) that read any of `ids`. */
export function rulesReading(form: Form, ids: Set<string>): RuleRef[] {
  const out: RuleRef[] = []
  for (const { el } of allElements(form)) {
    if (ids.has(el.id)) continue
    if (reads(el.visibleIf, ids)) out.push({ ownerId: el.id, kind: 'visibleIf' })
    if (el.kind === 'field' && reads(el.requiredIf, ids)) out.push({ ownerId: el.id, kind: 'requiredIf' })
  }
  for (const page of form.pages) {
    if (ids.has(page.id)) continue
    if (reads(page.visibleIf, ids)) out.push({ ownerId: page.id, kind: 'visibleIf' })
    if ((page.next ?? []).some((r) => reads(r.if, ids))) out.push({ ownerId: page.id, kind: 'next' })
  }
  return out
}

/** Drop every rule that reads any of `ids` (used when deleting questions). */
export function dropRulesReading(form: Form, ids: Set<string>): Form {
  const clean = <T extends { visibleIf?: Condition | null }>(x: T): T => {
    const out = { ...x }
    if (reads(out.visibleIf, ids)) delete out.visibleIf
    return out
  }
  const cleanEl = (el: Element): Element => {
    const out = clean(el) as Element
    if (out.kind === 'field' && reads(out.requiredIf, ids)) delete out.requiredIf
    if (out.kind === 'section' || out.kind === 'repeater')
      out.elements = (out.elements ?? []).map(cleanEl)
    return out
  }
  return withPages(
    form,
    form.pages.map((p) => ({
      ...clean(p),
      next: (p.next ?? []).filter((r: NavigationRule) => !reads(r.if, ids)),
      elements: (p.elements ?? []).map(cleanEl),
    })),
  )
}

// -- pages ----------------------------------------------------------------------------------

export function addPage(form: Form, at = form.pages.length): { form: Form; id: string } {
  const id = uniqueId(form, 'page')
  const page: Page = { id, title: `Page ${form.pages.length + 1}`, elements: [] }
  const pages = [...form.pages]
  pages.splice(at, 0, page)
  return { form: withPages(form, pages), id }
}

export function updatePage(form: Form, index: number, change: (p: Page) => Page): Form {
  return withPages(form, form.pages.map((p, i) => (i === index ? change(p) : p)))
}

export function removePage(form: Form, index: number): Form {
  if (form.pages.length <= 1) return form
  const page = form.pages[index]
  const ids = new Set<string>([page.id, ...(page.elements ?? []).flatMap(subtreeIds)])
  const pages = form.pages.filter((_, i) => i !== index)
  // Jumps to the removed page fall back to "next page".
  const cleaned = pages.map((p) => ({ ...p, next: (p.next ?? []).filter((r) => r.goto !== page.id) }))
  return dropRulesReading(withPages(form, cleaned), ids)
}

export function movePage(form: Form, from: number, to: number): Form {
  if (to < 0 || to >= form.pages.length || from === to) return form
  const pages = [...form.pages]
  const [p] = pages.splice(from, 1)
  pages.splice(to, 0, p)
  // Jumps may only go forward: drop any that now point backwards.
  const order = new Map(pages.map((pg, i) => [pg.id, i]))
  return withPages(
    form,
    pages.map((pg, i) => ({
      ...pg,
      next: (pg.next ?? []).filter((r) => r.goto === 'submit' || (order.get(r.goto) ?? -1) > i),
    })),
  )
}

export function duplicatePage(form: Form, index: number): { form: Form; id: string } {
  const page = form.pages[index]
  const id = uniqueId(form, page.id.replace(/_\d+$/, ''))
  const extra = new Set<string>([id])
  const elements = (page.elements ?? []).map((el) => cloneWithNewIds(form, el, extra))
  const copy: Page = {
    ...page,
    id,
    title: page.title ? `${page.title} (copy)` : page.title,
    elements,
    next: [],
  }
  const pages = [...form.pages]
  pages.splice(index + 1, 0, copy)
  return { form: withPages(form, pages), id }
}

/** Counts for the publish summary. */
export function formCounts(form: Form): { pages: number; questions: number; rules: number } {
  let questions = 0
  let rules = 0
  for (const { el } of allElements(form)) {
    if (el.kind === 'field' && el.type !== 'hidden') questions++
    if (el.visibleIf) rules++
    if (el.kind === 'field' && el.requiredIf) rules++
  }
  for (const p of form.pages) rules += (p.visibleIf ? 1 : 0) + (p.next?.length ?? 0)
  return { pages: form.pages.length, questions, rules }
}

/** Options from one label per line; keeps existing option values by position. */
export function optionsFromText(existing: Option[], text: string): [Option, ...Option[]] {
  const lines = text.split('\n').filter((l, _i, all) => l.trim() || all.length === 1)
  const used = new Set<string>()
  return lines.map((line, i): Option => {
    let value = existing[i]?.value ?? `option_${i + 1}`
    let n = i + 1
    while (used.has(value)) value = `option_${++n}`
    used.add(value)
    return { value, label: line.trim() }
  }) as [Option, ...Option[]]
}
