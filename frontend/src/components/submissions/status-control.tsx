/**
 * The status `Select` of a submission (PHASE-2-SCREENS 5.3): changes apply at once with Undo;
 * "Rejected" asks for a reason first. Editors and owners only. Renders flex items: the note and
 * the reason field wrap to their own line at the end of the parent row.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Field, FieldError, FieldLabel } from '@/components/ui/field'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api, type SubmissionDetail, type SubmissionStatus } from '@/lib/api'

import { STATUS_LABELS } from './labels'

export function StatusControl({ d }: { d: SubmissionDetail }) {
  const queryClient = useQueryClient()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const change = useMutation({
    mutationFn: ({ status, reason }: { status: SubmissionStatus; reason?: string; previous?: SubmissionStatus }) =>
      api.setSubmissionStatus(d.id, status, reason),
    onSuccess: (next, vars) => {
      queryClient.setQueryData(['submission', d.id], next)
      void queryClient.invalidateQueries({ queryKey: ['submission', d.id, 'verify'] })
      void queryClient.invalidateQueries({ queryKey: ['submissions'] })
      setRejecting(false)
      setReason('')
      const previous = vars.previous
      toast(`Status changed to ${STATUS_LABELS[vars.status]}`, {
        action:
          previous && vars.status !== 'rejected'
            ? {
                label: 'Undo',
                onClick: () =>
                  change.mutate({ status: previous, reason: previous === 'rejected' ? 'Restored' : undefined }),
              }
            : undefined,
      })
    },
    onError: () => toast.error("Couldn't change the status. Try again."),
  })
  const waiting = d.approval?.state === 'pending'
  return (
    <>
      <Select
        disabled={waiting}
        value={rejecting ? 'rejected' : d.status}
        onValueChange={(v) => {
          if (v === 'rejected') return setRejecting(true)
          setRejecting(false)
          change.mutate({ status: v as SubmissionStatus, previous: d.status })
        }}
      >
        <SelectTrigger className="w-48" aria-label="Status" size="sm">
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
      {waiting && (
        <p className="order-last basis-full text-sm text-muted-foreground">The status changes when the approval finishes.</p>
      )}
      {rejecting && (
        <Field data-invalid={reasonError ? true : undefined} className="order-last basis-full max-w-md">
          <FieldLabel htmlFor="reject-reason">Reason (sent to the activity log)</FieldLabel>
          <Textarea id="reject-reason" rows={2} value={reason} autoFocus onChange={(e) => setReason(e.target.value)} />
          {reasonError && <FieldError>{reasonError}</FieldError>}
          <div className="flex gap-2">
            <Button
              variant="destructive"
              size="sm"
              disabled={change.isPending}
              onClick={() => {
                if (!reason.trim()) return setReasonError('Give a reason so others know why it was rejected')
                setReasonError(null)
                change.mutate({ status: 'rejected', reason: reason.trim(), previous: d.status })
              }}
            >
              Reject
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setRejecting(false)}>
              Cancel
            </Button>
          </div>
        </Field>
      )}
    </>
  )
}
