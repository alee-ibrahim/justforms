/**
 * The submissions an answer lists (INSIGHTS-SCREENS 4.2): read from the database on the
 * server and shown as answered, never written by the AI. Up to two questions read as a table
 * with sortable headers; more stack under each submission (the panel is narrow) with a Sort
 * menu. Copy (tab-separated, for spreadsheets) and CSV keep the exact stored values; long
 * lists show the first rows with "Show all".
 */
import { Link } from '@tanstack/react-router'
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  CheckIcon,
  CopyIcon,
  DownloadIcon,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatPhone } from '@/components/submissions/format'

import type { ChartSpec } from './api'
import { listCsv, listRows, listTsv, sortRows, type ListSort } from './list-data'

const FIRST = 10
const thaana = /[ހ-޿]/

const count = (n: number) => n.toLocaleString('en')

function langOf(text: string, language: string) {
  return thaana.test(text) ? 'dv' : language === 'dv' ? 'dv' : 'en'
}

/** One value for reading: phone numbers grouped and kept on one line, emails allowed to
 * break before "@" (copy and CSV keep the exact stored value). */
function Value({ value, type, language }: { value: string; type: string | undefined; language: string }) {
  if (type === 'phone')
    return (
      <bdi dir="ltr" className="whitespace-nowrap tabular-nums">
        {formatPhone(value)}
      </bdi>
    )
  if (type === 'email') {
    const at = value.indexOf('@')
    return (
      <bdi dir="ltr">
        {at > 0 ? (
          <>
            {value.slice(0, at)}
            <wbr />
            {value.slice(at)}
          </>
        ) : (
          value
        )}
      </bdi>
    )
  }
  return (
    <bdi dir="auto" lang={langOf(value, language)}>
      {value}
    </bdi>
  )
}

function fileName(title: string): string {
  const base = title
    .trim()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return `${base || 'submissions'}.csv`
}

function SortButton({
  label,
  active,
  dir,
  onClick,
  language,
}: {
  label: string
  active: boolean
  dir: 'asc' | 'desc'
  onClick: () => void
  language: string
}) {
  const Icon = !active ? ArrowUpDownIcon : dir === 'asc' ? ArrowUpIcon : ArrowDownIcon
  return (
    <Button
      variant="ghost"
      size="sm"
      className="-ms-2.5 h-auto min-h-8 max-w-full justify-start px-2.5 py-1 text-start font-medium whitespace-normal pointer-coarse:min-h-11"
      onClick={onClick}
    >
      <bdi dir="auto" lang={langOf(label, language)}>
        {label}
      </bdi>
      <Icon className={active ? '' : 'text-muted-foreground'} aria-hidden />
    </Button>
  )
}

function Ref({ r, formId }: { r: ChartSpec['rows'][number]; formId: string }) {
  if (r.ref === undefined) return <>{r.label}</>
  return (
    <Link
      to="/forms/$formId/submissions/$ref"
      params={{ formId, ref: String(r.ref) }}
      className="inline-flex items-center tabular-nums underline-offset-4 hover:underline pointer-coarse:min-h-11 pointer-coarse:min-w-11"
    >
      #{r.ref}
    </Link>
  )
}

function Cell({ v, type, language }: { v: string | number | null | undefined; type?: string; language: string }) {
  return v === null || v === undefined || v === '' ? (
    <span className="text-muted-foreground">No answer</span>
  ) : (
    <Value value={String(v)} type={type} language={language} />
  )
}

