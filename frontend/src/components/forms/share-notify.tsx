/** "Notify by email" on the Share page (docs/ux/PEOPLE-SCREENS.md 6.1): a checkbox and an
 * optional plain-text message, used under "Add someone by email" and in the dialog that raises
 * someone's role. */
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Textarea } from '@/components/ui/textarea'
import type { FormRole } from '@/lib/api'
import { FORM_ROLE_DESCRIPTIONS, FORM_ROLE_LABELS } from '@/lib/labels'

import { NOTE_MAX, type NotifyChoice } from './share-notify-lib'

export function NotifyFields({
  id,
  smtpEnabled,
  value,
  onChange,
}: {
  id: string
  smtpEnabled: boolean
  value: NotifyChoice
  onChange: (next: NotifyChoice) => void
}) {
  const on = smtpEnabled && value.notify
  return (
    <FieldGroup className="gap-3">
      <Field orientation="horizontal" data-disabled={!smtpEnabled || undefined}>
        <Checkbox
          id={`${id}-notify`}
          checked={on}
          disabled={!smtpEnabled}
          aria-describedby={smtpEnabled ? undefined : `${id}-notify-off`}
          onCheckedChange={(v) => onChange({ ...value, notify: v === true })}
        />
        {smtpEnabled ? (
          <FieldLabel htmlFor={`${id}-notify`} className="font-normal">
            Notify by email
          </FieldLabel>
        ) : (
          <FieldContent>
            <FieldLabel htmlFor={`${id}-notify`} className="font-normal">
              Notify by email
            </FieldLabel>
            <FieldDescription id={`${id}-notify-off`}>Email is not set up on this server.</FieldDescription>
          </FieldContent>
        )}
      </Field>
      {on && (
        <Field>
          <FieldLabel htmlFor={`${id}-message`}>Message (optional)</FieldLabel>
          <Textarea
            id={`${id}-message`}
            rows={2}
            maxLength={NOTE_MAX}
            className="min-h-16"
            placeholder="Add a note to the email"
            value={value.message}
            aria-describedby={`${id}-message-help`}
            onChange={(e) => onChange({ ...value, message: e.target.value })}
          />
          <FieldDescription id={`${id}-message-help`} className="flex justify-between gap-4">
            <span>Plain text. Replies come to your email address.</span>
            <span className="shrink-0 tabular-nums">
              {value.message.length}/{NOTE_MAX}
            </span>
          </FieldDescription>
        </Field>
      )}
    </FieldGroup>
  )
}

/** Raising someone's role: confirm, with "Notify by email" and a message. */
export function RoleChangeDialog({
  change,
  smtpEnabled,
  pending,
  onCancel,
  onConfirm,
}: {
  change: { name: string; role: FormRole } | null
  smtpEnabled: boolean
  pending: boolean
  onCancel: () => void
  onConfirm: (choice: NotifyChoice) => void
}) {
  return (
    <Dialog open={change !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-md">
        {change && (
          <RoleChangeForm
            key={`${change.name}:${change.role}`}
            change={change}
            smtpEnabled={smtpEnabled}
            pending={pending}
            onCancel={onCancel}
            onConfirm={onConfirm}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function RoleChangeForm({
  change,
  smtpEnabled,
  pending,
  onCancel,
  onConfirm,
}: {
  change: { name: string; role: FormRole }
  smtpEnabled: boolean
  pending: boolean
  onCancel: () => void
  onConfirm: (choice: NotifyChoice) => void
}) {
  const [choice, setChoice] = useState<NotifyChoice>({ notify: true, message: '' })
  const label = FORM_ROLE_LABELS[change.role].toLowerCase()
  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        onConfirm(choice)
      }}
    >
      <DialogHeader>
        <DialogTitle>
          Make <bdi dir="auto">{change.name}</bdi> {change.role === 'viewer' ? 'a' : 'an'} {label}?
        </DialogTitle>
        <DialogDescription>{FORM_ROLE_DESCRIPTIONS[change.role]}</DialogDescription>
      </DialogHeader>
      <NotifyFields id="role-change" smtpEnabled={smtpEnabled} value={choice} onChange={setChoice} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          Change role
        </Button>
      </DialogFooter>
    </form>
  )
}
