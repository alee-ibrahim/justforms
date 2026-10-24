/**
 * A submission's approval in the detail sheet (APPROVALS-SCREENS 3.2): one row per step with
 * its state (icon and words, never colour alone), and for editors on the current step "Send
 * the email again" and "Stop approval".
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BanIcon, CheckIcon, CircleDashedIcon, ClockIcon, TriangleAlertIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Field, FieldError, FieldLabel } from '@/components/ui/field'
import { Item, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { api, type ApprovalStepInfo, type StepState, type SubmissionDetail } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { buildIndex } from '@/logic/form-index'
import { formLanguage } from '@/schema/language'

const ICONS: Record<StepState, typeof CheckIcon> = {
  waiting: CircleDashedIcon,
  pending: ClockIcon,
  no_approver: TriangleAlertIcon,
  approved: CheckIcon,
  rejected: XIcon,
  stopped: BanIcon,
}

function Who({ s }: { s: ApprovalStepInfo }) {
  return (
    <>
      <bdi dir="auto">{s.decidedName}</bdi> (<bdi dir="ltr">{s.approverEmail}</bdi>), {s.decidedAt && formatDateTime(s.decidedAt)}
    </>
  )
}

function describe(s: ApprovalStepInfo, d: SubmissionDetail): React.ReactNode {
  switch (s.state) {
    case 'approved':
      return (
        <>
          Approved by <Who s={s} />
        </>
      )
    case 'rejected':
      return (
        <>
          Rejected by <Who s={s} />
        </>
      )
    case 'pending':
      return (
        <>
          Waiting for <bdi dir="ltr">{s.approverEmail}</bdi>
          {s.requestedAt && <> since {formatDateTime(s.requestedAt)}</>}
        </>
      )
    case 'no_approver': {
      const el = s.fieldId ? buildIndex(d.schema).elements.get(s.fieldId)?.element : undefined
      const label = el && 'label' in el ? el.label : s.fieldId
      return (
        <>
          No approver: the answer to “
          <bdi dir="auto" lang={formLanguage(d.schema)}>
            {label}
          </bdi>
          ” is empty
        </>
      )
    }
    case 'stopped':
      return 'Stopped'
    case 'waiting':
      return 'Not started'
  }
}

function StopDialog({ id, open, onOpenChange }: { id: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const stop = useMutation({
    mutationFn: () => api.stopApproval(id, reason.trim()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['submission', id] })
      void queryClient.invalidateQueries({ queryKey: ['submissions'] })
      onOpenChange(false)
      setReason('')
      toast('Approval stopped')
    },
    onError: () => toast.error("Couldn't stop the approval. Try again."),
  })
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Stop this approval?</AlertDialogTitle>
          <AlertDialogDescription>The approver's link stops working. You can then set the status yourself.</AlertDialogDescription>
        </AlertDialogHeader>
        <Field data-invalid={error ? true : undefined}>
          <FieldLabel htmlFor="stop-reason">Reason</FieldLabel>
          <Textarea
            id="stop-reason"
            rows={2}
            maxLength={2000}
            value={reason}
            aria-invalid={error ? true : undefined}
            onChange={(e) => setReason(e.target.value)}
          />
          {error && <FieldError>{error}</FieldError>}
        </Field>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button
            variant="destructive"
            disabled={stop.isPending}
            onClick={() => {
              if (!reason.trim()) return setError('Give a reason so others know why it was stopped')
              setError(null)
              stop.mutate()
            }}
          >
            {stop.isPending && <Spinner />}
            Stop approval
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function ApprovalBlock({ d }: { d: SubmissionDetail }) {
  const [stopping, setStopping] = useState(false)
  const resend = useMutation({
    mutationFn: () => api.resendApproval(d.id),
    onSuccess: () => toast('Email sent again'),
    onError: () => toast.error("Couldn't send the email. Try again."),
  })
  const a = d.approval
  if (!a) return null
  const running = a.state === 'pending'
  const language = formLanguage(d.schema)
  return (
    <section aria-labelledby="approval-heading" className="flex flex-col gap-1 rounded-md border bg-card px-3 py-2">
      <h3 id="approval-heading" className="text-sm font-medium">
        Approval
      </h3>
      <ItemGroup className="gap-0">
        {a.steps.map((s) => {
          const Icon = ICONS[s.state]
          const current = running && s.step === a.step
          return (
            <Item key={s.step} size="sm" className="items-start px-0">
              <ItemMedia variant="icon" className={s.state === 'rejected' ? 'text-destructive' : undefined}>
                <Icon aria-hidden />
              </ItemMedia>
              <ItemContent className="min-w-0">
                <ItemTitle className="max-w-full">
                  <span>
                    <span className="tabular-nums">{s.step}.</span>{' '}
                    <bdi dir="auto" lang={language}>
                      {s.name}
                    </bdi>
                  </span>
                </ItemTitle>
                <ItemDescription className="line-clamp-none">{describe(s, d)}</ItemDescription>
                {s.comment && (
                  <ItemDescription className="line-clamp-none whitespace-pre-wrap text-foreground">
                    <bdi dir="auto">{s.comment}</bdi>
                  </ItemDescription>
                )}
                {current && d.canEdit && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    {s.state === 'pending' && (
                      <Button variant="outline" size="sm" disabled={resend.isPending} onClick={() => resend.mutate()}>
                        {resend.isPending && <Spinner />}
                        Send the email again
                      </Button>
                    )}
                    <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setStopping(true)}>
                      Stop approval
                    </Button>
                  </div>
                )}
              </ItemContent>
            </Item>
          )
        })}
      </ItemGroup>
      <StopDialog id={d.id} open={stopping} onOpenChange={setStopping} />
    </section>
  )
}
