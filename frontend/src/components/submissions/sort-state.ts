/** Sort state for the submissions table (SUBMISSIONS-SORT-AND-TRASH 1): which column, which
 * direction, and the words for each. Kept in the URL as `sort` and `dir`. */
import type { SortDir } from '@/lib/api'
import type { FieldElement } from '@/schema'

export interface SortState {
  sort?: string
  dir?: SortDir
}

export type SortKind = 'number' | 'date' | 'text' | 'choice' | 'status'

/** The built-in columns. */
export const META_COLUMNS: { key: string; label: string; kind: SortKind }[] = [
  { key: '_seq', label: 'Reference', kind: 'number' },
  { key: '_submitted', label: 'Submitted', kind: 'date' },
  { key: '_status', label: 'Status', kind: 'status' },
  { key: '_approval', label: 'Approval step', kind: 'status' },
  { key: '_respondent', label: 'Respondent email', kind: 'text' },
]

export const DEFAULT_KEY = '_submitted'

/** Answers stored as files or drawings have no order. */
export function isSortable(field: FieldElement): boolean {
  return field.type !== 'file' && field.type !== 'signature'
}

export function fieldKind(field: FieldElement): SortKind {
  switch (field.type) {
    case 'number':
    case 'rating':
    case 'phone':
      return 'number'
    case 'date':
    case 'time':
      return 'date'
    case 'single_choice':
    case 'multi_choice':
    case 'yes_no':
      return 'choice'
    default:
      return 'text'
  }
}

/** The direction a column is sorted in, or null. Unset sorts by Submitted, newest first. */
export function sortedDir(state: SortState, key: string): SortDir | null {
  const active = state.sort ?? DEFAULT_KEY
  if (active !== key) return null
  return state.sort ? (state.dir ?? 'desc') : 'desc'
}

/** The state after choosing a column: the other direction when it is already sorted, else
 * its natural first direction (newest first for times and numbers of record, A to Z for
 * answers). Back to newest first clears the URL. */
export function nextSort(state: SortState, key: string): SortState {
  const current = sortedDir(state, key)
  const first: SortDir = key === '_submitted' || key === '_seq' ? 'desc' : 'asc'
  const dir: SortDir = current ? (current === 'asc' ? 'desc' : 'asc') : first
  return normalise({ sort: key, dir })
}

export function normalise(state: SortState): SortState {
  if (!state.sort || (state.sort === DEFAULT_KEY && state.dir !== 'asc')) return { sort: undefined, dir: undefined }
  return { sort: state.sort, dir: state.dir ?? 'desc' }
}

/** Words for a direction, by what is sorted. */
export function dirWords(kind: SortKind, dir: SortDir): string {
  const words: Record<SortKind, [string, string]> = {
    number: ['Low to high', 'High to low'],
    date: ['Oldest first', 'Newest first'],
    text: ['A to Z', 'Z to A'],
    choice: ['Option order', 'Reverse option order'],
    status: ['First to last', 'Last to first'],
  }
  return words[kind][dir === 'asc' ? 0 : 1]
}
