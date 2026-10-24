/**
 * Import responses from a Jotform export (JOTFORM-IMPORT-SCREENS 3): upload, match columns
 * to questions, check the first rows, import.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CheckIcon, TriangleAlertIcon } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useFormSummary } from '@/components/builder/form-context'
import { PageContainer } from '@/components/layout/page'
import { STATUS_LABELS } from '@/components/submissions/labels'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldError, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item'
import { NativeSelect, NativeSelectOptGroup, NativeSelectOption } from '@/components/ui/native-select'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { SubmissionStatus } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import {
  IGNORE,
  importErrorText,
  importsApi,
  PROBLEM_TEXT,
  type DateOrder,
  type MappingPreview,
  type SubmissionsImport,
} from '@/lib/imports'

const TYPE_LABELS: Record<string, string> = {
  short_text: 'short text',
  long_text: 'long text',
  single_choice: 'choice',
  multi_choice: 'checkboxes',
  yes_no: 'yes/no',
}

function StepHeading({ n, children }: { n: number; children: string }) {
  const ref = useRef<HTMLHeadingElement>(null)
  useEffect(() => ref.current?.focus(), [])
  return (
    <h2 ref={ref} tabIndex={-1} className="text-lg font-semibold tracking-tight outline-none">
      Step {n} of 3: {children}
    </h2>
  )
}

function UploadStep({ formId, version, onUploaded }: { formId: string; version: number; onUploaded: (i: SubmissionsImport) => void }) {
  const upload = useMutation({ mutationFn: (file: File) => importsApi.uploadSubmissions(formId, file), onSuccess: onUploaded })
  const history = useQuery({ queryKey: ['imports', formId], queryFn: () => importsApi.listSubmissionImports(formId) })
  return (
    <>
      <StepHeading n={1}>Upload the export</StepHeading>
      <Card>
        <CardContent className="flex flex-col gap-4">
          <Field data-invalid={upload.isError ? true : undefined}>
            <FieldLabel htmlFor="jf-export">Jotform export (.xlsx or .csv)</FieldLabel>
            <Input
              id="jf-export"
              type="file"
              accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              disabled={upload.isPending}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) upload.mutate(file)
              }}
            />
            <FieldDescription>
              In Jotform open the form's Tables, then Download all, as Excel or CSV. Up to 50 MB.
            </FieldDescription>
            {upload.isError && <FieldError>{importErrorText(upload.error)}</FieldError>}
          </Field>
          {upload.isPending && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
              <Spinner /> Reading the file…
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            Responses go into version <span className="tabular-nums">{version}</span>, the published version.
          </p>
        </CardContent>
      </Card>
      {history.data && history.data.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium">Earlier imports</h2>
          <ItemGroup className="gap-1">
            {history.data.map((h) => (
              <Item key={h.id} size="xs" variant="outline">
                <ItemContent className="min-w-0">
                  <ItemTitle className="min-w-0 break-all">{h.filename}</ItemTitle>
                  <ItemDescription>
                    {h.status === 'done'
                      ? `${h.report.imported ?? 0} imported`
                      : h.status === 'failed'
                        ? 'Failed, nothing added'
                        : 'Importing'}
                    , {formatDateTime(h.createdAt)}
                  </ItemDescription>
                </ItemContent>
              </Item>
            ))}
          </ItemGroup>
        </section>
      )}
    </>
  )
}

function MapStep({
  imp,
  columns,
  setColumns,
  dateOrder,
  setDateOrder,
  status,
  setStatus,
  onBack,
  onPreview,
}: {
  imp: SubmissionsImport
  columns: string[]
  setColumns: (c: string[]) => void
  dateOrder: DateOrder
  setDateOrder: (d: DateOrder) => void
  status: SubmissionStatus
  setStatus: (s: SubmissionStatus) => void
  onBack: () => void
  onPreview: () => void
}) {
  const questions = imp.targets.filter((t) => t.type !== 'meta')
  // Repeated labels ("Full Name" for each contact) are told apart by the question key.
  const labelCount = new Map<string, number>()
  for (const t of questions) labelCount.set(t.label, (labelCount.get(t.label) ?? 0) + 1)
  const optionText = (t: (typeof questions)[number]) =>
    (labelCount.get(t.label) ?? 0) > 1
      ? `${t.label} (${t.value.slice('field:'.length)})`
      : `${t.label} (${TYPE_LABELS[t.type] ?? t.type.replace('_', ' ')})`
  const details = imp.targets.filter((t) => t.type === 'meta')
  const labelOf = useMemo(() => new Map(imp.targets.map((t) => [t.value, t.label])), [imp.targets])
  const counts = new Map<string, number>()
  for (const c of columns) if (c !== IGNORE) counts.set(c, (counts.get(c) ?? 0) + 1)
  const duplicates = [...counts].filter(([, n]) => n > 1).map(([t]) => t)
  const hasId = columns.includes('meta:external_id')
  const anyMapped = columns.some((c) => c.startsWith('field:'))
  const linkTypes = new Set(imp.targets.filter((t) => t.type === 'file' || t.type === 'signature').map((t) => t.value))
  const hasLinks = columns.some((c) => linkTypes.has(c))

  const select = (i: number) => {
    const value = columns[i]
    const dup = duplicates.includes(value)
    return (
      <Field data-invalid={dup ? true : undefined} className="gap-1">
        <NativeSelect
          aria-label={`Import "${imp.columns[i].header}" into`}
          value={value}
          aria-invalid={dup || undefined}
          className="w-full"
          onChange={(e) => {
            const next = [...columns]
            next[i] = e.target.value
            setColumns(next)
          }}
        >
          <NativeSelectOption value={IGNORE}>Don't import</NativeSelectOption>
          <NativeSelectOptGroup label="Questions">
            {questions.map((t) => (
              <NativeSelectOption key={t.value} value={t.value}>
                {optionText(t)}
                {counts.has(t.value) && t.value !== value ? ' (already used)' : ''}
              </NativeSelectOption>
            ))}
          </NativeSelectOptGroup>
          <NativeSelectOptGroup label="Details">
            {details.map((t) => (
              <NativeSelectOption key={t.value} value={t.value}>
                {t.label}
              </NativeSelectOption>
            ))}
          </NativeSelectOptGroup>
        </NativeSelect>
        {dup && <FieldError>Two columns import into {labelOf.get(value)}. Choose one.</FieldError>}
      </Field>
    )
  }

  return (
    <>
      <StepHeading n={2}>Match columns</StepHeading>
      <p className="-mt-4 text-sm text-muted-foreground">
        <bdi dir="auto" className="break-all">{imp.filename}</bdi>, <span className="tabular-nums">{imp.rowCount}</span>{' '}
        {imp.rowCount === 1 ? 'row' : 'rows'}. We matched columns to questions by their names; check them.
      </p>
      {!hasId && (
        <Alert>
          <TriangleAlertIcon />
          <AlertDescription>
            No column holds the Jotform submission ID. Importing the same file twice will add the rows twice.
          </AlertDescription>
        </Alert>
      )}
      <Card className="py-0">
        <CardContent className="px-0">
          <Table className="max-md:hidden">
            <TableHeader>
              <TableRow>
                <TableHead className="ps-4">Column in the file</TableHead>
                <TableHead>Examples</TableHead>
                <TableHead className="w-[22rem] pe-4">Import into</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {imp.columns.map((c, i) => (
                <TableRow key={c.index}>
                  <TableCell className="ps-4 align-top font-medium whitespace-normal">
                    <bdi dir="auto">{c.header || `Column ${i + 1}`}</bdi>
                  </TableCell>
                  <TableCell className="max-w-64 align-top text-muted-foreground">
                    <span className="block truncate">
                      <bdi dir="auto">{c.samples.join(', ') || '-'}</bdi>
                    </span>
                  </TableCell>
                  <TableCell className="pe-4 align-top">{select(i)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <ItemGroup className="md:hidden">
            {imp.columns.map((c, i) => (
              <Item key={c.index} className="flex-col items-stretch rounded-none border-b last:border-b-0">
                <ItemContent className="min-w-0">
                  <ItemTitle className="break-words">
                    <bdi dir="auto">{c.header || `Column ${i + 1}`}</bdi>
                  </ItemTitle>
                  <ItemDescription className="truncate">
                    <bdi dir="auto">{c.samples.join(', ') || '-'}</bdi>
                  </ItemDescription>
                </ItemContent>
                {select(i)}
              </Item>
            ))}
          </ItemGroup>
        </CardContent>
      </Card>
      {hasLinks && (
        <p className="text-sm text-muted-foreground">
          Files and signatures stay on Jotform. JustForms keeps their links on each submission; Jotform links usually
          need you to be signed in to Jotform.
        </p>
      )}
      <div className="grid gap-6 sm:grid-cols-2">
        <FieldSet>
          <FieldLegend variant="label">Dates like 03/04/2025 are</FieldLegend>
          <RadioGroup value={dateOrder} onValueChange={(v) => setDateOrder(v as DateOrder)} className="flex flex-wrap gap-x-6 gap-y-2">
            {(
              [
                ['auto', 'Detect'],
                ['mdy', 'Month first'],
                ['dmy', 'Day first'],
              ] as const
            ).map(([v, label]) => (
              <Field key={v} orientation="horizontal" className="w-auto">
                <RadioGroupItem value={v} id={`date-${v}`} />
                <FieldLabel htmlFor={`date-${v}`} className="font-normal">
                  {label}
                </FieldLabel>
              </Field>
            ))}
          </RadioGroup>
        </FieldSet>
        <Field>
          <FieldLabel htmlFor="import-status">New submissions get the status</FieldLabel>
          <NativeSelect id="import-status" value={status} onChange={(e) => setStatus(e.target.value as SubmissionStatus)}>
            {(Object.keys(STATUS_LABELS) as SubmissionStatus[]).map((s) => (
              <NativeSelectOption key={s} value={s}>
                {STATUS_LABELS[s]}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </Field>
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button onClick={onPreview} disabled={duplicates.length > 0 || !anyMapped}>
          Preview
        </Button>
      </div>
    </>
  )
}

function PreviewStep({
  imp,
  columns,
  preview,
  onBack,
  onImport,
  starting,
  error,
}: {
  imp: SubmissionsImport
  columns: string[]
  preview: MappingPreview
  onBack: () => void
  onImport: () => void
  starting: boolean
  error: unknown
}) {
  const labelOf = new Map(imp.targets.map((t) => [t.value, t.label]))
  const shown = columns.map((c, i) => ({ c, i })).filter(({ c }) => c !== IGNORE)
  return (
    <>
      <StepHeading n={3}>Check and import</StepHeading>
      <p className="-mt-4 text-sm text-muted-foreground">
        The first {preview.rows.length} {preview.rows.length === 1 ? 'row' : 'rows'}, as they will be imported.
      </p>
      <Card className="py-0">
        <ScrollArea className="w-full">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="ps-4">Row</TableHead>
                {shown.map(({ c, i }) => (
                  <TableHead key={i} className="max-w-56">
                    <bdi dir="auto" className="block truncate">
                      {labelOf.get(c) ?? c}
                    </bdi>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.rows.map((r) => {
                const cells = new Map(r.cells.map((cell) => [cell.column, cell]))
                return (
                  <TableRow key={r.row}>
                    <TableCell className="ps-4 tabular-nums text-muted-foreground">{r.row}</TableCell>
                    {shown.map(({ i }) => {
                      const cell = cells.get(i)
                      return (
                        <TableCell key={i} className="max-w-56">
                          {cell?.problem ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="inline-flex items-center gap-1 text-destructive" tabIndex={0}>
                                  <TriangleAlertIcon className="size-3.5" aria-hidden />
                                  Can't import
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>{PROBLEM_TEXT[cell.problem] ?? cell.problem}</TooltipContent>
                            </Tooltip>
                          ) : cell?.text ? (
                            <bdi dir="auto" className="block truncate">
                              {cell.text}
                            </bdi>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
      </Card>
      <p className="text-sm text-muted-foreground">
        {preview.problems === 0
          ? 'Every cell in these rows can be imported.'
          : `${preview.problems} ${preview.problems === 1 ? 'cell' : 'cells'} in these rows can't be imported and will be left empty.`}
      </p>
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{importErrorText(error)}</AlertDescription>
        </Alert>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button onClick={onImport} disabled={starting}>
          {starting && <Spinner />}
          Import {imp.rowCount} {imp.rowCount === 1 ? 'row' : 'rows'}
        </Button>
      </div>
    </>
  )
}

function ResultCard({ imp, formId, onAnother }: { imp: SubmissionsImport; formId: string; onAnother: () => void }) {
  const r = imp.report
  if (imp.status === 'failed')
    return (
      <Alert variant="destructive">
        <TriangleAlertIcon />
        <AlertTitle>The import failed and nothing was added.</AlertTitle>
        <AlertDescription>Check the file and try again.</AlertDescription>
      </Alert>
    )
  const dropped = Object.entries(r.droppedByColumn ?? {})
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CheckIcon className="size-4" aria-hidden />
          {r.imported ?? 0} {r.imported === 1 ? 'submission' : 'submissions'} imported
        </CardTitle>
        <CardDescription>
          From <bdi dir="auto">{imp.filename}</bdi>. Imported submissions don't send notifications or webhooks.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <ul className="flex list-disc flex-col gap-1 ps-5">
          {(r.skippedDuplicate ?? 0) > 0 && <li>{r.skippedDuplicate} rows skipped: already imported.</li>}
          {(r.skippedEmpty ?? 0) > 0 && <li>{r.skippedEmpty} empty rows skipped.</li>}
          {(r.links ?? 0) > 0 && <li>{r.links} file and signature links kept.</li>}
          {(r.cellsDropped ?? 0) > 0 ? (
            <li>
              {r.cellsDropped} {r.cellsDropped === 1 ? 'cell' : 'cells'} couldn't be imported:{' '}
              {dropped.map(([col, n], i) => (
                <span key={col}>
                  {i > 0 && ', '}
                  <bdi dir="auto">{col}</bdi> (<span className="tabular-nums">{n}</span>)
                </span>
              ))}
              .
            </li>
          ) : (
            <li>Every mapped cell was imported.</li>
          )}
          {r.dedupe === false && <li>No submission ID column: importing this file again would add the rows again.</li>}
        </ul>
        {r.problemRows && r.problemRows.length > 0 && (
          <ScrollArea className="w-full rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="ps-3">Row</TableHead>
                  <TableHead>Column</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead className="pe-3">Problem</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {r.problemRows.slice(0, 20).map((p, i) => (
                  <TableRow key={i}>
                    <TableCell className="ps-3 tabular-nums">{p.row}</TableCell>
                    <TableCell><bdi dir="auto">{p.column}</bdi></TableCell>
                    <TableCell className="max-w-56"><bdi dir="auto" className="block truncate">{p.value}</bdi></TableCell>
                    <TableCell className="pe-3">{PROBLEM_TEXT[p.problem] ?? p.problem}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <ScrollBar orientation="horizontal" />
          </ScrollArea>
        )}
        <div className="flex flex-wrap gap-2 pt-2">
          <Button asChild>
            <Link to="/forms/$formId/submissions" params={{ formId }}>
              Go to submissions
            </Link>
          </Button>
          <Button variant="ghost" onClick={onAnother}>
            Import another file
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export function SubmissionsImportPage() {
  const form = useFormSummary()
  const queryClient = useQueryClient()
  const [imp, setImp] = useState<SubmissionsImport | null>(null)
  const [step, setStep] = useState<'upload' | 'map' | 'preview' | 'running'>('upload')
  const [columns, setColumns] = useState<string[]>([])
  const [dateOrder, setDateOrder] = useState<DateOrder>('auto')
  const [status, setStatus] = useState<SubmissionStatus>('new')
  const [preview, setPreview] = useState<MappingPreview | null>(null)

  const save = useMutation({
    mutationFn: () => importsApi.setMapping(imp!.id, columns, dateOrder),
    onSuccess: (p) => {
      setPreview(p)
      setStep('preview')
    },
  })
  const start = useMutation({
    mutationFn: () => importsApi.start(imp!.id, status),
    onSuccess: (next) => {
      setImp(next)
      setStep('running')
    },
  })
  const poll = useQuery({
    queryKey: ['import', imp?.id],
    queryFn: () => importsApi.getSubmissionsImport(imp!.id),
    enabled: step === 'running' && imp !== null,
    refetchInterval: (q) => (q.state.data && q.state.data.status !== 'running' ? false : 2000),
  })
  const current = poll.data ?? imp
  useEffect(() => {
    if (poll.data && poll.data.status !== 'running') {
      void queryClient.invalidateQueries({ queryKey: ['submissions'] })
      void queryClient.invalidateQueries({ queryKey: ['imports', form.id] })
    }
  }, [poll.data, queryClient, form.id])

  const reset = () => {
    setImp(null)
    setPreview(null)
    setStep('upload')
    start.reset()
    save.reset()
  }

  let body
  if (form.role !== 'owner')
    body = (
      <Alert>
        <AlertDescription>Only owners of this form can import responses.</AlertDescription>
      </Alert>
    )
  else if (form.currentVersion === null)
    body = (
      <Alert>
        <AlertDescription>Publish the form first. Responses are imported into the published version.</AlertDescription>
      </Alert>
    )
  else if (step === 'upload' || !imp)
    body = (
      <UploadStep
        formId={form.id}
        version={form.currentVersion}
        onUploaded={(i) => {
          setImp(i)
          setColumns(i.columns.map((c) => c.target))
          setDateOrder(i.dateOrder)
          setStep('map')
        }}
      />
    )
  else if (step === 'map')
    body = (
      <>
        <MapStep
          imp={imp}
          columns={columns}
          setColumns={setColumns}
          dateOrder={dateOrder}
          setDateOrder={setDateOrder}
          status={status}
          setStatus={setStatus}
          onBack={reset}
          onPreview={() => save.mutate()}
        />
        {save.isError && (
          <Alert variant="destructive">
            <AlertDescription>{importErrorText(save.error)}</AlertDescription>
          </Alert>
        )}
      </>
    )
  else if (step === 'preview' && preview)
    body = (
      <PreviewStep
        imp={imp}
        columns={columns}
        preview={preview}
        onBack={() => setStep('map')}
        onImport={() => start.mutate()}
        starting={start.isPending}
        error={start.error}
      />
    )
  else
    body =
      current && current.status !== 'running' ? (
        <ResultCard imp={current} formId={form.id} onAnother={reset} />
      ) : (
        <Card>
          <CardContent>
            <p className="flex items-center gap-2 text-sm" aria-live="polite">
              <Spinner /> Importing {imp.rowCount} {imp.rowCount === 1 ? 'row' : 'rows'}…
            </p>
          </CardContent>
        </Card>
      )

  return (
    <PageContainer>
      <div className="flex flex-col gap-2">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/forms/$formId/submissions" params={{ formId: form.id }}>
                  Submissions
                </Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>Import responses</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <h1 className="text-xl font-semibold tracking-tight">Import responses</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Bring submissions over from a Jotform export. They keep their original dates and don't send notifications.
        </p>
      </div>
      {body}
    </PageContainer>
  )
}
