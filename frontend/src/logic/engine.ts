/**
 * The JustForms rule engine (DESIGN section 5). Twin of backend/app/logic/engine.py: both must
 * agree exactly on spec/logic/vectors (run by vitest and pytest). Change both together and add
 * a vector for every fix.
 */
import type { Condition, Form, Op } from '@/schema'

import { type FormIndex, buildIndex, requiredIfOf, visibleIfOf } from './form-index'

export const MISSING: unique symbol = Symbol('missing')

const DATE_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/
const TIME_RE = /^[0-9]{2}:[0-9]{2}$/

export class LogicCycleError extends Error {}

type Json = unknown
type Answers = Record<string, Json>

// -- operators (section 5.2) --------------------------------------------------------------

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

export function isMissing(v: unknown): boolean {
  return (
    v === MISSING ||
    v === null ||
    v === undefined ||
    v === '' ||
    (Array.isArray(v) && v.length === 0)
  )
}

const isNumber = (v: unknown): v is number => typeof v === 'number'
const nfc = (s: string) => s.normalize('NFC')

export function jsonEqual(a: unknown, b: unknown): boolean {
  if (typeof a === 'boolean' || typeof b === 'boolean') return a === b
  if (isNumber(a) && isNumber(b)) return a === b
  if (typeof a === 'string' && typeof b === 'string') return nfc(a) === nfc(b)
  if (Array.isArray(a) && Array.isArray(b))
    return a.length === b.length && a.every((x, i) => jsonEqual(x, b[i]))
  if (isPlainObject(a) && isPlainObject(b)) {
    const ka = Object.keys(a)
    return (
      ka.length === Object.keys(b).length &&
      ka.every((k) => Object.hasOwn(b, k) && jsonEqual(a[k], b[k]))
    )
  }
  return a === null && b === null
}

function compare(a: unknown, b: unknown): number | null {
  if (isNumber(a) && isNumber(b)) return a > b ? 1 : a < b ? -1 : 0
  if (typeof a === 'string' && typeof b === 'string') {
    const x = nfc(a)
    const y = nfc(b)
    if ((DATE_RE.test(x) && DATE_RE.test(y)) || (TIME_RE.test(x) && TIME_RE.test(y)))
      return x > y ? 1 : x < y ? -1 : 0
  }
  return null
}

const NEGATIONS: Partial<Record<Op, Op>> = { neq: 'eq', not_in: 'in', not_contains: 'contains' }

export function applyOp(op: Op, value: unknown, target: unknown): boolean {
  if (op === 'empty') return isMissing(value)
  if (op === 'not_empty') return !isMissing(value)
  const positive = NEGATIONS[op]
  if (positive) return !applyOp(positive, value, target)
  if (isMissing(value)) return false
  switch (op) {
    case 'eq':
      return jsonEqual(value, target)
    case 'gt':
    case 'gte':
    case 'lt':
    case 'lte': {
      const c = compare(value, target)
      if (c === null) return false
      return op === 'gt' ? c > 0 : op === 'gte' ? c >= 0 : op === 'lt' ? c < 0 : c <= 0
    }
    case 'in':
      if (!Array.isArray(target) || Array.isArray(value) || isPlainObject(value)) return false
      return target.some((t) => jsonEqual(value, t))
    case 'contains':
      if (Array.isArray(value)) return value.some((v) => jsonEqual(v, target))
      if (typeof value === 'string' && typeof target === 'string')
        return nfc(value).includes(nfc(target))
      return false
    case 'count_eq':
    case 'count_gte':
    case 'count_lte': {
      if (!Array.isArray(value) || !isNumber(target)) return false
      const n = value.length
      return op === 'count_eq' ? n === target : op === 'count_gte' ? n >= target : n <= target
    }
    default:
      return false
  }
}

// -- evaluation (section 5.4) -------------------------------------------------------------

export interface RowResult {
  visible: string[]
  hidden: string[]
  required: string[]
}

export interface Evaluation {
  visible: string[]
  hidden: string[]
  required: string[]
  path: string[]
  rows: Record<string, RowResult[]>
  strippedAnswers: Answers
}

type RowRef = [repeaterId: string, row: number] | null

class Evaluator {
  private readonly index: FormIndex
  private readonly answers: Answers
  private readonly vis = new Map<string, boolean>()
  private readonly rowVis = new Map<string, boolean>()
  private readonly inProgress = new Set<string>()
  private readonly path: number[] = []
  private readonly onPathSet = new Set<number>()
  private frontier = -1
  private started = false
  private done = false
  private stepping = false

  constructor(form: Form, answers: unknown) {
    this.index = buildIndex(form)
    this.answers = isPlainObject(answers) ? answers : {}
  }

  private rowsOf(repeaterId: string): Record<string, unknown>[] {
    const raw = this.answers[repeaterId]
    if (!Array.isArray(raw)) return []
    return raw.map((r) => (isPlainObject(r) ? r : {}))
  }

  private value(fieldId: string, row: RowRef): unknown {
    const info = this.index.elements.get(fieldId)!
    if (info.repeaterId !== null) {
      if (row === null || row[0] !== info.repeaterId) return MISSING
      const [rep, i] = row
      if (!this.visibleInRow(fieldId, rep, i)) return MISSING
      const data = this.rowsOf(rep)[i]
      return Object.hasOwn(data, fieldId) ? data[fieldId] : MISSING
    }
    if (!this.visible(fieldId)) return MISSING
    return Object.hasOwn(this.answers, fieldId) ? this.answers[fieldId] : MISSING
  }

