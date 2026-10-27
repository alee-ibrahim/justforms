/**
 * Sorting the submissions table (SUBMISSIONS-SORT-AND-TRASH 1): column headers sort on click,
 * the cards view sorts from a Sort menu. The order is kept in the URL (`sort`, `dir`) and done
 * by the server, so every page and Previous / Next follow it. Unset is newest first.
 */
import { ArrowDownIcon, ArrowDownUpIcon, ArrowUpDownIcon, ArrowUpIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { TableHead } from '@/components/ui/table'
import type { SortDir } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { FieldElement, FormLanguage } from '@/schema'

import {
  DEFAULT_KEY,
  dirWords,
  fieldKind,
  isSortable,
  META_COLUMNS,
  nextSort,
  normalise,
  sortedDir,
  type SortKind,
  type SortState,
} from './sort-state'

/** A table header that sorts its column (aria-sort on the header, a real button inside). */
export function SortableHead({
  sortKey,
  state,
  onSort,
  kind,
  className,
  children,
}: {
  sortKey: string
  state: SortState
  onSort: (next: SortState) => void
  kind: SortKind
  className?: string
  children: ReactNode
}) {
  const dir = sortedDir(state, sortKey)
  const Icon = dir === 'asc' ? ArrowUpIcon : dir === 'desc' ? ArrowDownIcon : ArrowUpDownIcon
  const next = nextSort(state, sortKey)
  const nextDir = sortedDir(next, sortKey) ?? 'desc'
  return (
    <TableHead
      className={className}
      aria-sort={dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none'}
    >
      <Button
        variant="ghost"
        size="sm"
        className="-ms-2.5 h-8 gap-1 px-2.5 font-medium data-[sorted=true]:text-foreground"
        data-sorted={dir !== null}
        onClick={() => onSort(next)}
        title={`Sort: ${dirWords(kind, nextDir)}`}
      >
        {children}
        <Icon className={cn('size-3.5', dir === null && 'text-muted-foreground/60')} aria-hidden />
      </Button>
    </TableHead>
  )
}

/** The cards view's Sort menu: a column, then a direction. */
export function SortMenu({
  state,
  onSort,
  fields,
  language,
  showRespondent,
  showApproval,
  className,
}: {
  state: SortState
  onSort: (next: SortState) => void
  fields: FieldElement[]
  language: FormLanguage
  showRespondent: boolean
  showApproval: boolean
  className?: string
}) {
  const key = state.sort ?? DEFAULT_KEY
  const dir = sortedDir(state, key) ?? 'desc'
  const meta = META_COLUMNS.filter(
    (c) => (c.key !== '_respondent' || showRespondent) && (c.key !== '_approval' || showApproval),
  )
  const answers = fields.filter(isSortable)
  const kind =
    meta.find((c) => c.key === key)?.kind ?? (answers.find((f) => f.id === key) ? fieldKind(answers.find((f) => f.id === key)!) : 'text')
  const label = meta.find((c) => c.key === key)?.label ?? answers.find((f) => f.id === key)?.label ?? 'Submitted'
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className={className} aria-label={`Sort: ${label}, ${dirWords(kind, dir)}`}>
          <ArrowDownUpIcon />
          <span className="max-w-40 truncate">
            Sort: <bdi dir="auto">{label}</bdi>
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-(--radix-dropdown-menu-content-available-height) min-w-56">
        <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">Direction</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={dir} onValueChange={(d) => onSort(normalise({ sort: key, dir: d as SortDir }))}>
          <DropdownMenuRadioItem value="asc">{dirWords(kind, 'asc')}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="desc">{dirWords(kind, 'desc')}</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">Sort by</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={key}
          onValueChange={(k) => onSort(normalise({ sort: k, dir: k === '_submitted' || k === '_seq' ? 'desc' : 'asc' }))}
        >
          {meta.map((c) => (
            <DropdownMenuRadioItem key={c.key} value={c.key}>
              {c.label}
            </DropdownMenuRadioItem>
          ))}
          {answers.length > 0 && <DropdownMenuSeparator />}
          {answers.map((f) => (
            <DropdownMenuRadioItem key={f.id} value={f.id}>
              <bdi dir="auto" lang={language} className="truncate">
                {f.label || f.id}
              </bdi>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
