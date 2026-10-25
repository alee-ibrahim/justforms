/**
 * A submission's approval (APPROVALS-SCREENS 3.2, 3.4): one row per step with its state (icon
 * and words, never colour alone) and who decided it, and for editors on the current step
 * "Approve", "Reject…", "Send the email again" and "Stop approval". Deciding here counts as the
 * step's decision: the approver's emailed link then says it's done.
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
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Item, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { api, type ApprovalStepInfo, type StepState, type SubmissionDetail } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { buildIndex } from '@/logic/form-index'
import { formLanguage } from '@/schema/language'

import { alreadyDecidedMessage, decidableStep } from './approval-lib'

const ICONS: Record<StepState, typeof CheckIcon> = {
  waiting: CircleDashedIcon,
  pending: ClockIcon,
  no_approver: TriangleAlertIcon,
  approved: CheckIcon,
  rejected: XIcon,
  stopped: BanIcon,
}

function Who({ s }: { s: ApprovalStepInfo }) {
  const email = s.decidedEmail ?? s.approverEmail
  return (
    <>
      <bdi dir="auto">{s.decidedName}</bdi>
      {email && email !== s.decidedName && (
        <>
          {' '}
          (<bdi dir="ltr">{email}</bdi>)
        </>
      )}
      {s.decidedVia === 'studio' ? ' in the studio' : s.decidedVia === 'email' ? ' by email' : ''}
      {s.decidedAt && <>, {formatDateTime(s.decidedAt)}</>}
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
      if (s.source === 'editors')
        return (
          <>
            Waiting for a decision by someone with edit access
            {s.requestedAt && <> since {formatDateTime(s.requestedAt)}</>}
          </>
        )
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

function DecideDialog({
  d,
  step,
  decision,
  onOpenChange,
}: {
  d: SubmissionDetail
  step: ApprovalStepInfo
  decision: 'approve' | 'reject' | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [comment, setComment] = useState('')
  const [error, setError] = useState<string | null>(null)
  const a = d.approval!
  const last = step.step === a.total
  const next = a.steps.find((x) => x.step === step.step + 1)
  // Keep the wording of the last choice while the dialog animates closed.
  const [shown, setShown] = useState(decision)
  if (decision && decision !== shown) setShown(decision)
  const reject = (decision ?? shown) === 'reject'
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['submission', d.id] })
    void queryClient.invalidateQueries({ queryKey: ['submissions'] })
  }
  const decide = useMutation({
    mutationFn: (chosen: 'approve' | 'reject') =>
      api.decideApproval(d.id, { step: step.step, decision: chosen, comment: chosen === 'reject' ? comment.trim() : '' }),
    onSuccess: () => {
      refresh()
      onOpenChange(false)
      setComment('')
      toast(reject ? 'Rejected' : last ? 'Approved' : 'Approved. Sent to the next step')
    },
    onError: (err) => {
      const already = alreadyDecidedMessage(err)
      if (already) {
        refresh()
        onOpenChange(false)
        return toast.error(already)
      }
      toast.error("Couldn't save the decision. Try again.")
    },
  })
  const language = formLanguage(d.schema)
  const consequence = reject
    ? `This ends the approval and the response is Rejected.${a.outcomeTo ? ' The respondent is emailed the outcome with your comment.' : ''}`
    : last
      ? `This is the last step, so the response is Approved.${a.outcomeTo ? ' The respondent is emailed the outcome.' : ''}`
      : 'It goes to the next step'
  return (
    <AlertDialog
      open={decision !== null}
      onOpenChange={(o) => {
        if (decide.isPending) return
        if (!o) setError(null)
        onOpenChange(o)
      }}
    >
      <AlertDialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (!decision || decide.isPending) return
            if (reject && !comment.trim()) return setError("Write why you're rejecting it")
            setError(null)
            decide.mutate(decision)
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>{reject ? 'Reject this response?' : 'Approve this response?'}</AlertDialogTitle>
            <AlertDialogDescription>
              {consequence}
              {!reject && !last && next && (
                <>
                  ,{' '}
                  <bdi dir="auto" lang={language}>
                    {next.name}
                  </bdi>
                </>
              )}
              {!reject && !last && '.'} You decide step {step.step} (
              <bdi dir="auto" lang={language}>
                {step.name}
              </bdi>
              ){step.source === 'editors' ? '.' : " in place of the approver. The emailed link will show it's done."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {reject && (
            <Field data-invalid={error ? true : undefined}>
              <FieldLabel htmlFor="decide-comment">Comment</FieldLabel>
              <Textarea
                id="decide-comment"
                rows={3}
                maxLength={2000}
                value={comment}
                autoFocus
                aria-invalid={error ? true : undefined}
                aria-describedby="decide-comment-hint"
                onChange={(e) => setComment(e.target.value)}
              />
              <FieldDescription id="decide-comment-hint">
                Needed to reject.{a.outcomeTo ? ' The respondent sees it.' : ''}
              </FieldDescription>
              {error && <FieldError>{error}</FieldError>}
            </Field>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel type="button" disabled={decide.isPending}>
              Cancel
            </AlertDialogCancel>
            <Button type="submit" variant={reject ? 'destructive' : 'default'} disabled={decide.isPending}>
              {decide.isPending && <Spinner />}
              {reject ? 'Reject' : 'Approve'}
            </Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/**
 * "Approve" / "Reject…" for the step waiting now, shown in the submission header in place of
 * the (locked) status control. Renders nothing when the person can't decide.
 */
