/** Submission detail in a Sheet from the end edge (PHASE-2-SCREENS 5.3). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BadgeCheckIcon, ChevronLeftIcon, ChevronRightIcon, HistoryIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import { Field, FieldError, FieldLabel } from '@/components/ui/field'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api, type SubmissionDetail, type SubmissionStatus } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { FORM_LANGUAGES } from '@/schema/language'

import { ActivityList, CommentBox } from './activity'
import { ApprovalBlock } from './approval-block'
import { AuditDetails } from './audit-details'
import { Answers } from './answers'
import { IntegrityBadge, PdfButton } from './integrity'
import { STATUS_LABELS } from './labels'
import { SubmissionStatusBadge } from './status-badge'

export function SubmissionSheet({
  id,
  onClose,
  onPrev,
  onNext,
}: {
  id: string | null
  onClose: () => void
  onPrev?: () => void
  onNext?: () => void
}) {
  const queryClient = useQueryClient()
  const detail = useQuery({
    queryKey: ['submission', id],
    queryFn: () => api.getSubmission(id!),
    enabled: id !== null,
    // Poll while the signed PDF is being made.
    refetchInterval: (q) => (q.state.data?.pdfStatus === 'pending' ? 2000 : false),
  })
  const integrity = useQuery({
    queryKey: ['submission', id, 'verify'],
    queryFn: () => api.verifySubmission(id!),
    enabled: id !== null,
  })
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const change = useMutation({
    mutationFn: ({ status, reason }: { status: SubmissionStatus; reason?: string }) =>
      api.setSubmissionStatus(id!, status, reason),
    onSuccess: (next, vars) => {
      queryClient.setQueryData(['submission', id], next)
      void queryClient.invalidateQueries({ queryKey: ['submission', id, 'verify'] })
      void queryClient.invalidateQueries({ queryKey: ['submissions'] })
      const previous = detail.data?.status
      setRejecting(false)
      setReason('')
      toast(`Status changed to ${STATUS_LABELS[vars.status]}`, {
        action:
          previous && vars.status !== 'rejected'
            ? { label: 'Undo', onClick: () => change.mutate({ status: previous, reason: previous === 'rejected' ? 'Restored' : undefined }) }
            : undefined,
      })
    },
    onError: () => toast.error("Couldn't change the status. Try again."),
  })

  // J / K move through the list while the sheet is open.
  useEffect(() => {
    if (!id) return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (['INPUT', 'TEXTAREA'].includes(t.tagName) || t.isContentEditable) return
      if (e.key === 'j') onNext?.()
      if (e.key === 'k') onPrev?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [id, onNext, onPrev])

  // Return focus to the row of the submission that was open last (Prev/Next may have moved it).
  const lastId = useRef<string | null>(null)
  useEffect(() => {
    if (id) lastId.current = id
  }, [id])

  const d = detail.data
  return (
    <Sheet open={id !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="w-full gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-2xl"
        onCloseAutoFocus={(e) => {
          const rows = document.querySelectorAll<HTMLElement>(`[data-submission="${lastId.current}"]`)
          const row = [...rows].find((r) => r.offsetParent !== null)
          if (row) {
            e.preventDefault()
            row.focus()
          }
        }}
      >
        <SheetHeader className="border-b">
          <div className="flex items-center gap-3 pe-8">
            <SheetTitle className="text-lg tabular-nums">{d ? `#${String(d.seq).padStart(4, '0')}` : 'Submission'}</SheetTitle>
            {d && <SubmissionStatusBadge status={d.status} />}
            <ButtonGroup className="ms-auto" aria-label="Move through submissions">
              <Button variant="outline" size="sm" onClick={onPrev} disabled={!onPrev}>
                <ChevronLeftIcon />
                Prev
              </Button>
              <Button variant="outline" size="sm" onClick={onNext} disabled={!onNext}>
                Next
                <ChevronRightIcon />
              </Button>
            </ButtonGroup>
          </div>
          <SheetDescription>
            {d ? (
              <>
                <span>Submitted {formatDateTime(d.createdAt)}</span>, <span>version {d.version}</span>,{' '}
                <span>{FORM_LANGUAGES[d.language].label}</span>
                {d.respondentEmail && <RespondentLine d={d} />}
              </>
            ) : (
              'Loading'
            )}
          </SheetDescription>
          {d && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {integrity.data && <IntegrityBadge result={integrity.data} />}
              <PdfButton d={d} />
            </div>
          )}
          {integrity.data && !integrity.data.ok && (
            <Alert variant="destructive" className="mt-2">
              <AlertDescription>
                This submission changed outside JustForms after it was submitted. Download the PDF and contact your administrator.
              </AlertDescription>
            </Alert>
          )}
          {d?.canEdit ? (
            <div className="flex flex-col gap-2 pt-2">
              <Select
                disabled={d.approval?.state === 'pending'}
                value={rejecting ? 'rejected' : d.status}
                onValueChange={(v) => {
                  if (v === 'rejected') return setRejecting(true)
                  setRejecting(false)
                  change.mutate({ status: v as SubmissionStatus })
                }}
              >
                <SelectTrigger className="w-48" aria-label="Status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(STATUS_LABELS) as SubmissionStatus[]).map((s) => (
                    <SelectItem key={s} value={s}>
                      Status: {STATUS_LABELS[s]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {d.approval?.state === 'pending' && (
                <p className="text-sm text-muted-foreground">The status changes when the approval finishes.</p>
              )}
              {rejecting && (
                <Field data-invalid={reasonError ? true : undefined}>
                  <FieldLabel htmlFor="reject-reason">Reason (sent to the activity log)</FieldLabel>
                  <Textarea id="reject-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
                  {reasonError && <FieldError>{reasonError}</FieldError>}
                  <div className="flex gap-2">
                    <Button
                      variant="destructive"
                      onClick={() => {
                        if (!reason.trim()) return setReasonError('Give a reason so others know why it was rejected')
                        setReasonError(null)
                        change.mutate({ status: 'rejected', reason: reason.trim() })
                      }}
                    >
                      Reject
                    </Button>
                    <Button variant="ghost" onClick={() => setRejecting(false)}>
                      Cancel
                    </Button>
                  </div>
                </Field>
              )}
            </div>
          ) : d ? (
            <p className="pt-2 text-sm text-muted-foreground">You can view submissions. Ask an owner to change status.</p>
          ) : null}
        </SheetHeader>
        <Tabs defaultValue="answers" className="min-h-0 flex-1 gap-0">
          <TabsList className="mx-4 mt-3">
            <TabsTrigger value="answers">Answers</TabsTrigger>
            <TabsTrigger value="activity" className="gap-1.5">
              Activity
              {d && (
                <Badge variant="secondary" className="tabular-nums">
                  {d.events.length}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>
          <ScrollArea className="min-h-0 flex-1">
            <TabsContent value="answers" className="flex flex-col gap-6 p-4">
              {d && <ImportedNote d={d} />}
              {d && <ApprovalBlock d={d} />}
              {d ? (
                <Answers
                  form={d.schema}
                  data={d.data}
                  signatures={d.signatures}
                  reveal={
                    d.canEdit
                      ? async (fieldId, row) => {
                          const res = await api.reveal(d.id, fieldId, row)
                          void queryClient.invalidateQueries({ queryKey: ['submission', d.id] })
                          return res.value
                        }
                      : undefined
                  }
                />
              ) : (
                <Skeleton className="h-48" />
              )}
              {d && <AuditDetails d={d} />}
            </TabsContent>
            <TabsContent value="activity" className="flex flex-col gap-4 p-4">
              {d && <CommentBox id={d.id} />}
              {d ? <ActivityList events={d.events} /> : <Skeleton className="h-24" />}
            </TabsContent>
          </ScrollArea>
        </Tabs>
      </SheetContent>
    </Sheet>
  )
}

/** Rows brought over from a Jotform export (JOTFORM-IMPORT-SCREENS 3.4). */
type Imported = SubmissionDetail & {
  source?: string
  externalId?: string | null
  importedLinks?: Record<string, string[]> | null
}

