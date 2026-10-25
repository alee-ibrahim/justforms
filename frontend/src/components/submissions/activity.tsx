/** Activity log of a submission, newest first (PHASE-3-SCREENS 2). */
import {
  ArrowRightLeftIcon,
  BanIcon,
  CheckIcon,
  ClockIcon,
  EyeIcon,
  FileCheckIcon,
  FileSpreadsheetIcon,
  MailIcon,
  MessageSquareIcon,
  PlusIcon,
  TrashIcon,
  TriangleAlertIcon,
  XIcon,
} from 'lucide-react'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Field, FieldLabel } from '@/components/ui/field'
import { Textarea } from '@/components/ui/textarea'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { api, type EventType, type SubmissionEvent, type SubmissionStatus } from '@/lib/api'
import { formatDateTime } from '@/lib/format'

import { STATUS_LABELS } from './labels'

const ICONS = {
  created: PlusIcon,
  status_changed: ArrowRightLeftIcon,
  comment: MessageSquareIcon,
  pdf_generated: FileCheckIcon,
  exported: FileSpreadsheetIcon,
  viewed: EyeIcon,
  deleted: TrashIcon,
  approval_requested: MailIcon,
  approval_decided: CheckIcon,
  approval_waiting: TriangleAlertIcon,
  approval_stopped: BanIcon,
} satisfies Record<EventType, unknown>

/** "(step 1, Supervisor)": the step name is form content, isolated for bidi. */
function stepOf(ev: SubmissionEvent) {
  return (
    <>
      {' '}
      (step {String(ev.payload.step)}, <bdi dir="auto">{String(ev.payload.name ?? '')}</bdi>)
    </>
  )
}

function icon(ev: SubmissionEvent) {
  if (ev.type === 'approval_decided' && ev.payload.decision === 'rejected') return XIcon
  if (ev.type === 'approval_requested') return ev.payload.approverEmail ? MailIcon : ClockIcon
  return ICONS[ev.type]
}

function title(ev: SubmissionEvent): React.ReactNode {
  const who = ev.actorName ?? 'Someone'
  switch (ev.type) {
    case 'created':
      return ev.payload.imported ? 'Imported from Jotform' : 'Submitted'
    case 'status_changed':
      if (ev.payload.via === 'approval')
        return `Approval set the status to ${STATUS_LABELS[ev.payload.to as SubmissionStatus] ?? String(ev.payload.to)}`
      return `${who} changed status to ${STATUS_LABELS[ev.payload.to as SubmissionStatus] ?? String(ev.payload.to)}`
    case 'comment':
      return `${who} commented`
    case 'pdf_generated':
      return 'Signed PDF created'
    case 'exported':
      return `Exported to Excel by ${who}`
    case 'viewed':
      return `${who} viewed a sensitive answer`
    case 'deleted':
      return `${who} deleted this submission`
    case 'approval_requested':
      return (
        <>
          Approval requested from <bdi dir="ltr">{String(ev.payload.approverEmail)}</bdi>
          {stepOf(ev)}
        </>
      )
    case 'approval_decided':
      return (
        <>
          <bdi dir="auto">{String(ev.payload.approverName)}</bdi> {ev.payload.decision === 'rejected' ? 'rejected' : 'approved'}
          {stepOf(ev)}
        </>
      )
    case 'approval_waiting':
      return <>Approval waiting: no approver{stepOf(ev)}</>
    case 'approval_stopped':
      return `${who} stopped the approval`
  }
}

function detail(ev: SubmissionEvent): string | null {
  if (ev.type === 'comment') return String(ev.payload.text ?? '')
  if (ev.type === 'status_changed' && ev.payload.reason) return `Reason: ${String(ev.payload.reason)}`
  if (ev.type === 'approval_decided' && ev.payload.comment) return `Comment: ${String(ev.payload.comment)}`
  if (ev.type === 'approval_stopped' && ev.payload.reason) return `Reason: ${String(ev.payload.reason)}`
  if (ev.type === 'approval_waiting') return 'The answer with the approver’s email is empty. Stop the approval to set the status yourself.'
  return null
}

export function ActivityList({ events }: { events: SubmissionEvent[] }) {
  if (!events.length) return <p className="text-sm text-muted-foreground">No activity yet.</p>
  return (
    <ItemGroup className="gap-1">
      {events.map((ev) => {
        const Icon = icon(ev)
        const text = detail(ev)
        return (
          <Item key={ev.seq} size="sm" className="items-start px-0">
            <ItemMedia variant="icon">
              <Icon />
            </ItemMedia>
            <ItemContent className="min-w-0">
              {/* One span: ItemTitle is a flex row, which would space out mixed text and bdi runs. */}
              <ItemTitle>
                <span>{title(ev)}</span>
              </ItemTitle>
              {text && <ItemDescription className="line-clamp-none whitespace-pre-wrap text-foreground">{text}</ItemDescription>}
            </ItemContent>
            <ItemActions className="text-xs tabular-nums text-muted-foreground">{formatDateTime(ev.createdAt)}</ItemActions>
          </Item>
        )
      })}
    </ItemGroup>
  )
}

/** "Add a comment": plain text, part of the activity log; viewers can comment too. */
export function CommentBox({ id }: { id: string }) {
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const send = useMutation({
    mutationFn: () => api.addComment(id, text.trim()),
    onSuccess: (next) => {
      queryClient.setQueryData(['submission', id], next)
      void queryClient.invalidateQueries({ queryKey: ['submission', id, 'verify'] })
      setText('')
      toast('Comment added')
    },
    onError: () => toast.error("Couldn't add the comment. Try again."),
  })
  const ready = text.trim().length > 0 && !send.isPending
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (ready) send.mutate()
      }}
    >
      <Field>
        <FieldLabel htmlFor="comment">Add a comment</FieldLabel>
        <Textarea
          id="comment"
          rows={2}
          maxLength={4000}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && ready) {
              e.preventDefault()
              send.mutate()
            }
          }}
        />
        <div>
          <Button type="submit" size="sm" disabled={!ready}>
            Comment
          </Button>
        </div>
      </Field>
    </form>
  )
}