export function ApprovalDecision({ d }: { d: SubmissionDetail }) {
  const [decision, setDecision] = useState<'approve' | 'reject' | null>(null)
  const step = decidableStep(d)
  if (!step) return null
  return (
    <>
      <Button size="sm" onClick={() => setDecision('approve')}>
        <CheckIcon />
        Approve
      </Button>
      <Button size="sm" variant="outline" className="text-destructive" onClick={() => setDecision('reject')}>
        <XIcon />
        Reject…
      </Button>
      <p className="order-last basis-full text-sm text-muted-foreground">
        {d.approval!.total > 1 && <>Step {step.step} of {d.approval!.total}, </>}
        <bdi dir="auto" lang={formLanguage(d.schema)}>
          {step.name}
        </bdi>
        :{' '}
        {step.state === 'pending' && step.source === 'editors' ? (
          'waiting for a decision by someone with edit access. You can decide it here.'
        ) : step.state === 'pending' ? (
          <>
            waiting for <bdi dir="ltr">{step.approverEmail}</bdi>. You can decide it here instead.
          </>
        ) : (
          'no approver. Decide it here or stop the approval.'
        )}
      </p>
      <DecideDialog d={d} step={step} decision={decision} onOpenChange={(o) => !o && setDecision(null)} />
    </>
  )
}

function StopDialog({
  id,
  open,
  onOpenChange,
  withLink,
}: {
  id: string
  open: boolean
  onOpenChange: (o: boolean) => void
  withLink: boolean
}) {
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
          <AlertDialogDescription>
            {withLink ? "The approver's link stops working. " : ''}You can then set the status yourself.
          </AlertDialogDescription>
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
  const [decision, setDecision] = useState<'approve' | 'reject' | null>(null)
  const a = d.approval
  const current = a?.state === 'pending' ? a.steps.find((x) => x.step === a.step) : undefined
  const resend = useMutation({
    mutationFn: () => api.resendApproval(d.id),
    onSuccess: () => toast(current?.source === 'editors' ? 'Notification sent again' : 'Email sent again'),
    onError: () => toast.error("Couldn't send the email. Try again."),
  })
  if (!a) return null
  const running = a.state === 'pending'
  const language = formLanguage(d.schema)
  const decidable = decidableStep(d)
  const progress = running
    ? `Step ${a.step} of ${a.total}`
    : a.state === 'approved'
      ? 'Approved'
      : a.state === 'rejected'
        ? 'Rejected'
        : 'Stopped'
  return (
    <section aria-labelledby="approval-heading" className="flex flex-col gap-1 rounded-md border bg-card px-3 py-2">
      <div className="flex items-baseline gap-2">
        <h3 id="approval-heading" className="text-sm font-medium">
          Approval
        </h3>
        <span className="ms-auto text-xs text-muted-foreground tabular-nums">{progress}</span>
      </div>
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
                    {decidable?.step === s.step && (
                      <>
                        <Button size="sm" onClick={() => setDecision('approve')}>
                          Approve
                        </Button>
                        <Button variant="outline" size="sm" className="text-destructive" onClick={() => setDecision('reject')}>
                          Reject…
                        </Button>
                      </>
                    )}
                    {s.state === 'pending' && (s.source !== 'editors' || (s.notifyTo ?? []).length > 0) && (
                      <Button variant="outline" size="sm" disabled={resend.isPending} onClick={() => resend.mutate()}>
                        {resend.isPending && <Spinner />}
                        {s.source === 'editors' ? 'Send the notification again' : 'Send the email again'}
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
      {decidable && (
        <DecideDialog d={d} step={decidable} decision={decision} onOpenChange={(o) => !o && setDecision(null)} />
      )}
      <StopDialog id={d.id} open={stopping} onOpenChange={setStopping} withLink={current?.source !== 'editors'} />
    </section>
  )
}
