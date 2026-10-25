/** Custom subject, opening text and Reply-To for one notification email (DESIGN 11.1). */
import { useState } from 'react'

import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ApiError, type NotificationRule } from '@/lib/api'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export const PLACEHOLDER_HELP = 'You can use {reference}, {form_title}, {submitted} and {answer:question_key}.'

function problem(e: unknown): string {
  if (e instanceof ApiError && e.status === 422) {
    const detail = e.detail as { code?: string; placeholder?: string } | string | undefined
    if (typeof detail === 'object' && detail?.code === 'unknown_placeholder')
      return `${detail.placeholder} can't be filled in. ${PLACEHOLDER_HELP} Sensitive, signature and file questions can't be used.`
    if (detail === 'subject_one_line') return 'Keep the subject on one line.'
    return 'Check this value and try again.'
  }
  return "Couldn't save. Try again."
}

function TextSetting({
  id,
  label,
  description,
  value,
  placeholder,
  multiline,
  email,
  disabled,
  onSave,
}: {
  id: string
  label: string
  description: string
  value: string | null
  placeholder?: string
  multiline?: boolean
  email?: boolean
  disabled: boolean
  onSave: (next: string | null) => Promise<unknown>
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const text = draft ?? value ?? ''

  const commit = async () => {
    if (draft === null) return
    const next = email ? draft.trim().toLowerCase() : draft.trim()
    if (email && next && !EMAIL.test(next)) return setError('Enter an email address like name@example.org')
    if (next === (value ?? '')) {
      setDraft(null)
      setError(null)
      return
    }
    try {
      await onSave(next || null)
      setDraft(null)
      setError(null)
    } catch (e) {
      setError(problem(e))
    }
  }

  const common = {
    id,
    value: text,
    placeholder,
    disabled,
    'aria-invalid': error ? true : undefined,
    onBlur: () => void commit(),
  }
  return (
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {multiline ? (
        <Textarea {...common} dir="auto" rows={4} onChange={(e) => setDraft(e.target.value)} />
      ) : (
        <Input
          {...common}
          dir={email ? 'ltr' : 'auto'}
          type="text"
          inputMode={email ? 'email' : undefined}
          onChange={(e) => setDraft(e.target.value)}
        />
      )}
      <FieldDescription>{description}</FieldDescription>
      {error && <FieldError>{error}</FieldError>}
    </Field>
  )
}

/** Subject, message and (optionally) Reply-To fields; each saves when it loses focus. */
export function EmailWording({
  idPrefix,
  rule,
  defaultSubject,
  messageHelp,
  replyTo,
  disabled,
  save,
}: {
  idPrefix: string
  rule: NotificationRule
  defaultSubject: string
  messageHelp: string
  replyTo?: boolean
  disabled: boolean
  save: (rule: NotificationRule) => Promise<unknown>
}) {
  return (
    <>
      <TextSetting
        id={`${idPrefix}-subject`}
        label="Subject"
        description={`Leave empty for "${defaultSubject}". ${PLACEHOLDER_HELP}`}
        value={rule.subject}
        placeholder={defaultSubject}
        disabled={disabled}
        onSave={(subject) => save({ ...rule, subject })}
      />
      <TextSetting
        id={`${idPrefix}-message`}
        label="Message"
        description={`${messageHelp} Plain text. ${PLACEHOLDER_HELP}`}
        value={rule.message}
        multiline
        disabled={disabled}
        onSave={(message) => save({ ...rule, message })}
      />
      {replyTo && (
        <TextSetting
          id={`${idPrefix}-reply-to`}
          label="Reply-to address"
          description="Replies to this email go here. Leave empty to use the sender address."
          value={rule.replyTo}
          placeholder="team@example.org"
          email
          disabled={disabled}
          onSave={(replyTo) => save({ ...rule, replyTo })}
        />
      )}
    </>
  )
}
