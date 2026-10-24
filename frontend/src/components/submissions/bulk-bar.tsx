/** Selection bar for bulk status changes, export and delete (PHASE-3-SCREENS 6). */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDownIcon, FileSpreadsheetIcon, TrashIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogAction,
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
import { Field, FieldError, FieldLabel } from '@/components/ui/field'
import { Textarea } from '@/components/ui/textarea'
import { api, type SubmissionStatus } from '@/lib/api'

import { STATUS_LABELS } from './labels'

const plural = (n: number) => `${n} ${n === 1 ? 'submission' : 'submissions'}`

export function BulkBar({
  formId,
  ids,
  canDelete,
  onClear,
  onExport,
}: {
  formId: string
  ids: string[]
  canDelete: boolean
  onClear: () => void
  onExport: () => void
}) {
  const queryClient = useQueryClient()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const n = ids.length
  const run = useMutation({
    mutationFn: (body: { action: 'status' | 'delete'; status?: SubmissionStatus; reason?: string }) =>
      api.bulk(formId, { ids, ...body }),
    onSuccess: (res, body) => {
      void queryClient.invalidateQueries({ queryKey: ['submissions', formId] })
      void queryClient.invalidateQueries({ queryKey: ['submission'] })
      toast(
        body.action === 'delete'
          ? `Deleted ${plural(res.changed)}`
          : `Changed ${plural(res.changed)} to ${STATUS_LABELS[body.status!]}`,
      )
      setRejecting(false)
      setDeleting(false)
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
      {/* Apart from the group and styled as destructive, so it never reads like Export. */}
      {canDelete && (
        <Button variant="destructive" size="sm" onClick={() => setDeleting(true)}>
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

      <AlertDialog open={deleting} onOpenChange={setDeleting}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {plural(n)}?</AlertDialogTitle>
            <AlertDialogDescription>
              They are removed from lists and exports now and erased for good after 30 days.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => run.mutate({ action: 'delete' })}>
              Delete {n}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
