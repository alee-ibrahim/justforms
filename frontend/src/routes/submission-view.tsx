/**
 * One submission laid out as the filled form, on its own linkable page
 * (docs/ux/SUBMISSIONS-VIEWER-SCREENS.md 1): header with reference, status and actions,
 * Previous / Next through the list it was opened from, the themed sheet, and Details / Activity.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { ChevronLeftIcon, ChevronRightIcon, MessageSquareIcon, PrinterIcon, SearchXIcon } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { flushSync } from 'react-dom'

import { useFormSummary } from '@/components/builder/form-context'
import { ActivityList, CommentBox } from '@/components/submissions/activity'
import { useLogic } from '@/components/submissions/answer-logic'
import { Answers } from '@/components/submissions/answers'
import { ApprovalBlock, ApprovalDecision } from '@/components/submissions/approval-block'
import { decidableStep } from '@/components/submissions/approval-lib'
import { AuditDetails } from '@/components/submissions/audit-details'
import { IntegrityBadge, PdfButton } from '@/components/submissions/integrity'
import {
  listFilters,
  listSearch,
  neighbours,
  rememberLastViewed,
  useSubmissionList,
} from '@/components/submissions/list-query'
import type { SubmissionsSearch } from '@/components/submissions/search'
import { SubmissionStatusBadge } from '@/components/submissions/status-badge'
import { StatusControl } from '@/components/submissions/status-control'
import { HiddenValues, ImportedNote, RespondentLine } from '@/components/submissions/viewer-parts'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import { DirectionProvider } from '@/components/ui/direction'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldLabel } from '@/components/ui/field'
import { Kbd } from '@/components/ui/kbd'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, api, type SubmissionDetail } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { formThemeQuery, retryUnlessMissing } from '@/lib/queries'
import { canvasMode, themeScope, useFontLinks } from '@/lib/theme'
import { useDelayed } from '@/lib/use-delayed'
import { cn } from '@/lib/utils'
import { legibleAccent } from '@/renderer/accent'
import { FormHeader } from '@/renderer/form-view'
import { contentProps, formLanguage } from '@/schema/language'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const reference = (seq: number) => `#${String(seq).padStart(4, '0')}`

function useMedia(query: string): boolean {
  const [on, setOn] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const m = window.matchMedia(query)
    const change = () => setOn(m.matches)
    m.addEventListener('change', change)
    return () => m.removeEventListener('change', change)
  }, [query])
  return on
}

/** While printing: the studio's dark mode is lifted so the page prints on white. */
function usePrinting(): boolean {
  const [printing, setPrinting] = useState(false)
  useEffect(() => {
    const root = document.documentElement
    let wasDark = false
    const before = () => {
      wasDark = root.classList.contains('dark')
      root.classList.remove('dark')
      flushSync(() => setPrinting(true))
    }
    const after = () => {
      if (wasDark) root.classList.add('dark')
      setPrinting(false)
    }
    window.addEventListener('beforeprint', before)
    window.addEventListener('afterprint', after)
    return () => {
      window.removeEventListener('beforeprint', before)
      window.removeEventListener('afterprint', after)
    }
  }, [])
  return printing
}

/** Resolves the address (reference number, or an id from older links) to the submission. */
function useSubmission(formId: string, ref: string) {
  const queryClient = useQueryClient()
  const seq = /^\d{1,9}$/.test(ref) ? Number(ref) : null
  const byRef = useQuery({
    queryKey: ['submission', 'ref', formId, seq],
    queryFn: async () => {
      const d = await api.getSubmissionByReference(formId, seq!)
      queryClient.setQueryData(['submission', d.id], d)
      return d.id
    },
    enabled: seq !== null && seq > 0,
    retry: retryUnlessMissing,
  })
  const id = seq !== null ? (byRef.data ?? null) : UUID.test(ref) ? ref : null
  const detail = useQuery({
    queryKey: ['submission', id],
    queryFn: () => api.getSubmission(id!),
    enabled: id !== null,
    staleTime: 5000,
    retry: retryUnlessMissing,
    // Poll while the signed PDF is being made.
    refetchInterval: (q) => (q.state.data?.pdfStatus === 'pending' ? 2000 : false),
  })
  const error = byRef.error ?? detail.error
  const missing =
    (seq === null && !UUID.test(ref)) || (seq !== null && seq <= 0) || (error instanceof ApiError && [404, 422].includes(error.status))
  return { d: detail.data, missing, error: missing ? null : error, retry: () => void (byRef.error ? byRef.refetch() : detail.refetch()) }
}

