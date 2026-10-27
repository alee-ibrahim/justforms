/** Sorting, copying and CSV for the submissions an answer lists (list-table.tsx). */
import type { ChartSpec } from './api'

export type ListRow = ChartSpec['rows'][number]
export interface ListSort {
  /** A column key, or `_ref` for the submission number. */
  col: string
  dir: 'asc' | 'desc'
}

const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' })

export function listRows(chart: ChartSpec): ListRow[] {
  return chart.rows
}

function cell(r: ListRow, col: string): string | number | null {
  if (col === '_ref') return r.ref ?? null
  const v = r.values[col]
  return v === undefined || v === '' ? null : v
}

/** Sorted copy; unanswered cells always last. */
export function sortRows(rows: ListRow[], sort: ListSort | null): ListRow[] {
  if (!sort) return rows
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const x = cell(a, sort.col)
    const y = cell(b, sort.col)
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1
    const n = typeof x === 'number' && typeof y === 'number' ? x - y : collator.compare(String(x), String(y))
    return n * sign
  })
}

function header(chart: ChartSpec): string[] {
  return ['Number', ...chart.columns.map((c) => chart.columnLabels?.[c] ?? c)]
}

function values(chart: ChartSpec, r: ListRow): string[] {
  return [r.ref !== undefined ? `#${r.ref}` : r.label, ...chart.columns.map((c) => String(cell(r, c) ?? ''))]
}

// Cells a spreadsheet would run as a formula. Phone numbers ("+960 777 1234") stay as they are.
const FORMULA = /^[=@\t\r]|^[+-](?![\d\s().-]*$)/

/** A cell a spreadsheet would run as a formula gets a leading apostrophe (shown as text). */
function guard(s: string): string {
  return FORMULA.test(s) ? `'${s}` : s
}

/** Tab-separated, for pasting into a spreadsheet; formulas are neutralised as in the CSV. */
export function listTsv(chart: ChartSpec, rows: ListRow[]): string {
  const clean = (s: string) => guard(s.replace(/[\t\r\n]+/g, ' '))
  return [header(chart), ...rows.map((r) => values(chart, r))].map((line) => line.map(clean).join('\t')).join('\n')
}

function csvCell(s: string): string {
  const safe = guard(s)
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

/** CSV with a byte-order mark so spreadsheets read Thaana and other non-Latin text. */
export function listCsv(chart: ChartSpec, rows: ListRow[]): string {
  const lines = [header(chart), ...rows.map((r) => values(chart, r))]
  return '﻿' + lines.map((line) => line.map(csvCell).join(',')).join('\r\n') + '\r\n'
}
