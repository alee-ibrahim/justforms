/**
 * Selection bar for bulk status changes, approval decisions, export and delete
 * (PHASE-3-SCREENS 6, APPROVALS-SCREENS 3.5).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckIcon, ChevronDownIcon, FileSpreadsheetIcon, TrashIcon, XIcon } from 'lucide-react'
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
import { ButtonGroup } from '@/components/ui/button-group'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { api, type BulkDecideResult, type SubmissionStatus } from '@/lib/api'
import { metaQuery } from '@/lib/queries'

import { STATUS_LABELS } from './labels'

const reference = (seq: number) => `#${String(seq).padStart(4, '0')}`
const plural = (n: number) => `${n} ${n === 1 ? 'submission' : 'submissions'}`

/** A selected submission waiting at an approval step. */
export interface ApprovalItem {
  id: string
  step: number
}

/** One toast for a bulk decision: how many were decided, and which ones someone decided first. */
function reportDecisions(results: BulkDecideResult[], approve: boolean) {
  const done = results.filter((r) => r.result === 'approved' || r.result === 'rejected').length
  const missed = results.filter((r) => r.result !== 'approved' && r.result !== 'rejected')
  const head = done ? `${approve ? 'Approved' : 'Rejected'} ${plural(done)}` : 'Nothing was decided'
  if (!missed.length) return toast(head)
  toast.warning(head, {
    description: missed
      .map((r) =>
        r.result === 'already_decided'
          ? `${r.seq ? reference(r.seq) : 'One'}: already decided${r.decidedName ? ` by ${r.decidedName}` : ''}`
          : `${r.seq ? reference(r.seq) : 'One'}: not found`,
      )
      .join('\n'),
    classNames: { description: 'whitespace-pre-line' },
  })
}

