/**
 * Problems that block publishing, found on the client so each can link to its question
 * (PHASE-2-SCREENS 2.12, 3.1). The server repeats these checks on publish.
 */
import { buildIndex, iterLeaves } from '@/logic/form-index'
import { buildGraph, findCycle } from '@/logic/graph'
import type { Condition, Element, Form } from '@/schema'

import { blockInfo, blockLabel } from './block-types'
import { allElements } from './tree'
import { opsFor } from './logic-text'

export interface Problem {
  /** Element or page id to select, or null for form settings. */
  target: string | null
  pageIndex: number | null
  message: string
}

function conditionProblems(form: Form, cond: Condition | null | undefined, ownerRepeater: string | null): string[] {
  const index = buildIndex(form)
  const out: string[] = []
  for (const leaf of iterLeaves(cond)) {
    const info = index.elements.get(leaf.field)
    if (!info) {
      out.push('A rule uses a deleted question')
      continue
    }
    if (info.repeaterId !== null && info.repeaterId !== ownerRepeater)
      out.push('A rule uses a question inside a repeater from outside it')
    if (!opsFor(info.element).includes(leaf.op)) out.push(`A rule compares “${blockLabel(info.element) || leaf.field}” in a way its type doesn't support`)
  }
  return out
}

/** Problems with one element (shown as the "Fix" badge on the canvas). */
export function elementProblems(form: Form, el: Element): string[] {
  const out: string[] = []
  const repeater = buildIndex(form).elements.get(el.id)?.repeaterId ?? null
  if ((el.kind === 'field' || el.kind === 'repeater') && !(el.label ?? '').trim())
    out.push('Add a label so people know what to answer')
  if (el.kind === 'content' && (el.contentType === 'heading' || el.contentType === 'paragraph') && !el.text?.trim())
    out.push('Add text or remove this block')
  if (el.kind === 'field' && (el.type === 'single_choice' || el.type === 'multi_choice') && el.options.some((o) => !(o.label ?? '').trim()))
    out.push('Give every option a label')
  if (el.kind === 'field' && el.type === 'short_text' && el.pattern) {
    try {
      new RegExp(el.pattern, 'u')
    } catch {
      out.push("The pattern isn't a valid regular expression")
    }
  }
  out.push(...conditionProblems(form, el.visibleIf, repeater))
  if (el.kind === 'field') out.push(...conditionProblems(form, el.requiredIf, repeater))
  return out
}

/** A dependency loop in plain words, or null. */
export function cycleText(form: Form): string | null {
  const index = buildIndex(form)
  const cycle = findCycle(buildGraph(index))
  if (!cycle) return null
  const name = (node: string) => {
    if (node.startsWith('page:')) {
      const i = index.pageIndex.get(node.slice(5))
      return i === undefined ? node : `page ${i + 1}`
    }
    const el = index.elements.get(node)?.element
    return el ? blockLabel(el) || node : node
  }
  const names = cycle.map(name)
  return `This creates a loop: ${names.slice(0, -1).map((n, i) => `${n} depends on ${names[i + 1]}`).join(', which ')}. Change one of these rules.`
}

export function formProblems(form: Form): Problem[] {
  const out: Problem[] = []
  if (!form.settings.title.trim()) out.push({ target: null, pageIndex: null, message: 'Give the form a title' })
  const index = buildIndex(form)
  for (const info of index.elements.values())
    for (const message of elementProblems(form, info.element))
      out.push({ target: info.id, pageIndex: info.pageIndex, message })
  form.pages.forEach((page, i) => {
    for (const m of conditionProblems(form, page.visibleIf, null)) out.push({ target: page.id, pageIndex: i, message: m })
    for (const rule of page.next ?? []) {
      for (const m of conditionProblems(form, rule.if, null)) out.push({ target: page.id, pageIndex: i, message: m })
      const to = rule.goto === 'submit' ? Infinity : (index.pageIndex.get(rule.goto) ?? -1)
      if (to <= i) out.push({ target: page.id, pageIndex: i, message: 'A jump goes to a page that is missing or not later in the form' })
    }
  })
  const loop = cycleText(form)
  if (loop) out.push({ target: null, pageIndex: null, message: loop })
  return out
}

/**
 * Where a block sits, in words that tell rows apart even when every label is empty:
 * "Page 1, question 2 (Email)" for questions, "Page 2, heading 1" for other blocks
 * (REVIEW P2-11). Questions and repeaters are numbered together, in reading order.
 */
export function blockPosition(form: Form, id: string): string | null {
  const items = allElements(form)
  const found = items.find((e) => e.el.id === id)
  if (!found) return null
  const page = found.loc.pageIndex
  const onPage = items.filter((e) => e.loc.pageIndex === page)
  const isQuestion = (el: Element) => el.kind === 'field' || el.kind === 'repeater'
  const info = blockInfo(found.el)
  if (isQuestion(found.el)) {
    const n = onPage.filter((e) => isQuestion(e.el)).findIndex((e) => e.el.id === id) + 1
    return `Page ${page + 1}, question ${n} (${info.label})`
  }
  const n = onPage.filter((e) => !isQuestion(e.el) && blockInfo(e.el).type === info.type).findIndex((e) => e.el.id === id) + 1
  return `Page ${page + 1}, ${info.label.toLowerCase()} ${n}`
}
