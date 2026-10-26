/**
 * Submissions › Insights (INSIGHTS-SCREENS): "Ask your submissions" (when the install has an
 * AI provider) and a summary of every question under the same filters as the list. A bar
 * opens the Submissions list filtered to its answers. Loaded lazily (it carries the charts).
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { ChartColumnIcon, InboxIcon } from 'lucide-react'
import { useMemo } from 'react'

import { useFormSummary } from '@/components/builder/form-context'
import { insightsApi, type QuestionSummary } from '@/components/insights/api'
import { AskEntry } from '@/components/insights/ask-entry'
import { ConditionChip, SubmissionsTabs } from '@/components/insights/nav'
import { QuestionCard } from '@/components/insights/question-card'
import { PageContainer } from '@/components/layout/page'
import { AddFilter, DateRangeFilter, FilterChips, VersionFilter } from '@/components/submissions/filters'
import { STATUS_LABELS } from '@/components/submissions/labels'
import { listFilters, listSearch } from '@/components/submissions/list-query'
import type { SubmissionsSearch, Tab } from '@/components/submissions/search'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import type { Condition } from '@/lib/api'
import { versionQuery, versionsQuery } from '@/lib/queries'
import { useDelayed } from '@/lib/use-delayed'
import { buildIndex } from '@/logic/form-index'
import type { FieldElement } from '@/schema'
import { formLanguage } from '@/schema/language'

const TABS: Tab[] = ['all', 'new', 'in_review', 'approved', 'rejected']

function Grid({
  questions,
  of,
  unit,
  language,
  formId,
  multipleVersions,
  onOpen,
}: {
  questions: QuestionSummary[]
  of: number
  unit: 'submissions' | 'rows'
  language: string
  formId: string
  multipleVersions: boolean
  onOpen: (where: Condition[], label: string) => void
}) {
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      {questions.map((q) => (
        <QuestionCard
          key={q.key}
          q={q}
          of={of}
          unit={unit}
          language={language}
          formId={formId}
          multipleVersions={multipleVersions}
          onOpen={onOpen}
        />
      ))}
    </div>
  )
}

export function FormInsightsPage() {
  const form = useFormSummary()
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
  const tab: Tab = search.status ?? 'all'
  const filters = useMemo(() => listFilters(search, tab), [search, tab])
  const live = useQuery(versionQuery(form.id, form.currentVersion))
  const versions = useQuery({ ...versionsQuery(form.id), enabled: form.currentVersion !== null })
  const summary = useQuery({
    queryKey: ['insights', form.id, filters],
    queryFn: () => insightsApi.summary(form.id, filters),
    enabled: form.currentVersion !== null,
    placeholderData: keepPreviousData,
  })
  const showSkeleton = useDelayed(summary.isPending)
  const schema = live.data?.schema
  const language = schema ? formLanguage(schema) : 'en'
  const fields = useMemo(
    () =>
      schema
        ? [...buildIndex(schema).elements.values()]
            .filter((i) => i.repeaterId === null && i.kind === 'field')
            .map((i) => i.element as FieldElement)
            .filter((f) => f.type !== 'hidden')
        : [],
    [schema],
  )
  const fieldFilters = search.fields ?? []
  const conditions = !!(search.where?.length || search.whereAny?.length)
  const filtered = !!(search.from || search.to || search.version || fieldFilters.length || conditions || search.q)
  const multipleVersions = (versions.data?.length ?? 0) > 1
  const data = summary.data

  const openList = (where: Condition[], label: string) =>
    void navigate({
      to: '/forms/$formId/submissions',
      params: { formId: form.id },
      search: {
        ...listSearch(search),
        status: tab,
        // An Insights bar replaces earlier conditions; question filters and dates stay.
        where,
        whereAny: undefined,
        whereLabel: label,
      },
    } as never)

  const clearFilters = (status?: Tab) =>
    setSearch({
      ...(status ? { status } : {}),
      q: undefined,
      from: undefined,
      to: undefined,
      version: undefined,
      fields: undefined,
      where: undefined,
      whereAny: undefined,
      whereLabel: undefined,
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

  return (
    <PageContainer>
      <h1 className="text-xl font-semibold tracking-tight">Submissions</h1>
      <SubmissionsTabs formId={form.id} current="insights" search={listSearch(search)} />
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={tab} onValueChange={(v) => setSearch({ status: v as Tab })}>
            <SelectTrigger size="sm" aria-label="Status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TABS.map((t) => (
                <SelectItem key={t} value={t}>
                  {t === 'all' ? 'All statuses' : STATUS_LABELS[t]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <AddFilter fields={fields} language={language} onAdd={(f) => setSearch({ fields: [...fieldFilters, f] })} />
          <DateRangeFilter from={search.from} to={search.to} onChange={(r) => setSearch(r)} />
          <VersionFilter
            versions={(versions.data ?? []).map((v) => v.version).sort((a, b) => b - a)}
            value={search.version}
            onChange={(version) => setSearch({ version })}
          />
        </div>
        {filtered && (
          <div className="flex flex-wrap items-center gap-2">
            {search.q && (
              <ConditionChip label={`Answers contain “${search.q}”`} onRemove={() => setSearch({ q: undefined })} />
            )}
            <FilterChips
              filters={fieldFilters}
              fields={fields}
              language={language}
              onRemove={(i) => setSearch({ fields: fieldFilters.filter((_, j) => j !== i) })}
            />
            {conditions && (
              <ConditionChip
                label={search.whereLabel}
                onRemove={() => setSearch({ where: undefined, whereAny: undefined, whereLabel: undefined })}
              />
            )}
            <Button variant="link" size="sm" onClick={() => clearFilters()}>
              Clear filters
            </Button>
          </div>
        )}
      </div>

      <AskEntry schema={schema} language={language} />

      {summary.isError && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center gap-3">
            Couldn't load the summary. Check your connection.
            <Button variant="outline" size="sm" onClick={() => void summary.refetch()}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {summary.isPending ? (
        showSkeleton && (
          <div className="grid gap-4 lg:grid-cols-2">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-56" />
            ))}
          </div>
        )
      ) : data && data.total === 0 ? (
        <Empty className="border bg-card">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ChartColumnIcon />
            </EmptyMedia>
            <EmptyTitle>{filtered || tab !== 'all' ? 'No submissions match these filters' : 'No submissions yet'}</EmptyTitle>
            <EmptyDescription>
              {filtered || tab !== 'all'
                ? 'Change or clear the filters to see a summary.'
                : 'A summary of every question appears here once people respond.'}
            </EmptyDescription>
          </EmptyHeader>
          {(filtered || tab !== 'all') && (
            <EmptyContent>
              <Button variant="outline" onClick={() => clearFilters('all')}>
                Clear filters
              </Button>
            </EmptyContent>
          )}
        </Empty>
      ) : (
        data && (
          <section aria-labelledby="summary-title" className="flex flex-col gap-4">
            <h2 id="summary-title" className="text-base font-medium">
              Summary of <span className="tabular-nums">{data.total}</span> submission{data.total === 1 ? '' : 's'}
              {summary.isFetching && <span className="sr-only"> (updating)</span>}
            </h2>
            <Grid
              questions={data.questions}
              of={data.total}
              unit="submissions"
              language={data.language}
              formId={form.id}
              multipleVersions={multipleVersions}
              onOpen={openList}
            />
            {data.repeaters.map((r) => (
              <section key={r.key} aria-labelledby={`rep-${r.key}`} className="flex flex-col gap-3 border-t pt-4">
                <div className="flex flex-col gap-0.5">
                  <h2 id={`rep-${r.key}`} className="text-base font-medium">
                    <bdi dir="auto" lang={data.language}>
                      {r.label}
                    </bdi>
                  </h2>
                  <p className="text-sm text-muted-foreground tabular-nums">
                    {r.rows} row{r.rows === 1 ? '' : 's'} in {r.submissions} submission{r.submissions === 1 ? '' : 's'}
                    {r.submissions ? `, ${r.avgRows} on average` : ''}
                    {r.mapped ? '. Older versions’ questions are counted as rows.' : ''}
                  </p>
                </div>
                <Grid
                  questions={r.questions}
                  of={r.rows}
                  unit="rows"
                  language={data.language}
                  formId={form.id}
                  multipleVersions={multipleVersions}
                  onOpen={openList}
                />
              </section>
            ))}
          </section>
        )
      )}
    </PageContainer>
  )
}