function fieldLabels(schema: SubmissionDetail['schema']): Map<string, string> {
  const out = new Map<string, string>()
  const walk = (els: SubmissionDetail['schema']['pages'][number]['elements']) => {
    for (const el of els ?? []) {
      if (el.kind === 'field') out.set(el.id, el.label || el.id)
      if (el.kind === 'section' || el.kind === 'repeater') walk(el.elements ?? [])
    }
  }
  for (const page of schema.pages) walk(page.elements ?? [])
  return out
}

function ImportedNote({ d }: { d: Imported }) {
  if (d.source !== 'jotform_import') return null
  const links = Object.entries(d.importedLinks ?? {})
  const labels = fieldLabels(d.schema)
  return (
    <Alert>
      <HistoryIcon />
      <AlertTitle>
        Imported from Jotform
        {d.externalId && (
          <>
            {' '}
            (submission <bdi dir="ltr" className="tabular-nums">{d.externalId}</bdi>)
          </>
        )}
      </AlertTitle>
      <AlertDescription>
        <p>Originally submitted {formatDateTime(d.submittedAt)}. Signatures from Jotform are not part of JustForms' audit trail.</p>
        {links.length > 0 && (
          <>
            <p>Files and signatures stay on Jotform:</p>
            <ul className="flex list-disc flex-col gap-1 ps-5">
              {links.flatMap(([fieldId, urls]) =>
                urls.map((u) => (
                  <li key={u} className="min-w-0 break-all">
                    <bdi dir="auto">{labels.get(fieldId) ?? fieldId}</bdi>:{' '}
                    <a href={u} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-4">
                      <bdi dir="ltr">{u.split('/').pop() || u}</bdi>
                    </a>
                  </li>
                )),
              )}
            </ul>
          </>
        )}
      </AlertDescription>
    </Alert>
  )
}

/** ", by {email}" with how the address was confirmed (PHASE-4-SCREENS 4). */
function RespondentLine({ d }: { d: SubmissionDetail }) {
  const via = d.events.find((e) => e.type === 'created')?.payload.respondentVia
  return (
    <>
      , by{' '}
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex items-center gap-1 text-foreground" tabIndex={0}>
            <BadgeCheckIcon className="size-3.5" aria-hidden />
            <bdi dir="ltr">{d.respondentEmail}</bdi>
          </span>
        </TooltipTrigger>
        <TooltipContent>{via === 'staff' ? 'Signed in' : 'Email confirmed with a code'}</TooltipContent>
      </Tooltip>
    </>
  )
}
