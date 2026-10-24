/** Flat index over a form's pages and elements. Twin of backend/app/logic/index.py. */
import type { Condition, Element, FieldCondition, Form, Page } from '@/schema'

export interface ElementInfo {
  id: string
  element: Element
  kind: Element['kind']
  type: string | null
  pageIndex: number
  parentId: string | null
  repeaterId: string | null
  sectionDepth: number
}

export interface FormIndex {
  form: Form
  pages: Page[]
  pageIndex: Map<string, number>
  elements: Map<string, ElementInfo>
  duplicates: string[]
  topLevel: string[]
}

export function pageNode(pageId: string): string {
  return `page:${pageId}`
}

export function buildIndex(form: Form): FormIndex {
  const elements = new Map<string, ElementInfo>()
  const duplicates: string[] = []
  const pageIndex = new Map<string, number>()
  const seen = new Set<string>()

  form.pages.forEach((page, i) => {
    if (seen.has(page.id)) duplicates.push(page.id)
    seen.add(page.id)
    if (!pageIndex.has(page.id)) pageIndex.set(page.id, i)
  })

  const walk = (
    items: Element[],
    pageI: number,
    parent: string | null,
    repeater: string | null,
    depth: number,
  ) => {
    for (const el of items) {
      if (seen.has(el.id)) {
        duplicates.push(el.id)
        continue
      }
      seen.add(el.id)
      elements.set(el.id, {
        id: el.id,
        element: el,
        kind: el.kind,
        type: el.kind === 'field' ? el.type : null,
        pageIndex: pageI,
        parentId: parent,
        repeaterId: repeater,
        sectionDepth: depth,
      })
      if (el.kind === 'section') walk(el.elements ?? [], pageI, el.id, repeater, depth + 1)
      else if (el.kind === 'repeater') walk(el.elements ?? [], pageI, el.id, el.id, depth)
    }
  }
  form.pages.forEach((page, i) => walk(page.elements ?? [], i, null, null, 0))

  const topLevel = [...elements.values()].filter((e) => e.repeaterId === null).map((e) => e.id)
  return { form, pages: form.pages, pageIndex, elements, duplicates, topLevel }
}

export function* iterLeaves(cond: Condition | null | undefined): Generator<FieldCondition> {
  if (!cond) return
  const stack: Condition[] = [cond]
  while (stack.length) {
    const node = stack.pop()!
    if ('field' in node) yield node
    else if ('all' in node) stack.push(...node.all)
    else if ('any' in node) stack.push(...node.any)
    else stack.push(node.not)
  }
}

export function visibleIfOf(el: Element): Condition | null {
  return el.visibleIf ?? null
}

export function requiredIfOf(el: Element): Condition | null {
  return el.kind === 'field' ? (el.requiredIf ?? null) : null
}