/** "Sort" menu for the stacked layout: a column, then the direction. */
function SortMenu({
  chart,
  sort,
  onSort,
}: {
  chart: ChartSpec
  sort: ListSort | null
  onSort: (s: ListSort | null) => void
}) {
  const labels = chart.columnLabels ?? {}
  const Icon = !sort ? ArrowUpDownIcon : sort.dir === 'asc' ? ArrowUpIcon : ArrowDownIcon
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Icon />
          Sort
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-w-72">
        <DropdownMenuLabel>Sort by</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={sort?.col ?? ''}
          onValueChange={(col) => onSort(col ? { col, dir: sort?.dir ?? 'asc' } : null)}
        >
          <DropdownMenuRadioItem value="">Newest first</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="_ref">Number</DropdownMenuRadioItem>
          {chart.columns.map((c) => (
            <DropdownMenuRadioItem key={c} value={c}>
              <bdi dir="auto" className="truncate">
                {labels[c] ?? c}
              </bdi>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {sort && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuRadioGroup value={sort.dir} onValueChange={(dir) => onSort({ col: sort.col, dir: dir as 'asc' | 'desc' })}>
              <DropdownMenuRadioItem value="asc">A to Z, low to high</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="desc">Z to A, high to low</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function ListTable({ chart, formId, language }: { chart: ChartSpec; formId: string; language: string }) {
  const labels = chart.columnLabels ?? {}
  const [sort, setSort] = useState<ListSort | null>(null)
  const [all, setAll] = useState(false)
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const t = window.setTimeout(() => setCopied(false), 2000)
    return () => window.clearTimeout(t)
  }, [copied])
  const rows = useMemo(() => sortRows(listRows(chart), sort), [chart, sort])
  const shown = all ? rows : rows.slice(0, FIRST)
  const total = chart.total ?? rows.length
  const stacked = chart.columns.length > 2
  const [first, ...rest] = chart.columns

  const toggle = (col: string) =>
    setSort((s) => (s?.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' }))
  const ariaSort = (col: string) => (sort?.col === col ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined)

  const copy = () =>
    void navigator.clipboard.writeText(listTsv(chart, rows)).then(
      () => setCopied(true),
      () => toast("Couldn't copy the table"),
    )
  const download = () => {
    const blob = new Blob([listCsv(chart, rows)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = fileName(chart.title)
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground tabular-nums">
          {count(rows.length)} {rows.length === 1 ? 'submission' : 'submissions'}
          {chart.truncated && total > rows.length && ` (newest of ${count(total)})`}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {stacked && <SortMenu chart={chart} sort={sort} onSort={setSort} />}
          <ButtonGroup aria-label="Table actions">
            <Button variant="outline" size="sm" onClick={copy}>
              {copied ? <CheckIcon /> : <CopyIcon />}
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button variant="outline" size="sm" onClick={download}>
              <DownloadIcon />
              CSV
            </Button>
          </ButtonGroup>
        </div>
      </div>
      {stacked ? (
        <ul className="flex flex-col border-t">
          {shown.map((r) => (
            <li key={r.ref ?? r.label} className="flex flex-col gap-1.5 border-b py-2.5">
              <div className="flex items-baseline gap-3">
                <Ref r={r} formId={formId} />
                <span className="min-w-0 font-medium break-words">
                  <Cell v={r.values[first]} type={chart.columnTypes?.[first]} language={language} />
                </span>
              </div>
              <dl className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-x-3 gap-y-1 text-sm sm:ps-11">
                {rest.map((c) => (
                  <div key={c} className="contents">
                    <dt className="text-muted-foreground break-words">
                      <bdi dir="auto" lang={langOf(labels[c] ?? c, language)}>
                        {labels[c] ?? c}
                      </bdi>
                    </dt>
                    <dd className="min-w-0 break-words">
                      <Cell v={r.values[c]} type={chart.columnTypes?.[c]} language={language} />
                    </dd>
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ul>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-auto w-16 py-1" aria-sort={ariaSort('_ref')}>
                <SortButton label="Number" active={sort?.col === '_ref'} dir={sort?.dir ?? 'asc'} onClick={() => toggle('_ref')} language="en" />
              </TableHead>
              {chart.columns.map((c) => (
                <TableHead key={c} className="h-auto py-1 whitespace-normal" aria-sort={ariaSort(c)}>
                  <SortButton
                    label={labels[c] ?? c}
                    active={sort?.col === c}
                    dir={sort?.dir ?? 'asc'}
                    onClick={() => toggle(c)}
                    language={language}
                  />
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((r) => (
              <TableRow key={r.ref ?? r.label}>
                <TableCell className="py-1.5 align-top pointer-coarse:py-0">
                  <Ref r={r} formId={formId} />
                </TableCell>
                {chart.columns.map((c) => (
                  <TableCell key={c} className="py-1.5 align-top whitespace-normal break-words pointer-coarse:py-3">
                    <Cell v={r.values[c]} type={chart.columnTypes?.[c]} language={language} />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {rows.length > FIRST && (
        <Button variant="ghost" size="sm" className="-ms-2.5 self-start" onClick={() => setAll((a) => !a)}>
          {all ? `Show the first ${FIRST}` : `Show all ${count(rows.length)}`}
        </Button>
      )}
      {chart.truncated && total > rows.length && (
        <p className="text-xs text-muted-foreground">
          The newest {count(rows.length)} of {count(total)} are listed. Export on the Responses page has them all.
        </p>
      )}
    </div>
  )
}