export function SubmissionViewPage() {
  const form = useFormSummary()
  const { ref } = useParams({ strict: false }) as { ref: string }
  const search = useSearch({ strict: false }) as SubmissionsSearch
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { d, missing, error, retry } = useSubmission(form.id, ref)
  const wide = useMedia('(min-width: 64rem)')
  const printing = usePrinting()
  const [tab, setTab] = useState('answers')
  const [showSkipped, setShowSkipped] = useState(false)
  const [announce, setAnnounce] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)
  const back = listSearch(search)

  // An id from an older link: show the reference in the address bar instead.
  useEffect(() => {
    if (d && UUID.test(ref))
      void navigate({
        to: '/forms/$formId/submissions/$ref',
        params: { formId: form.id, ref: String(d.seq) },
        search: back,
        replace: true,
      } as never)
  }, [d, ref, form.id, navigate, back])
  useEffect(() => {
    if (d) rememberLastViewed(form.id, d.id)
  }, [d, form.id])

  // The list it was opened from: the same query (and cache) as the Submissions page.
  const filters = useMemo(() => listFilters(search, search.status ?? 'all'), [search])
  const { list, rows, total } = useSubmissionList(form.id, filters, form.currentVersion !== null)
  const { index: idx, prev, next: nextRow, atEnd } = neighbours(rows, d?.id)
  // Not among the loaded rows yet (opened from a link or an older page): load a few more pages.
  const pagesLoaded = list.data?.pages.length ?? 0
  useEffect(() => {
    if (d && idx === -1 && list.hasNextPage && !list.isFetchingNextPage && pagesLoaded < 10) void list.fetchNextPage()
  }, [d, idx, list, pagesLoaded])

  const go = useCallback(
    (seq: number) => {
      void navigate({
        to: '/forms/$formId/submissions/$ref',
        params: { formId: form.id, ref: String(seq) },
        search: back,
        replace: true,
      } as never)
      setAnnounce(reference(seq))
      window.scrollTo({ top: 0 })
      window.setTimeout(() => heading.current?.focus({ preventScroll: true }), 0)
    },
    [navigate, form.id, back],
  )
  const canNext = !!nextRow || (atEnd && !!list.hasNextPage)
  const onPrev = useCallback(() => prev && go(prev.seq), [prev, go])
  const onNext = useCallback(async () => {
    if (nextRow) return go(nextRow.seq)
    if (!canNext) return
    const res = await list.fetchNextPage()
    const more = res.data?.pages.flatMap((p) => p.items) ?? []
    const after = more[idx + 1]
    if (after) go(after.seq)
  }, [nextRow, canNext, list, idx, go])
  const toList = useCallback(
    () => void navigate({ to: '/forms/$formId/submissions', params: { formId: form.id }, search: back } as never),
    [navigate, form.id, back],
  )

  // J / K move through the list, Esc goes back to it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable) return
      if (document.querySelector('[role=dialog], [role=menu], [role=listbox]')) return
      if (e.key === 'j') void onNext()
      else if (e.key === 'k') onPrev()
      else if (e.key === 'Escape') toList()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onNext, onPrev, toList])

  const integrity = useQuery({
    queryKey: ['submission', d?.id, 'verify'],
    queryFn: () => api.verifySubmission(d!.id),
    enabled: !!d,
  })
  const theme = useQuery(formThemeQuery(form.id)).data?.preview
  useFontLinks(theme?.fonts)

  if (missing)
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
        <Empty className="border bg-card">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <SearchXIcon />
            </EmptyMedia>
            <EmptyTitle>Submission not found</EmptyTitle>
            <EmptyDescription>It was deleted, or you don't have access to it.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" asChild>
              <Link to="/forms/$formId/submissions" params={{ formId: form.id }} search={back as never}>
                Back to submissions
              </Link>
            </Button>
          </EmptyContent>
        </Empty>
      </main>
    )

  const position = d && idx >= 0 && total > 0 ? `${idx + 1} of ${total}` : null
  const reveal = d?.canEdit
    ? async (fieldId: string, row?: number) => {
        const res = await api.reveal(d.id, fieldId, row)
        void queryClient.invalidateQueries({ queryKey: ['submission', d.id] })
        return res.value
      }
    : undefined

  const header = (
    <header className="flex flex-col gap-3 border-b bg-card px-4 py-3 sm:px-6 print:border-0 print:px-0">
      <div className="flex items-center gap-2 print:hidden">
        <Button variant="ghost" size="sm" className="-ms-2" asChild>
          <Link to="/forms/$formId/submissions" params={{ formId: form.id }} search={back as never}>
            <ChevronLeftIcon />
            Submissions
          </Link>
        </Button>
        <div className="ms-auto flex items-center gap-3">
          {position && <span className="text-sm text-muted-foreground tabular-nums max-sm:hidden">{position}</span>}
          <ButtonGroup aria-label="Move through submissions">
            <NavButton label="Previous" kbd="K" onClick={onPrev} disabled={!prev} compact={!wide}>
              <ChevronLeftIcon />
            </NavButton>
            <NavButton label="Next" kbd="J" onClick={() => void onNext()} disabled={!canNext} compact={!wide} end>
              <ChevronRightIcon />
            </NavButton>
          </ButtonGroup>
        </div>
      </div>
      {d ? (
        <>
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold tracking-tight tabular-nums outline-none">
                {reference(d.seq)}
              </h1>
              <SubmissionStatusBadge status={d.status} />
              {d.approval?.state === 'pending' && d.approval.step && (
                <span className="text-sm text-muted-foreground tabular-nums">
                  Step {d.approval.step} of {d.approval.total}
                </span>
              )}
            </div>
            <p className="min-w-0 text-sm text-muted-foreground">
              <span className="tabular-nums">Submitted {formatDateTime(d.submittedAt)}</span>
              {d.respondentEmail && <RespondentLine d={d} />}, <span className="tabular-nums">version {d.version}</span>
              {d.source === 'jotform_import' && (
                <>
                  , <span className="tabular-nums">imported {formatDateTime(d.createdAt)}</span>
                </>
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 print:hidden">
            {decidableStep(d) ? (
              <ApprovalDecision d={d} />
            ) : d.canEdit ? (
              <StatusControl d={d} />
            ) : (
              <p className="self-center text-sm text-muted-foreground">You can view submissions. Ask an owner to change status.</p>
            )}
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <PrinterIcon />
              Print
            </Button>
            <PdfButton d={d} />
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setTab('activity')
                window.setTimeout(() => document.getElementById('comment')?.focus(), 0)
              }}
            >
              <MessageSquareIcon />
              Comment
            </Button>
            {integrity.data && (
              <span className="self-center">
                <IntegrityBadge result={integrity.data} />
              </span>
            )}
          </div>
          {integrity.data && !integrity.data.ok && (
            <Alert variant="destructive">
              <AlertDescription>
                This submission changed outside JustForms after it was submitted. Download the PDF and contact your administrator.
              </AlertDescription>
            </Alert>
          )}
        </>
      ) : (
        <HeaderSkeleton />
      )}
      {!!error && (
        <Alert variant="destructive" className="print:hidden">
          <AlertDescription className="flex flex-wrap items-center gap-3">
            Couldn't load this submission. Check your connection.
            <Button variant="outline" size="sm" onClick={retry}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}
    </header>
  )

  const details = d ? (
    <div className="flex flex-col gap-6">
      <ImportedNote d={d} />
      <ApprovalBlock d={d} />
      <HiddenValues d={d} />
      <AuditDetails d={d} />
    </div>
  ) : (
    <Skeleton className="h-32" />
  )
  const activity = d ? (
    <div className="flex flex-col gap-4">
      <CommentBox id={d.id} />
      <ActivityList events={d.events} />
    </div>
  ) : (
    <Skeleton className="h-24" />
  )
  const sheet = <Sheet d={d} theme={theme} printing={printing} reveal={reveal} showSkipped={showSkipped} onShowSkipped={setShowSkipped} />
  const activityLabel = (
    <>
      Activity
      {d && (
        <Badge variant="secondary" className="tabular-nums">
          {d.events.length}
        </Badge>
      )}
    </>
  )

  return (
    <main data-print-root className="flex min-h-0 flex-1 flex-col">
      {header}
      {wide ? (
        <div className="flex flex-1">
          {sheet}
          <aside className="w-[22rem] shrink-0 border-s bg-card print:hidden" aria-label="Details and activity">
            <Tabs
              value={tab === 'answers' ? 'details' : tab}
              onValueChange={setTab}
              className="sticky top-(--studio-top) max-h-[calc(100dvh-var(--studio-top))] gap-0 overflow-y-auto"
            >
              <TabsList className="mx-4 mt-3">
                <TabsTrigger value="details">Details</TabsTrigger>
                <TabsTrigger value="activity" className="gap-1.5">
                  {activityLabel}
                </TabsTrigger>
              </TabsList>
              <TabsContent value="details" className="p-4">
                {details}
              </TabsContent>
              <TabsContent value="activity" className="p-4">
                {activity}
              </TabsContent>
            </Tabs>
          </aside>
        </div>
      ) : (
        <Tabs value={tab} onValueChange={setTab} className="flex-1 gap-0">
          <TabsList className="mx-4 mt-3 print:hidden sm:mx-6">
            <TabsTrigger value="answers">Answers</TabsTrigger>
            <TabsTrigger value="details">Details</TabsTrigger>
            <TabsTrigger value="activity" className="gap-1.5">
              {activityLabel}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="answers" className="flex flex-col">
            {sheet}
          </TabsContent>
          <TabsContent value="details" className="p-4 sm:px-6">
            {details}
          </TabsContent>
          <TabsContent value="activity" className="p-4 sm:px-6">
            {activity}
          </TabsContent>
        </Tabs>
      )}
      <div className="sr-only" aria-live="polite">
        {announce}
      </div>
    </main>
  )
}

