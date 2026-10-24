/**
 * Logic in plain words for builders: which operators a question offers, and conditions as
 * sentences ("Shown when Age is less than 18 and Has dependents is Yes").
 */
import { buildIndex } from '@/logic/form-index'
import type { Condition, Element, FieldCondition, Form, Op } from '@/schema'

import { blockLabel } from './block-types'

export const OP_LABELS: Record<Op, string> = {
  eq: 'is',
  neq: 'is not',
  in: 'is one of',
  not_in: 'is not one of',
  gt: 'is more than',
  gte: 'is at least',
  lt: 'is less than',
  lte: 'is at most',
  contains: 'contains',
  not_contains: "doesn't contain",
  empty: 'is empty',
  not_empty: 'is not empty',
  count_eq: 'has exactly',
  count_gte: 'has at least',
  count_lte: 'has at most',
}

const DATE_LABELS: Partial<Record<Op, string>> = {
  gt: 'is after',
  gte: 'is on or after',
  lt: 'is before',
  lte: 'is on or before',
}

const ORDER: Op[] = ['eq', 'neq', 'gt', 'gte', 'lt', 'lte']
const EMPTY: Op[] = ['empty', 'not_empty']
const COUNT: Op[] = ['count_eq', 'count_gte', 'count_lte']

/** Operators a condition on this element may use (DESIGN 5.2, 5.3). */
export function opsFor(el: Element | undefined): Op[] {
  if (!el) return ['eq', 'neq', ...EMPTY]
  if (el.kind === 'repeater') return [...COUNT, ...EMPTY]
  if (el.kind !== 'field') return EMPTY
  switch (el.type) {
    case 'number':
    case 'rating':
    case 'date':
    case 'time':
      return [...ORDER, ...EMPTY]
    case 'single_choice':
      return ['eq', 'neq', 'in', 'not_in', ...EMPTY]
    case 'multi_choice':
      return ['contains', 'not_contains', ...COUNT, ...EMPTY]
    case 'yes_no':
      return ['eq', ...EMPTY]
    case 'file':
      return [...COUNT, ...EMPTY]
    case 'signature':
      return EMPTY
    default:
      return ['eq', 'neq', 'contains', 'not_contains', ...EMPTY]
  }
}

export function opLabel(op: Op, el: Element | undefined): string {
  if (el?.kind === 'field' && (el.type === 'date' || el.type === 'time') && DATE_LABELS[op])
    return DATE_LABELS[op]!
  return OP_LABELS[op]
}

export function countUnit(el: Element | undefined): string {
  if (el?.kind === 'repeater') return 'rows'
  if (el?.kind === 'field' && el.type === 'file') return 'files'
  return 'selected'
}

/** A field's value written for people (option label, Yes/No, "3 rows"). */
export function valueText(el: Element | undefined, op: Op, value: unknown): string {
  if (op === 'empty' || op === 'not_empty') return ''
  if (op.startsWith('count_')) return `${String(value)} ${countUnit(el)}`
  const one = (v: unknown): string => {
    if (el?.kind === 'field' && el.type === 'yes_no') return v === true ? 'Yes' : v === false ? 'No' : String(v)
    if (el?.kind === 'field' && (el.type === 'single_choice' || el.type === 'multi_choice'))
      return el.options.find((o) => o.value === v)?.label || String(v)
    return v === null || v === undefined ? '' : String(v)
  }
  if (Array.isArray(value)) {
    const parts = value.map(one)
    return parts.length > 1 ? `${parts.slice(0, -1).join(', ')} or ${parts[parts.length - 1]}` : (parts[0] ?? '')
  }
  return one(value)
}

/** Text pieces of a condition: plain words plus form-language snippets (labels, values). */
export type Piece = { text: string; content?: boolean }

export function piecesOf(cond: Condition, form: Form, nested: boolean): Piece[] {
  const index = buildIndex(form)
  const leaf = (c: FieldCondition): Piece[] => {
    const el = index.elements.get(c.field)?.element
    const label = el ? blockLabel(el) || 'Untitled question' : '(deleted question)'
    const value = valueText(el, c.op, c.value)
    return [
      { text: label, content: !!el },
      { text: ` ${opLabel(c.op, el)}` },
      ...(value ? [{ text: ' ' }, { text: value, content: !c.op.startsWith('count_') }] : []),
    ]
  }
  if ('field' in cond) return leaf(cond)
  if ('not' in cond) return [{ text: 'not (' }, ...piecesOf(cond.not, form, false), { text: ')' }]
  const list = 'all' in cond ? cond.all : cond.any
  const joiner = 'all' in cond ? ' and ' : ' or '
  const out: Piece[] = []
  list.forEach((c, i) => {
    if (i) out.push({ text: joiner })
    out.push(...piecesOf(c, form, true))
  })
  return nested && list.length > 1 ? [{ text: '(' }, ...out, { text: ')' }] : out
}

export function conditionText(cond: Condition, form: Form): string {
  return piecesOf(cond, form, false)
    .map((p) => p.text)
    .join('')
}

/** Conditions nested deeper than one all/any group can't be edited in the UI. */
export function isSimpleCondition(cond: Condition | null | undefined): boolean {
  if (!cond) return true
  if ('field' in cond) return true
  if ('not' in cond) return false
  const list = 'all' in cond ? cond.all : cond.any
  return list.every((c) => 'field' in c)
}
