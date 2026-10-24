/**
 * Submissions (PHASE-2-SCREENS 5, PHASE-3-SCREENS 4-7): status tabs, search, filters, column
 * picker, table with selection and bulk actions, Excel export, detail sheet.
 */
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { ChevronDownIcon, FileSpreadsheetIcon, InboxIcon, LockIcon, SearchIcon, UploadIcon } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useFormSummary } from '@/components/builder/form-context'
import { PageContainer } from '@/components/layout/page'
import { BulkBar } from '@/components/submissions/bulk-bar'
import { CheckPdfDialog } from '@/components/submissions/check-pdf-dialog'
import { ColumnPicker } from '@/components/submissions/column-picker'
import { SubmissionSheet } from '@/components/submissions/detail-sheet'
import { ExportDialog } from '@/components/submissions/export-dialog'
import { AddFilter, DateRangeFilter, FilterChips, VersionFilter } from '@/components/submissions/filters'
import { answerText } from '@/components/submissions/format'
import { STATUS_LABELS } from '@/components/submissions/labels'
import type { SubmissionsSearch, Tab } from '@/components/submissions/search'
import { SubmissionStatusBadge } from '@/components/submissions/status-badge'
import { useColumns } from '@/components/submissions/use-columns'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item'
import { Kbd } from '@/components/ui/kbd'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api, type ListFilters, type SubmissionSummary } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { meQuery, versionQuery, versionsQuery } from '@/lib/queries'
import { useDelayed } from '@/lib/use-delayed'
import { buildIndex } from '@/logic/form-index'
import type { FieldElement, Form } from '@/schema'
import { formLanguage } from '@/schema/language'

const TABS: Tab[] = ['new', 'in_review', 'approved', 'rejected', 'all']

/** The generated Checkbox draws a tick for every checked state; show a dash when only some
 * rows are selected (REVIEW P2-13). Styling at the call site, the component is unchanged. */
const INDETERMINATE =
  "data-[state=indeterminate]:border-primary data-[state=indeterminate]:bg-primary data-[state=indeterminate]:[&_svg]:hidden data-[state=indeterminate]:before:h-0.5 data-[state=indeterminate]:before:w-2 data-[state=indeterminate]:before:rounded-full data-[state=indeterminate]:before:bg-primary-foreground data-[state=indeterminate]:before:content-['']"

/** The first status tab with submissions in it, else All. */
function firstNonEmptyTab(counts: Record<Tab, number>): Tab {
  return TABS.find((t) => t !== 'all' && counts[t] > 0) ?? 'all'
}
const EMPTY = new Set<string>()

/** Top-level questions of a version, in form order (repeaters have their own sheets). */
function topFields(form: Form | undefined): FieldElement[] {
  if (!form) return []
  return [...buildIndex(form).elements.values()]
    .filter((i) => i.repeaterId === null && i.kind === 'field')
    .map((i) => i.element as FieldElement)
    .filter((f) => f.type !== 'hidden')
}

function Cell({ field, row, form }: { field: FieldElement; row: SubmissionSummary; form: Form }) {
  const text = answerText(field, row.data[field.id], formLanguage(form))
  if (!text) return <span className="text-muted-foreground">-</span>
  if (field.sensitive)
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex items-center gap-1 tabular-nums" tabIndex={0}>
            <LockIcon className="size-3.5 text-muted-foreground" aria-label="Sensitive" />
            {text}
          </span>
        </TooltipTrigger>
        <TooltipContent>Sensitive. Open the submission to view.</TooltipContent>
      </Tooltip>
    )
  return (
    <bdi dir="auto" lang={row.language} className="inline-block max-w-56 truncate align-middle">
      {text}
    </bdi>
  )
}

