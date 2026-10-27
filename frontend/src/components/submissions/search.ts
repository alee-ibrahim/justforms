/** Submissions view state kept in the URL (PHASE-3-SCREENS 4): shareable, and Back works. */
import type { Condition, FieldFilter, FilterOp, SortDir, SubmissionStatus } from '@/lib/api'

/** A status, All, or Deleted (the trash; owners). */
export type Tab = SubmissionStatus | 'all' | 'deleted'

export interface SubmissionsSearch {
  status?: Tab
  q?: string
  from?: string
  to?: string
  version?: number
  fields?: FieldFilter[]
  /** Conditions from an Insights bar or an AI answer ("Show these submissions"). */
  where?: Condition[]
  whereAny?: Condition[]
  /** What those conditions mean, in words (the filter chip). */
  whereLabel?: string
  /** Submission to open in the detail sheet (links from notification emails). */
  open?: string
  /** Column order (a column key, see `sort.ts`); unset is newest first. */
  sort?: string
  dir?: SortDir
}

const TABS = new Set(['new', 'in_review', 'approved', 'rejected', 'all', 'deleted'])
const SORT_KEY = /^_?[a-z][a-z0-9_]{0,62}$/
const OPS = new Set<FilterOp>(['contains', 'eq', 'neq', 'gte', 'lte', 'includes', 'answered', 'unanswered'])
const DAY = /^\d{4}-\d{2}-\d{2}$/

function fieldFilters(raw: unknown): FieldFilter[] | undefined {
  if (!Array.isArray(raw)) return undefined
  const out = raw.filter(
    (f): f is FieldFilter =>
      typeof f === 'object' &&
      f !== null &&
      typeof (f as FieldFilter).field === 'string' &&
      OPS.has((f as FieldFilter).op) &&
      ['string', 'number', 'boolean', 'undefined'].includes(typeof (f as FieldFilter).value),
  )
  return out.length ? out.slice(0, 20) : undefined
}

const KEY = /^(_status|_submitted|_version|[a-z][a-z0-9_]{0,62})$/
const SCALAR = ['string', 'number', 'boolean']

function conditions(raw: unknown): Condition[] | undefined {
  if (!Array.isArray(raw)) return undefined
  const out = raw.filter(
    (c): c is Condition =>
      typeof c === 'object' &&
      c !== null &&
      typeof (c as Condition).field === 'string' &&
      KEY.test((c as Condition).field) &&
      typeof (c as Condition).op === 'string' &&
      ((c as Condition).value == null || SCALAR.includes(typeof (c as Condition).value)) &&
      ((c as Condition).values == null ||
        (Array.isArray((c as Condition).values) && (c as Condition).values!.every((v) => SCALAR.includes(typeof v)))),
  )
  return out.length ? out.slice(0, 20) : undefined
}

export function validateSubmissionsSearch(search: Record<string, unknown>): SubmissionsSearch {
  return {
    status: typeof search.status === 'string' && TABS.has(search.status) ? (search.status as Tab) : undefined,
    q: typeof search.q === 'string' && search.q ? search.q.slice(0, 200) : undefined,
    from: typeof search.from === 'string' && DAY.test(search.from) ? search.from : undefined,
    to: typeof search.to === 'string' && DAY.test(search.to) ? search.to : undefined,
    version: typeof search.version === 'number' && search.version > 0 ? search.version : undefined,
    fields: fieldFilters(search.fields),
    where: conditions(search.where),
    whereAny: conditions(search.whereAny),
    whereLabel: typeof search.whereLabel === 'string' && search.whereLabel ? search.whereLabel.slice(0, 300) : undefined,
    open: typeof search.open === 'string' && /^[0-9a-f-]{36}$/i.test(search.open) ? search.open : undefined,
    sort: typeof search.sort === 'string' && SORT_KEY.test(search.sort) ? search.sort : undefined,
    dir: search.dir === 'asc' || search.dir === 'desc' ? search.dir : undefined,
  }
}