  private cond(cond: Condition | null | undefined, row: RowRef): boolean {
    if (!cond) return true
    if ('field' in cond) return applyOp(cond.op, this.value(cond.field, row), cond.value)
    if ('all' in cond) return cond.all.every((c) => this.cond(c, row))
    if ('any' in cond) return cond.any.some((c) => this.cond(c, row))
    return !this.cond(cond.not, row)
  }

  // navigation

  private onPath(pageI: number): boolean {
    while (pageI > this.frontier && !this.done) {
      if (this.stepping)
        throw new LogicCycleError(`page ${this.index.pages[pageI].id} depends on itself`)
      this.step()
    }
    return this.onPathSet.has(pageI)
  }

  private firstVisibleFrom(start: number): number | null {
    for (let k = start; k < this.index.pages.length; k++) {
      this.frontier = k - 1
      if (this.cond(this.index.pages[k].visibleIf, null)) return k
    }
    return null
  }

  private step(): void {
    this.stepping = true
    try {
      let next: number | null
      if (!this.started) {
        this.started = true
        next = this.firstVisibleFrom(0)
      } else {
        const j = this.path[this.path.length - 1]
        let goto: string | null = null
        for (const rule of this.index.pages[j].next ?? []) {
          if (this.cond(rule.if, null)) {
            goto = rule.goto
            break
          }
        }
        if (goto === 'submit') next = null
        else next = this.firstVisibleFrom(goto !== null ? this.index.pageIndex.get(goto)! : j + 1)
      }
      if (next === null) {
        this.done = true
        this.frontier = this.index.pages.length - 1
      } else {
        this.path.push(next)
        this.onPathSet.add(next)
        this.frontier = next
      }
    } finally {
      this.stepping = false
    }
  }

  // visibility

  private visible(id: string): boolean {
    const cached = this.vis.get(id)
    if (cached !== undefined) return cached
    if (this.inProgress.has(id)) throw new LogicCycleError(`'${id}' depends on itself`)
    this.inProgress.add(id)
    const info = this.index.elements.get(id)!
    let ok = info.parentId !== null ? this.visible(info.parentId) : this.onPath(info.pageIndex)
    if (ok) ok = this.cond(visibleIfOf(info.element), null)
    this.inProgress.delete(id)
    this.vis.set(id, ok)
    return ok
  }

  private visibleInRow(id: string, repeaterId: string, i: number): boolean {
    const key = `${id}\u0000${i}`
    const cached = this.rowVis.get(key)
    if (cached !== undefined) return cached
    if (this.inProgress.has(key)) throw new LogicCycleError(`'${id}' (row ${i}) depends on itself`)
    this.inProgress.add(key)
    const info = this.index.elements.get(id)!
    const parent = info.parentId!
    let ok =
      parent === repeaterId
        ? this.visible(repeaterId) && i < this.rowsOf(repeaterId).length
        : this.visibleInRow(parent, repeaterId, i)
    if (ok) ok = this.cond(visibleIfOf(info.element), [repeaterId, i])
    this.inProgress.delete(key)
    this.rowVis.set(key, ok)
    return ok
  }

  private required(id: string, row: RowRef): boolean {
    const el = this.index.elements.get(id)!.element
    if (el.kind !== 'field') return false
    const requiredIf = requiredIfOf(el)
    return el.required === true || (requiredIf !== null && this.cond(requiredIf, row))
  }

  run(): Evaluation {
    const visible: string[] = []
    const hidden: string[] = []
    const required: string[] = []
    const rows: Record<string, RowResult[]> = {}
    const stripped: Answers = {}

    for (const id of this.index.topLevel) {
      if (this.visible(id)) {
        visible.push(id)
        if (this.required(id, null)) required.push(id)
      } else {
        hidden.push(id)
      }
    }
    while (!this.done) this.step()

    for (const id of visible) {
      const info = this.index.elements.get(id)!
      if (info.kind === 'field') {
        if (Object.hasOwn(this.answers, id)) stripped[id] = this.answers[id]
      } else if (info.kind === 'repeater') {
        const children = [...this.index.elements.values()]
          .filter((e) => e.repeaterId === id)
          .map((e) => e.id)
        const results: RowResult[] = []
        const strippedRows: Answers[] = []
        this.rowsOf(id).forEach((rowData, i) => {
          const res: RowResult = { visible: [], hidden: [], required: [] }
          const kept: Answers = {}
          for (const child of children) {
            if (this.visibleInRow(child, id, i)) {
              res.visible.push(child)
              if (this.required(child, [id, i])) res.required.push(child)
              if (this.index.elements.get(child)!.kind === 'field' && Object.hasOwn(rowData, child))
                kept[child] = rowData[child]
            } else {
              res.hidden.push(child)
            }
          }
          results.push(res)
          strippedRows.push(kept)
        })
        rows[id] = results
        if (Object.hasOwn(this.answers, id)) {
          const raw = this.answers[id]
          stripped[id] = Array.isArray(raw) ? strippedRows : raw
        }
      }
    }

    return {
      visible,
      hidden,
      required,
      path: this.path.map((i) => this.index.pages[i].id),
      rows,
      strippedAnswers: stripped,
    }
  }
}

export function evaluate(form: Form, answers: unknown): Evaluation {
  return new Evaluator(form, answers).run()
}
