/** Builder commands shared by the palette, canvas, menus and keyboard shortcuts. */
import { toast } from 'sonner'

import type { Element, Form } from '@/schema'

import { blockInfo, blockLabel } from './block-types'
import { textKey } from './inline-edit'
import type { BuilderStore } from './store'
import {
  childrenOf,
  dropRulesReading,
  duplicateElement,
  findElement,
  insertElement,
  type Location,
  moveElement,
  newElement,
  nudgeElement,
  placementProblem,
  removeElement,
  rulesReading,
  subtreeIds,
  type BlockType,
  wrapInSection,
} from './tree'

export function currentPageIndex(store: BuilderStore): number {
  const { schema, pageId } = store.get()
  return Math.max(0, schema.pages.findIndex((p) => p.id === pageId))
}

/** Where a new block goes: after the selected block, or at the end of the current page. */
export function insertionPoint(store: BuilderStore, el: Element): Location {
  const { schema, selection } = store.get()
  const pageIndex = currentPageIndex(store)
  if (selection.type === 'element') {
    const found = findElement(schema, selection.id)
    if (found && found.loc.pageIndex === pageIndex) {
      // Selected container: add inside it, at the end.
      if (
        (found.el.kind === 'section' || found.el.kind === 'repeater') &&
        !placementProblem(schema, el, { pageIndex, parentId: found.el.id })
      )
        return { pageIndex, parentId: found.el.id, index: childrenOf(schema, { pageIndex, parentId: found.el.id }).length }
      if (!placementProblem(schema, el, found.loc)) return { ...found.loc, index: found.loc.index + 1 }
    }
  }
  return { pageIndex, parentId: null, index: (schema.pages[pageIndex].elements ?? []).length }
}

export function addBlock(store: BuilderStore, type: BlockType, at?: Location): string {
  const el = newElement(store.get().schema, type)
  const loc = at ?? insertionPoint(store, el)
  store.edit((f) => insertElement(f, el, loc), {
    selection: { type: 'element', id: el.id },
    pageId: store.get().schema.pages[loc.pageIndex].id,
    editing:
      el.kind === 'field' || el.kind === 'repeater'
        ? textKey.element(el.id, 'label')
        : el.kind === 'section'
          ? textKey.element(el.id, 'title')
          : null,
  })
  const editsLabel = el.kind === 'field' || el.kind === 'repeater' || el.kind === 'section'
  window.setTimeout(() => {
    document.querySelector(`[data-block="${el.id}"]`)?.scrollIntoView({ block: 'nearest' })
    if (!editsLabel) focusBlock(el.id)
  }, 0)
  return el.id
}

export function quoted(el: Element): string {
  const label = blockLabel(el)
  return label ? `“${label}”` : blockInfo(el).label.toLowerCase()
}

/** Delete with an Undo toast. Returns the rules that read it, if the caller must confirm. */
export function deleteElement(store: BuilderStore, id: string, confirmed = false): boolean {
  const { schema } = store.get()
  const found = findElement(schema, id)
  if (!found) return true
  const ids = new Set(subtreeIds(found.el))
  const rules = rulesReading(schema, ids)
  if (rules.length && !confirmed) return false
  // Focus moves to the next block, the previous one, or nothing.
  const siblings = childrenOf(schema, found.loc)
  const neighbour = siblings[found.loc.index + 1] ?? siblings[found.loc.index - 1]
  store.edit((f) => removeElement(dropRulesReading(f, ids), id), {
    selection: neighbour ? { type: 'element', id: neighbour.id } : { type: 'page', pageId: store.get().pageId },
  })
  toast(`Deleted ${quoted(found.el)}`, {
    duration: 5000,
    action: {
      label: 'Undo',
      onClick: () => {
        void store.undo().then(() => {
          store.select({ type: 'element', id })
          document.querySelector(`[data-block="${id}"]`)?.scrollIntoView({ block: 'nearest' })
        })
      },
    },
  })
  if (neighbour) window.setTimeout(() => focusBlock(neighbour.id), 0)
  return true
}

/** Delete now, or ask first when other rules read the question. */
export function requestDelete(store: BuilderStore, id: string) {
  if (!deleteElement(store, id)) store.setConfirm({ kind: 'element', id })
}

export function focusBlock(id: string) {
  const node = document.querySelector<HTMLElement>(`[data-block="${id}"] [data-block-focus]`)
  node?.focus({ preventScroll: false })
}

export function duplicate(store: BuilderStore, id: string) {
  let newId = id
  store.edit((f) => {
    const out = duplicateElement(f, id)
    newId = out.id
    return out.form
  })
  store.select({ type: 'element', id: newId })
}

export function nudge(store: BuilderStore, id: string, delta: -1 | 1) {
  store.edit((f) => nudgeElement(f, id, delta))
  window.setTimeout(() => focusBlock(id), 0)
}

export function wrap(store: BuilderStore, id: string) {
  let sectionId = id
  store.edit((f) => {
    const out = wrapInSection(f, id)
    sectionId = out.id
    return out.form
  })
  store.select({ type: 'element', id: sectionId })
}

export function moveToPage(store: BuilderStore, id: string, pageIndex: number) {
  const form: Form = store.get().schema
  const el = findElement(form, id)
  if (!el) return
  store.edit((f) => moveElement(f, id, { pageIndex, parentId: null, index: (f.pages[pageIndex].elements ?? []).length }), {
    pageId: form.pages[pageIndex].id,
    selection: { type: 'element', id },
  })
  toast(`Moved ${quoted(el.el)} to page ${pageIndex + 1}`)
}