export function FormSubmissionsPage() {
  const form = useFormSummary()
  const me = useQuery(meQuery)
  const search = useSearch({ strict: false }) as SubmissionsSearch
  const navigate = useNavigate()
  const setSearch = (patch: Partial<SubmissionsSearch>) =>
    void navigate({
      to: '.',
      search: (prev: SubmissionsSearch) => {
        const next: Record<string, unknown> = { ...prev, ...patch }
        for (const k of Object.keys(next)) if (next[k] === undefined || next[k] === '') delete next[k]
        return next
      },
      replace: true,
    } as never)

  const stats = useQuery({
    queryKey: ['submissions', form.id, 'stats'],
    queryFn: () => api.submissionStats(form.id),
    enabled: form.currentVersion !== null,
  })
  // Without a tab in the link, open the first tab that has submissions, else All, and keep it
  // in the URL so later count changes don't move the view (REVIEW P3-10).
  const tab: Tab = search.status ?? (stats.data ? firstNonEmptyTab(stats.data) : 'new')
  const pickedTab = !!search.status || !!stats.data || stats.isError
  useEffect(() => {
    if (search.status || !stats.data) return
    const status = firstNonEmptyTab(stats.data)
    void navigate({ to: '.', search: (prev: SubmissionsSearch) => ({ ...prev, status }), replace: true } as never)
  }, [search.status, stats.data, navigate])
  const [query, setQuery] = useState(search.q ?? '')
  // Typing updates the URL (and the list) after a 300 ms pause.
  const typing = useRef<number | undefined>(undefined)
  const onType = (value: string) => {
    setQuery(value)
    window.clearTimeout(typing.current)
    typing.current = window.setTimeout(() => setSearch({ q: value.trim() || undefined }), 300)
  }
  useEffect(() => () => window.clearTimeout(typing.current), [])
  const fieldFilters = useMemo(() => search.fields ?? [], [search.fields])

  const filters: ListFilters = useMemo(
    () => ({
      status: tab === 'all' ? undefined : tab,
      q: search.q,
      from: search.from,
      to: search.to,
      version: search.version,
      fields: fieldFilters,
    }),
    [tab, search.q, search.from, search.to, search.version, fieldFilters],
  )
  // A link like ?open=<id> (from a notification email) opens that submission once.
  const [openId, setOpenIdState] = useState<string | null>(search.open ?? null)
  const setOpenId = (id: string | null) => {
    setOpenIdState(id)
    if (search.open) setSearch({ open: undefined })
  }
  // The selection belongs to one filtered view; a new filter starts a new selection.
  const filtersKey = JSON.stringify(filters)
  const [selection, setSelection] = useState<{ key: string; ids: Set<string> }>({ key: '', ids: new Set() })
  const selected = selection.key === filtersKey ? selection.ids : EMPTY
  const setSelected = (ids: Set<string> | ((prev: Set<string>) => Set<string>)) =>
    setSelection((prev) => ({
      key: filtersKey,
      ids: typeof ids === 'function' ? ids(prev.key === filtersKey ? prev.ids : EMPTY) : ids,
    }))
  const [exporting, setExporting] = useState<ListFilters | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const live = useQuery(versionQuery(form.id, form.currentVersion))
  const versions = useQuery({ ...versionsQuery(form.id), enabled: form.currentVersion !== null })
  const list = useInfiniteQuery({
    queryKey: ['submissions', form.id, filters],
    queryFn: ({ pageParam }) => api.listSubmissions(form.id, { ...filters, cursor: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    enabled: form.currentVersion !== null && pickedTab,
  })
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data])
  const total = list.data?.pages[0]?.total ?? 0
  const showSkeleton = useDelayed(list.isPending)
  const schema = live.data?.schema
  const language = schema ? formLanguage(schema) : 'en'
  const fields = useMemo(() => topFields(schema), [schema])
  const {
    columns: cols,
    ids: colIds,
    respondent: showRespondent,
    save: saveColumns,
  } = useColumns(me.data?.id, form.id, fields, form.accessMode !== 'public')
  const canEdit = form.role !== 'viewer'
  const canDelete = form.role === 'owner'
  const sensitive = fields.filter((f) => f.sensitive).map((f) => f.label)
  const idx = rows.findIndex((r) => r.id === openId)
  const url = form.url
  const filtered = !!(search.q || search.from || search.to || search.version || fieldFilters.length)
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id))
  const someSelected = rows.some((r) => selected.has(r.id))

  const tabList = useRef<HTMLDivElement>(null)
  useEffect(() => {
    tabList.current
      ?.querySelector<HTMLElement>('[data-state=active]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [tab, stats.data])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.key !== '/' || ['INPUT', 'TEXTAREA'].includes(t.tagName)) return
      e.preventDefault()
      document.getElementById('submission-search')?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const exportWith = (f: ListFilters) => {
    setExporting(f)
    setExportOpen(true)
  }
  const clearFilters = () => {
    window.clearTimeout(typing.current)
    setQuery('')
    setSearch({ status: 'all', q: undefined, from: undefined, to: undefined, version: undefined, fields: undefined })
  }
  const toggle = (id: string, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })

  if (form.currentVersion === null)
    return (
      <PageContainer>
        <h1 className="text-xl font-semibold tracking-tight">Submissions</h1>
        <Empty className="border bg-card">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <InboxIcon />
            </EmptyMedia>
            <EmptyTitle>No submissions yet</EmptyTitle>
            <EmptyDescription>Publish your form and share the link to start collecting responses.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button asChild>
              <Link to="/forms/$formId/share" params={{ formId: form.id }}>
                Go to Share
              </Link>
            </Button>
          </EmptyContent>
        </Empty>
      </PageContainer>
    )

  const none = stats.data?.all === 0
  return (
    <PageContainer>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Submissions</h1>
        <div className="flex flex-wrap items-center gap-2">
          {form.role === 'owner' && (
            <Button variant="outline" size="sm" asChild>
              <Link to="/forms/$formId/submissions/import" params={{ formId: form.id }}>
                <UploadIcon />
                Import responses
              </Link>
            </Button>
          )}
          <CheckPdfDialog />
          {!none && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm">
                  <FileSpreadsheetIcon />
                  Export
                  <ChevronDownIcon />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => exportWith(filters)} disabled={total === 0}>
                  Export all matching (<span className="tabular-nums">{total}</span>)
                </DropdownMenuItem>
                {selected.size > 0 && (
                  <DropdownMenuItem onSelect={() => exportWith({ ids: [...selected] })}>
                    Export selected (<span className="tabular-nums">{selected.size}</span>)
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
      {none ? (
        <Empty className="border bg-card">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <InboxIcon />
            </EmptyMedia>
            <EmptyTitle>No submissions yet</EmptyTitle>
            <EmptyDescription>Responses appear here as soon as someone submits the form.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="outline" onClick={() => void navigator.clipboard?.writeText(url)}>
                Copy form link
              </Button>
              {form.role === 'owner' && (
                <Button variant="ghost" asChild>
                  <Link to="/forms/$formId/submissions/import" params={{ formId: form.id }}>
                    <UploadIcon />
                    Import from Jotform
                  </Link>
                </Button>
              )}
            </div>
          </EmptyContent>
        </Empty>
      ) : (
        <>
          <Tabs value={tab} onValueChange={(v) => setSearch({ status: v as Tab })}>
            {/* Phones: the tabs scroll sideways, starting at the first tab, with a scrollbar cue.
                Sideways only: no stray vertical thumb from the focus ring (REVIEW P3-11). */}
            <ScrollArea
              className="w-full max-w-full pb-2 md:pb-0 [&>[data-slot=scroll-area-scrollbar][data-orientation=vertical]]:hidden [&>[data-slot=scroll-area-viewport]]:overflow-y-hidden!"
              data-scroll-x
            >
              <TabsList className="w-max justify-start" ref={tabList}>
                {TABS.map((t) => (
                  <TabsTrigger key={t} value={t} className="flex-none gap-1.5">
                    {t === 'all' ? 'All' : STATUS_LABELS[t]}
                    {stats.data && (
                      <Badge variant="secondary" className="tabular-nums">
                        {stats.data[t]}
                      </Badge>
                    )}
                  </TabsTrigger>
                ))}
              </TabsList>
              <ScrollBar orientation="horizontal" />
            </ScrollArea>
          </Tabs>
          {selected.size > 0 && canEdit ? (
            <BulkBar
              formId={form.id}
              ids={[...selected]}
              canDelete={canDelete}
              onClear={() => setSelected(new Set())}
              onExport={() => exportWith({ ids: [...selected] })}
            />
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <InputGroup className="max-w-xs">
                  <InputGroupAddon>
                    <SearchIcon />
                  </InputGroupAddon>
                  <InputGroupInput
                    id="submission-search"
                    placeholder="Search answers"
                    aria-label="Search answers"
                    value={query}
                    onChange={(e) => onType(e.target.value)}
                  />
                  <InputGroupAddon align="inline-end">
                    <Kbd>/</Kbd>
                  </InputGroupAddon>
                </InputGroup>
                <AddFilter
                  fields={fields}
                  language={language}
                  onAdd={(f) => setSearch({ fields: [...fieldFilters, f] })}
                />
                <DateRangeFilter from={search.from} to={search.to} onChange={(r) => setSearch(r)} />
                <VersionFilter
                  versions={(versions.data ?? []).map((v) => v.version).sort((a, b) => b - a)}
                  value={search.version}
                  onChange={(version) => setSearch({ version })}
                />
                <div className="ms-auto max-md:hidden">
                  <ColumnPicker fields={fields} ids={colIds} language={language} onChange={saveColumns} />
                </div>
              </div>
              {(fieldFilters.length > 0 || filtered) && (
                <div className="flex flex-wrap items-center gap-2">
                  <FilterChips
                    filters={fieldFilters}
                    fields={fields}
                    language={language}
                    onRemove={(i) => setSearch({ fields: fieldFilters.filter((_, j) => j !== i) })}
                  />
                  <Button variant="link" size="sm" onClick={clearFilters}>
                    Clear filters
                  </Button>
                </div>
              )}
            </div>
          )}
          {list.isError && (
            <Alert variant="destructive">
              <AlertDescription className="flex items-center gap-3">
                Couldn't load submissions. Check your connection.
                <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
                  Try again
                </Button>
              </AlertDescription>
            </Alert>
          )}
          {list.isPending ? (
            showSkeleton && (
              <div className="flex flex-col gap-1">
                {Array.from({ length: 8 }, (_, i) => (
                  <Skeleton key={i} className="h-10" />
                ))}
              </div>
            )
          ) : (
            <>
              <div className="rounded-md border bg-card max-md:hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {canEdit && (
                        <TableHead className="w-10 ps-4">
                          <Checkbox
                            aria-label="Select all shown"
                            className={INDETERMINATE}
                            checked={allSelected ? true : someSelected ? 'indeterminate' : false}
                            onCheckedChange={(on) =>
                              setSelected(on ? new Set(rows.map((r) => r.id)) : new Set())
                            }
                          />
                        </TableHead>
                      )}
                      <TableHead className={canEdit ? 'w-20' : 'w-20 ps-4'}>#</TableHead>
                      <TableHead>Submitted</TableHead>
                      <TableHead>Status</TableHead>
                      {showRespondent && <TableHead>Respondent email</TableHead>}
                      {cols.map((c) => (
                        <TableHead key={c.id}>
                          <bdi dir="auto" lang={language}>
                            {c.label}
                          </bdi>
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row) => (
                      <TableRow
                        key={row.id}
                        tabIndex={0}
                        className="h-10 cursor-pointer outline-none focus-visible:ring-3 focus-visible:ring-ring/50 data-[open=true]:bg-accent"
                        data-open={row.id === openId}
                        data-state={selected.has(row.id) ? 'selected' : undefined}
                        data-submission={row.id}
                        onClick={() => setOpenId(row.id)}
                        onKeyDown={(e) => {
                          if (e.key !== 'Enter' || e.target !== e.currentTarget) return
                          // Without this the same Enter also clicks the sheet's first button
                          // (Next) once focus moves into it, opening the wrong submission.
                          e.preventDefault()
                          setOpenId(row.id)
                        }}
                      >
                        {canEdit && (
                          <TableCell className="ps-4" onClick={(e) => e.stopPropagation()}>
                            <Checkbox
                              aria-label={`Select #${row.seq}`}
                              checked={selected.has(row.id)}
                              onCheckedChange={(on) => toggle(row.id, on === true)}
                            />
                          </TableCell>
                        )}
                        <TableCell className={canEdit ? 'tabular-nums' : 'ps-4 tabular-nums'}>{row.seq}</TableCell>
                        <TableCell className="tabular-nums text-muted-foreground">{formatDateTime(row.submittedAt)}</TableCell>
                        <TableCell>
                          <span className="inline-flex items-center gap-2">
                            <SubmissionStatusBadge status={row.status} />
                            <ApprovalStep row={row} />
                          </span>
                        </TableCell>
                        {showRespondent && (
                          <TableCell>
                            {row.respondentEmail ? (
                              <bdi dir="ltr" className="inline-block max-w-56 truncate align-middle">
                                {row.respondentEmail}
                              </bdi>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                        )}
                        {cols.map((c) => (
                          <TableCell key={c.id}>{schema && <Cell field={c} row={row} form={schema} />}</TableCell>
                        ))}
                      </TableRow>
                    ))}
                    {!rows.length && (
                      <TableRow>
                        <TableCell colSpan={(canEdit ? 4 : 3) + (showRespondent ? 1 : 0) + cols.length} className="py-8 text-center text-muted-foreground">
                          No submissions match these filters.{' '}
                          <Button variant="link" onClick={clearFilters}>
                            Clear filters
                          </Button>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
              <ItemGroup className="gap-2 md:hidden">
                {rows.map((row) => (
                  <Item key={row.id} variant="outline" className="bg-card" asChild>
                    <button type="button" data-submission={row.id} onClick={() => setOpenId(row.id)}>
                      <ItemContent className="min-w-0 text-start">
                        <ItemTitle className="max-w-full tabular-nums">
                          #{row.seq} {cols[0] && schema && <Cell field={cols[0]} row={row} form={schema} />}
                        </ItemTitle>
                        <ItemDescription className="tabular-nums">
                          {formatDateTime(row.submittedAt)}
                          {row.respondentEmail && (
                            <>
                              , <bdi dir="ltr">{row.respondentEmail}</bdi>
                            </>
                          )}
                          {row.approval?.state === 'pending' && row.approval.step && (
                            <>, step {row.approval.step} of {row.approval.total}</>
                          )}
                        </ItemDescription>
                      </ItemContent>
                      <ItemActions>
                        <SubmissionStatusBadge status={row.status} />
                      </ItemActions>
                    </button>
                  </Item>
                ))}
                {!rows.length && <p className="text-sm text-muted-foreground">No submissions match these filters.</p>}
              </ItemGroup>
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span className="tabular-nums">
                  Showing {rows.length} of {total}
                </span>
                {list.hasNextPage && (
                  <Button variant="outline" size="sm" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
                    Load older
                  </Button>
                )}
              </div>
              {!canEdit && (
                <p className="text-sm text-muted-foreground">You can view submissions. Ask an owner to change status.</p>
              )}
            </>
          )}
        </>
      )}
      <SubmissionSheet
        id={openId}
        onClose={() => setOpenId(null)}
        onPrev={idx > 0 ? () => setOpenId(rows[idx - 1].id) : undefined}
        onNext={idx >= 0 && idx < rows.length - 1 ? () => setOpenId(rows[idx + 1].id) : undefined}
      />
      {exporting && (
        <ExportDialog
          key={JSON.stringify(exporting)}
          open={exportOpen}
          onOpenChange={setExportOpen}
          formId={form.id}
          filters={exporting}
          count={exporting.ids ? exporting.ids.length : total}
          sensitive={sensitive}
          canSeeSensitive={canEdit}
        />
      )}
    </PageContainer>
  )
}

/** "Step 1 of 2" next to the status while an approval runs (APPROVALS-SCREENS 3.1). */
function ApprovalStep({ row }: { row: SubmissionSummary }) {
  const a = row.approval
  if (a?.state !== 'pending' || !a.step) return null
  return (
    <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
      Step {a.step} of {a.total}
    </span>
  )
}