function NavButton({
  label,
  kbd,
  onClick,
  disabled,
  compact,
  end,
  children,
}: {
  label: string
  kbd: string
  onClick: () => void
  disabled: boolean
  compact: boolean
  end?: boolean
  children: ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="outline"
          size={compact ? 'icon-sm' : 'sm'}
          onClick={onClick}
          disabled={disabled}
          aria-label={compact ? label : undefined}
          aria-keyshortcuts={kbd}
        >
          {!end && children}
          {!compact && label}
          {end && children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        {label} <Kbd>{kbd}</Kbd>
      </TooltipContent>
    </Tooltip>
  )
}

function HeaderSkeleton() {
  const show = useDelayed(true)
  if (!show) return <div className="h-20" />
  return (
    <div className="flex flex-col gap-2">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-4 w-72 max-w-full" />
      <Skeleton className="h-8 w-80 max-w-full" />
    </div>
  )
}

/** The answers on the form's own sheet, in the form's theme, language and direction. */
function Sheet({
  d,
  theme,
  printing,
  reveal,
  showSkipped,
  onShowSkipped,
}: {
  d: SubmissionDetail | undefined
  theme: Parameters<typeof themeScope>[0]
  printing: boolean
  reveal?: (fieldId: string, row?: number) => Promise<string>
  showSkipped: boolean
  onShowSkipped: (on: boolean) => void
}) {
  const scope = themeScope(theme, printing ? 'light' : canvasMode(theme))
  const show = useDelayed(!d)
  const accent = d ? legibleAccent(d.schema.settings.theme?.accent) : null
  return (
    <div
      {...scope}
      data-accent={accent ? '' : undefined}
      style={{ ...scope.style, ...(accent ? { '--form-accent': accent } : {}) } as React.CSSProperties}
      className={cn(
        scope.className,
        'flex min-w-0 flex-1 flex-col gap-3 bg-background text-foreground sm:px-6 sm:py-6 print:bg-transparent print:p-0',
      )}
    >
      {d ? (
        <>
          <SkippedSwitch d={d} on={showSkipped} onChange={onShowSkipped} />
          <SheetBody d={d} theme={theme} reveal={reveal} showSkipped={showSkipped} />
        </>
      ) : (
        show && (
          <div className="mx-auto flex w-full max-w-[40rem] flex-col gap-8 bg-card p-5 sm:rounded-md sm:border md:p-10">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="flex flex-col gap-2">
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-8" />
              </div>
            ))}
          </div>
        )
      )}
    </div>
  )
}