export function BulkBar({
  formId,
  ids,
  canDelete,
  approvalItems = [],
  onClear,
  onExport,
}: {
  formId: string
  ids: string[]
  canDelete: boolean
  /** The selected submissions that wait at an approval step (approve / reject them there). */
  approvalItems?: ApprovalItem[]
  onClear: () => void
  onExport: () => void
}) {
  const queryClient = useQueryClient()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const [deciding, setDeciding] = useState<'approve' | 'reject' | null>(null)
  const [comment, setComment] = useState('')
  const [commentError, setCommentError] = useState<string | null>(null)
  const n = ids.length
  const waiting = approvalItems.length
  // Keep the wording of the last choice while the dialog animates closed.
  const [shown, setShown] = useState(deciding)
  if (deciding && deciding !== shown) setShown(deciding)
  const mode = deciding ?? shown
  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject') =>
      api.bulkDecideApproval(formId, { items: approvalItems, decision, comment: comment.trim() }),
    onSuccess: (res, decision) => {
      void queryClient.invalidateQueries({ queryKey: ['submissions', formId] })
      void queryClient.invalidateQueries({ queryKey: ['submission'] })
      reportDecisions(res.results, decision === 'approve')
      setDeciding(null)
      setComment('')
      onClear()
    },
    onError: () => toast.error("Couldn't save the decisions. Try again."),
  })
  const skipped = n - waiting
  const trashDays = useQuery(metaQuery).data?.trashDays ?? 30
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['submissions', formId] })
    void queryClient.invalidateQueries({ queryKey: ['submission'] })
    void queryClient.invalidateQueries({ queryKey: ['forms'] })
  }
  /** Undo a delete: the same submissions come back from Deleted. */
  const undoDelete = (deleted: string[]) =>
    api.bulk(formId, { ids: deleted, action: 'restore' }).then(
      (res) => {
        refresh()
        toast(`Restored ${plural(res.changed)}`)
      },
      () => toast.error("Couldn't restore them. Find them under Deleted."),
    )
  const run = useMutation({
    mutationFn: (body: { action: 'status' | 'delete'; status?: SubmissionStatus; reason?: string }) =>
      api.bulk(formId, { ids, ...body }),
    onSuccess: (res, body) => {
      refresh()
      if (body.action === 'delete') {
        const deleted = [...ids]
        toast(`Deleted ${plural(res.changed)}`, {
          description: `In Deleted for ${trashDays} days.`,
          action: { label: 'Undo', onClick: () => void undoDelete(deleted) },
          duration: 10_000,
        })
      } else toast(`Changed ${plural(res.changed)} to ${STATUS_LABELS[body.status!]}`)
      setRejecting(false)
      setReason('')
      onClear()
    },
    onError: () => toast.error("Couldn't change the submissions. Try again."),
  })

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border bg-card px-3 py-2" role="region" aria-label="Selected submissions">
      <span className="text-sm font-medium tabular-nums">{n} selected</span>
      <ButtonGroup>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">
              Change status
              <ChevronDownIcon />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {(Object.keys(STATUS_LABELS) as SubmissionStatus[]).map((s) => (
              <DropdownMenuItem
                key={s}
                onSelect={() => (s === 'rejected' ? setRejecting(true) : run.mutate({ action: 'status', status: s }))}
              >
                {STATUS_LABELS[s]}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="outline" size="sm" onClick={onExport}>
          <FileSpreadsheetIcon />
          Export selected
        </Button>
      </ButtonGroup>
      {waiting > 0 && (
        <ButtonGroup aria-label="Approval">
          <Button size="sm" onClick={() => setDeciding('approve')}>
            <CheckIcon />
            Approve
          </Button>
          <Button size="sm" variant="outline" className="text-destructive" onClick={() => setDeciding('reject')}>
            <XIcon />
            Reject…
          </Button>
        </ButtonGroup>
      )}
      {/* Apart from the group and styled as destructive, so it never reads like Export. No
          confirmation: deleting goes to Deleted and the toast offers Undo (REVIEW-CHECKLIST E). */}
      {canDelete && (
        <Button variant="destructive" size="sm" disabled={run.isPending} onClick={() => run.mutate({ action: 'delete' })}>
          <TrashIcon />
          Delete
        </Button>
      )}
      <Button variant="ghost" size="sm" className="ms-auto" onClick={onClear}>
        Clear selection
      </Button>

      <Dialog open={rejecting} onOpenChange={setRejecting}>
        <DialogContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (!reason.trim()) return setReasonError('Give a reason so others know why they were rejected')
              setReasonError(null)
              run.mutate({ action: 'status', status: 'rejected', reason: reason.trim() })
            }}
          >
            <DialogHeader>
              <DialogTitle>Reject {plural(n)}</DialogTitle>
            </DialogHeader>
            <Field data-invalid={reasonError ? true : undefined}>
              <FieldLabel htmlFor="bulk-reason">Reason (added to each activity log)</FieldLabel>
              <Textarea id="bulk-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
              {reasonError && <FieldError>{reasonError}</FieldError>}
            </Field>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setRejecting(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="destructive" disabled={run.isPending}>
                Reject {n}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deciding !== null} onOpenChange={(o) => !o && !decide.isPending && setDeciding(null)}>
        <AlertDialogContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (deciding === 'reject' && !comment.trim()) return setCommentError("Write why you're rejecting them")
              setCommentError(null)
              if (deciding) decide.mutate(deciding)
            }}
          >
            <AlertDialogHeader>
              <AlertDialogTitle>
                {mode === 'reject' ? 'Reject' : 'Approve'} {plural(waiting)}?
              </AlertDialogTitle>
              <AlertDialogDescription>
                {mode === 'reject'
                  ? 'Each one is rejected at its current step, which ends its approval.'
                  : 'Each one is approved at its current step and moves to its next step, or is approved when that was the last.'}{' '}
                Your decision replaces the approvers' and their emailed links will show it's done.
                {skipped > 0 && ` ${plural(skipped)} not waiting for approval ${skipped === 1 ? 'is' : 'are'} left as they are.`}
              </AlertDialogDescription>
            </AlertDialogHeader>
            {mode === 'reject' && (
              <Field data-invalid={commentError ? true : undefined}>
                <FieldLabel htmlFor="bulk-decide-comment">Comment</FieldLabel>
                <Textarea
                  id="bulk-decide-comment"
                  rows={3}
                  maxLength={2000}
                  value={comment}
                  autoFocus
                  aria-invalid={commentError ? true : undefined}
                  onChange={(e) => setComment(e.target.value)}
                />
                <FieldDescription>The same comment goes on each one. Respondents emailed the outcome see it.</FieldDescription>
                {commentError && <FieldError>{commentError}</FieldError>}
              </Field>
            )}
            <AlertDialogFooter>
              <AlertDialogCancel type="button" disabled={decide.isPending}>
                Cancel
              </AlertDialogCancel>
              <Button type="submit" variant={mode === 'reject' ? 'destructive' : 'default'} disabled={decide.isPending}>
                {decide.isPending && <Spinner />}
                {mode === 'reject' ? 'Reject' : 'Approve'} {waiting}
              </Button>
            </AlertDialogFooter>
          </form>
        </AlertDialogContent>
      </AlertDialog>

    </div>
  )
}
