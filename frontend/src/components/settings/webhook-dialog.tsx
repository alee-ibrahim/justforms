/** Add / edit a webhook, then show its signing secret once (PHASE-4-SCREENS 1.4). */
import { CheckIcon, CopyIcon } from 'lucide-react'
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
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import { Switch } from '@/components/ui/switch'
import type { Webhook, WebhookEvent, WebhookInput } from '@/lib/api'

import { EVENT_LABELS, EVENTS, urlError } from './webhook-text'

/** The one-time secret with a copy button. */
export function SecretStep({ secret, onDone }: { secret: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <>
      <DialogHeader>
        <DialogTitle>Copy the signing secret</DialogTitle>
        <DialogDescription>
          You won't see it again. Your system uses it to check that requests come from JustForms.
        </DialogDescription>
      </DialogHeader>
      <InputGroup>
        <InputGroupInput readOnly dir="ltr" aria-label="Signing secret" className="font-mono text-xs" value={secret} onFocus={(e) => e.target.select()} />
        <InputGroupAddon align="inline-end">
          <InputGroupButton
            size="xs"
            onClick={() =>
              void navigator.clipboard?.writeText(secret).then(() => {
                setCopied(true)
                window.setTimeout(() => setCopied(false), 2000)
              })
            }
          >
            {copied ? <CheckIcon /> : <CopyIcon />}
            {copied ? 'Copied' : 'Copy'}
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
      <span className="sr-only" aria-live="polite">
        {copied ? 'Secret copied' : ''}
      </span>
      <DialogFooter>
        <Button onClick={onDone}>Done</Button>
      </DialogFooter>
    </>
  )
}

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Editing an existing webhook (no secret step). */
  initial?: Webhook
  /** Returns the new secret when one was created. */
  onSave: (body: WebhookInput) => Promise<string | null>
}

export function WebhookDialog(props: DialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        {/* Mounted only while open, so every opening starts from the initial values. */}
        <WebhookDialogBody {...props} />
      </DialogContent>
    </Dialog>
  )
}

function WebhookDialogBody({ onOpenChange, initial, onSave }: DialogProps) {
  const [url, setUrl] = useState(initial?.url ?? '')
  const [events, setEvents] = useState<WebhookEvent[]>(initial?.events ?? ['submission.created'])
  const [sensitive, setSensitive] = useState(initial?.includeSensitive ?? false)
  const [error, setError] = useState<string | null>(null)
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [secret, setSecret] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    const value = url.trim()
    if (!/^https?:\/\/\S+$/i.test(value)) return setError('Enter a full address like https://hooks.example.org/justforms')
    if (events.length === 0) return setEventsError('Choose at least one event')
    setSaving(true)
    try {
      const created = await onSave({ url: value, events, includeSensitive: sensitive })
      if (created) setSecret(created)
      else onOpenChange(false)
    } catch (err) {
      setError(urlError(err))
    } finally {
      setSaving(false)
    }
  }

  return secret ? (
    <SecretStep secret={secret} onDone={() => onOpenChange(false)} />
  ) : (
    <form
      className="flex flex-col gap-6"
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <DialogHeader>
        <DialogTitle>{initial ? 'Edit webhook' : 'Add a webhook'}</DialogTitle>
        <DialogDescription>JustForms sends a signed POST request to this address for each event.</DialogDescription>
      </DialogHeader>
      <FieldGroup className="gap-5">
        <Field data-invalid={error ? true : undefined}>
          <FieldLabel htmlFor="webhook-url">URL</FieldLabel>
          <Input
            id="webhook-url"
            type="url"
            dir="ltr"
            autoComplete="off"
            placeholder="https://hooks.example.org/justforms"
            value={url}
            aria-invalid={error ? true : undefined}
            onChange={(e) => {
              setUrl(e.target.value)
              setError(null)
            }}
          />
          <FieldDescription>Must start with https://. Addresses on private networks need the install's allowlist.</FieldDescription>
          {error && <FieldError>{error}</FieldError>}
        </Field>
        <FieldSet data-invalid={eventsError ? true : undefined}>
          <FieldLegend variant="label">Events</FieldLegend>
          <FieldGroup data-slot="checkbox-group" className="gap-3">
            {EVENTS.map((ev) => (
              <Field key={ev} orientation="horizontal">
                <Checkbox
                  id={`event-${ev}`}
                  checked={events.includes(ev)}
                  onCheckedChange={(on) => {
                    setEventsError(null)
                    setEvents((list) => (on ? [...list, ev] : list.filter((x) => x !== ev)))
                  }}
                />
                <FieldContent>
                  <FieldLabel htmlFor={`event-${ev}`} className="font-normal">
                    {EVENT_LABELS[ev]}
                  </FieldLabel>
                  <FieldDescription className="font-mono text-xs">{ev}</FieldDescription>
                </FieldContent>
              </Field>
            ))}
          </FieldGroup>
          {eventsError && <FieldError>{eventsError}</FieldError>}
        </FieldSet>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor="webhook-sensitive">Include sensitive answers</FieldLabel>
            <FieldDescription>Off: sensitive answers arrive as [redacted].</FieldDescription>
          </FieldContent>
          <Switch id="webhook-sensitive" checked={sensitive} onCheckedChange={setSensitive} />
        </Field>
      </FieldGroup>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {initial ? 'Save webhook' : 'Add webhook'}
        </Button>
      </DialogFooter>
    </form>
  )
}