function SkippedSwitch({ d, on, onChange }: { d: SubmissionDetail; on: boolean; onChange: (on: boolean) => void }) {
  const { skippedCount } = useLogic(d.schema, d.data)
  if (!skippedCount) return null
  return (
    <div className="mx-auto flex w-full max-w-[var(--df-page-width,40rem)] px-4 pt-3 sm:px-0 sm:pt-0 print:hidden">
      <Field orientation="horizontal" className="w-auto">
        <Switch id="show-skipped" checked={on} onCheckedChange={onChange} />
        <FieldLabel htmlFor="show-skipped" className="font-normal">
          <span className="tabular-nums">Show skipped questions ({skippedCount})</span>
        </FieldLabel>
      </Field>
    </div>
  )
}

function SheetBody({
  d,
  theme,
  reveal,
  showSkipped,
}: {
  d: SubmissionDetail
  theme: Parameters<typeof themeScope>[0]
  reveal?: (fieldId: string, row?: number) => Promise<string>
  showSkipped: boolean
}) {
  const language = formLanguage(d.schema)
  const options = theme?.options
  return (
    <DirectionProvider dir={contentProps(language).dir}>
      <article
        {...contentProps(language)}
        aria-label="Answers"
        className="@container mx-auto flex w-full max-w-[var(--df-page-width,40rem)] flex-col gap-6 bg-card p-5 text-base sm:rounded-md sm:border md:p-10 print:max-w-none print:border-0 print:p-0"
      >
        <FormHeader form={d.schema} theme={options ? { ...options, headerImageUrl: null } : undefined} description={null} />
        <Answers
          form={d.schema}
          data={d.data}
          signatures={d.signatures}
          importedFiles={d.importedFiles}
          reveal={reveal}
          showSkipped={showSkipped}
        />
      </article>
    </DirectionProvider>
  )
}
