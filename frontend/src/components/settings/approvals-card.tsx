/**
 * "Approvals" (APPROVALS-SCREENS 1): up to three ordered approval steps, each with a name and
 * an approver taken from an email question or a fixed address, or decided only in the studio by
 * people with edit access (who can be told by email); the wording of the approver's email, and
 * the outcome email.
 * Edited locally and saved together ("Save approvals"), because a step is several fields.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDownIcon, ChevronUpIcon, MailIcon, PlusIcon, Trash2Icon, TriangleAlertIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSeparator,
  FieldSet,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  api,
  ApiError,
  type ApprovalConfig,
  type ApprovalIssue,
  type ApprovalStepConfig,
  type Approvals,
  type ApproverSource,
  type FormSummary,
} from '@/lib/api'
import { contentProps } from '@/schema/language'

import { PLACEHOLDER_HELP } from './email-wording'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MAX_STEPS = 3
const MAX_NOTIFY = 10

/** "a@x.org, b@y.org" → lower-case addresses without repeats. */
function parseList(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/[,;\s]+/)
        .map((x) => x.trim().toLowerCase())
        .filter(Boolean),
    ),
  ]
}
const CONFIRMED = '__confirmed__'

function newStep(a: Approvals): ApprovalStepConfig {
  const first = a.emailFields[0]?.id ?? null
  return { name: '', source: first ? 'field' : 'fixed', fieldId: first, email: null }
}

/** Errors found before saving, keyed by step (1-based). */
function localErrors(c: ApprovalConfig): Map<number, string> {
  const out = new Map<number, string>()
  if (!c.enabled) return out
  c.steps.forEach((s, i) => {
    if (!s.name.trim()) out.set(i + 1, 'Give the step a name, like Supervisor')
    else if (s.source === 'field' && !s.fieldId) out.set(i + 1, 'Choose a question')
    else if (s.source === 'fixed' && !EMAIL.test(s.email?.trim() ?? ''))
      out.set(i + 1, 'Enter an email address like name@example.org')
    else if (s.source === 'editors' && (s.notify ?? []).some((x) => !EMAIL.test(x)))
      out.set(i + 1, 'Enter email addresses like name@example.org, separated by commas')
    else if (s.source === 'editors' && (s.notify ?? []).length > MAX_NOTIFY)
      out.set(i + 1, `Enter up to ${MAX_NOTIFY} addresses`)
  })
  return out
}

type WordingKey = 'requestSubject' | 'requestMessage' | 'outcomeApprovedMessage' | 'outcomeRejectedMessage' | 'outcomeReplyTo'

/** Server issue fields (snake_case) to the settings they belong to. */
const ISSUE_FIELDS: Record<string, WordingKey> = {
  request_subject: 'requestSubject',
  request_message: 'requestMessage',
  outcome_approved_message: 'outcomeApprovedMessage',
  outcome_rejected_message: 'outcomeRejectedMessage',
  outcome_reply_to: 'outcomeReplyTo',
}

/** A wording setting of the approval emails: plain text, saved with the rest of the card. */
function WordingField({
  id,
  label,
  description,
  value,
  placeholder,
  multiline,
  email,
  disabled,
  error,
  onChange,
}: {
  id: string
  label: string
  description: string
  value: string | null | undefined
  placeholder?: string
  multiline?: boolean
  email?: boolean
  disabled: boolean
  error?: string
  onChange: (next: string) => void
}) {
  const common = {
    id,
    value: value ?? '',
    placeholder,
    disabled,
    'aria-invalid': error ? true : undefined,
  }
  return (
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {multiline ? (
        <Textarea {...common} dir="auto" rows={3} maxLength={5000} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <Input
          {...common}
          type="text"
          dir={email ? 'ltr' : 'auto'}
          inputMode={email ? 'email' : undefined}
          maxLength={email ? 320 : 200}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      <FieldDescription>{description}</FieldDescription>
      {error && <FieldError>{error}</FieldError>}
    </Field>
  )
}

function IconAction({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button type="button" variant="ghost" size="icon-sm" aria-label={label} disabled={disabled} onClick={onClick}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

function StepEditor({
  step,
  n,
  total,
  a,
  disabled,
  error,
  warnings,
  onChange,
  onMove,
  onRemove,
}: {
  step: ApprovalStepConfig
  n: number
  total: number
  a: Approvals
  disabled: boolean
  error?: string
  warnings: ApprovalIssue[]
  onChange: (s: ApprovalStepConfig) => void
  onMove: (by: -1 | 1) => void
  onRemove: () => void
}) {
  const id = `approval-step-${n}`
  const noQuestions = a.emailFields.length === 0
  // What was typed in "Notify", kept while it still means the step's list (moving or
  // discarding a step shows that step's own list again).
  const [notifyText, setNotifyText] = useState<string | null>(null)
  const notify = step.notify ?? []
  const shownNotify =
    notifyText !== null && parseList(notifyText).join(',') === notify.join(',') ? notifyText : notify.join(', ')
  return (
    <FieldSet className="gap-4 rounded-md border p-4" data-invalid={error ? true : undefined}>
      <div className="flex items-center gap-1">
        <FieldLegend variant="label" className="mb-0">
          Step {n}
        </FieldLegend>
        <div className="ms-auto flex gap-1">
          <IconAction label="Move up" disabled={disabled || n === 1} onClick={() => onMove(-1)}>
            <ChevronUpIcon />
          </IconAction>
          <IconAction label="Move down" disabled={disabled || n === total} onClick={() => onMove(1)}>
            <ChevronDownIcon />
          </IconAction>
          <IconAction label="Remove step" disabled={disabled} onClick={onRemove}>
            <Trash2Icon />
          </IconAction>
        </div>
      </div>
      <Field>
        <FieldLabel htmlFor={`${id}-name`}>Step name</FieldLabel>
        <Input
          id={`${id}-name`}
          {...contentProps(a.language)}
          maxLength={60}
          placeholder={a.language === 'en' ? 'Supervisor' : undefined}
          value={step.name}
          disabled={disabled}
          onChange={(e) => onChange({ ...step, name: e.target.value })}
        />
        <FieldDescription>Approvers and respondents see this name.</FieldDescription>
      </Field>
      <FieldSet>
        <FieldLegend variant="label">Approver</FieldLegend>
        <RadioGroup
          value={step.source}
          disabled={disabled}
          onValueChange={(v) =>
            onChange({
              ...step,
              source: v as ApproverSource,
              fieldId: v === 'field' ? (step.fieldId ?? a.emailFields[0]?.id ?? null) : step.fieldId,
            })
          }
          className="gap-4"
        >
          <div className="flex flex-col gap-2">
            <Field orientation="horizontal" data-disabled={noQuestions ? true : undefined}>
              <RadioGroupItem value="field" id={`${id}-field`} disabled={noQuestions} />
              <FieldContent>
                <FieldLabel htmlFor={`${id}-field`} className="font-normal">
                  The answer to an email question
                </FieldLabel>
                {noQuestions && <FieldDescription>Add an email question to the form to use this.</FieldDescription>}
              </FieldContent>
            </Field>
            {step.source === 'field' && !noQuestions && (
              <div className="ps-7">
                <NativeSelect
                  aria-label={`Email question for step ${n}`}
                  value={step.fieldId ?? ''}
                  disabled={disabled}
                  {...contentProps(a.language)}
                  onChange={(e) => onChange({ ...step, fieldId: e.target.value || null })}
                >
                  {!step.fieldId && (
                    <NativeSelectOption value="" lang="en" dir="ltr">
                      Choose a question
                    </NativeSelectOption>
                  )}
                  {step.fieldId && !a.emailFields.some((f) => f.id === step.fieldId) && (
                    <NativeSelectOption value={step.fieldId} lang="en" dir="ltr">
                      Deleted question ({step.fieldId})
                    </NativeSelectOption>
                  )}
                  {a.emailFields.map((f) => (
                    <NativeSelectOption key={f.id} value={f.id}>
                      {f.label || f.id}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </div>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <Field orientation="horizontal">
              <RadioGroupItem value="fixed" id={`${id}-fixed`} />
              <FieldLabel htmlFor={`${id}-fixed`} className="font-normal">
                Always this address
              </FieldLabel>
            </Field>
            {step.source === 'fixed' && (
              <div className="ps-7">
                <Input
                  aria-label={`Approver email for step ${n}`}
                  type="email"
                  dir="ltr"
                  inputMode="email"
                  placeholder="name@example.org"
                  value={step.email ?? ''}
                  disabled={disabled}
                  onChange={(e) => onChange({ ...step, email: e.target.value })}
                />
              </div>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <Field orientation="horizontal">
              <RadioGroupItem value="editors" id={`${id}-editors`} />
              <FieldContent>
                <FieldLabel htmlFor={`${id}-editors`} className="font-normal">
                  People with edit access, in the studio
                </FieldLabel>
                <FieldDescription>
                  Editors and owners of this form approve or reject it here after signing in. No emailed link or code.
                </FieldDescription>
              </FieldContent>
            </Field>
            {step.source === 'editors' && (
              <FieldGroup className="gap-4 ps-7">
                <Field>
                  <FieldLabel htmlFor={`${id}-notify`}>Notify</FieldLabel>
                  <Input
                    id={`${id}-notify`}
                    type="text"
                    dir="ltr"
                    inputMode="email"
                    autoComplete="off"
                    placeholder="team@example.org"
                    value={shownNotify}
                    disabled={disabled}
                    onChange={(e) => {
                      setNotifyText(e.target.value)
                      onChange({ ...step, notify: parseList(e.target.value) })
                    }}
                    onBlur={() => setNotifyText(null)}
                  />
                  <FieldDescription>
                    Up to {MAX_NOTIFY} addresses, separated by commas, for example a shared mailbox. They get a "New
                    response to review" email with a link to sign in; they can't decide from the email.
                  </FieldDescription>
                </Field>
                <Field orientation="horizontal">
                  <FieldContent>
                    <FieldLabel htmlFor={`${id}-notify-editors`}>Also email people with edit access</FieldLabel>
                    <FieldDescription>Each editor and owner of the form gets the same email.</FieldDescription>
                  </FieldContent>
                  <Switch
                    id={`${id}-notify-editors`}
                    checked={step.notifyEditors ?? false}
                    disabled={disabled}
                    onCheckedChange={(on) => onChange({ ...step, notifyEditors: on })}
                  />
                </Field>
              </FieldGroup>
            )}
          </div>
        </RadioGroup>
      </FieldSet>
      {error && <FieldError>{error}</FieldError>}
      {warnings.map((w) => (
        <Alert key={w.code}>
          <TriangleAlertIcon />
          <AlertDescription>{w.message}</AlertDescription>
        </Alert>
      ))}
    </FieldSet>
  )
}

export function ApprovalsCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const queryClient = useQueryClient()
  const key = ['approvals', form.id]
  const data = useQuery({ queryKey: key, queryFn: () => api.getApprovals(form.id) })
  const [edit, setEdit] = useState<ApprovalConfig | null>(null)
  const [errors, setErrors] = useState<Map<number, string>>(new Map())
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<WordingKey, string>>>({})
  const test = useMutation({
    mutationFn: () => api.testApprovals(form.id),
    onSuccess: (res) => {
      void queryClient.invalidateQueries({ queryKey: ['notifications', form.id] })
      toast(`Test emails sent to ${res.to}`)
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError && err.status === 429
          ? 'You sent test emails a few times already. Try again in an hour.'
          : "Couldn't send the test emails. Try again.",
      ),
  })
  const save = useMutation({
    mutationFn: (c: ApprovalConfig) => api.putApprovals(form.id, c),
    onSuccess: (next) => {
      queryClient.setQueryData(key, next)
      void queryClient.invalidateQueries({ queryKey: ['approval-problems', form.id] })
      setEdit(null)
      setErrors(new Map())
      setFieldErrors({})
      toast('Approvals saved')
    },
    onError: (err) => {
      const issues = err instanceof ApiError ? (err.body as { issues?: ApprovalIssue[] } | null)?.issues : undefined
      if (err instanceof ApiError && err.status === 422 && !issues?.length) {
        // A malformed Reply-To address is refused by the request model itself.
        return setFieldErrors({ outcomeReplyTo: 'Enter an email address like name@example.org' })
      }
      if (!issues?.length) return toast.error("Couldn't save. Try again.")
      const byField = Object.fromEntries(
        issues.filter((i) => i.field && ISSUE_FIELDS[i.field]).map((i) => [ISSUE_FIELDS[i.field!], i.message]),
      )
      setFieldErrors(byField)
      setErrors(new Map(issues.filter((i) => !i.field).map((i) => [i.step, i.message])))
    },
  })

  const header = (
    <CardHeader>
      <CardTitle>Approvals</CardTitle>
      <CardDescription>
        Send each new response to people who approve or reject it, in order. Approvers by email confirm their address
        with a code and don't need an account; a step can also be decided only here, by people with edit access.
        Changes save when you choose Save approvals.
      </CardDescription>
    </CardHeader>
  )
  if (!data.data)
    return (
      <Card className="rounded-md border shadow-none ring-0">
        {header}
        <CardContent>
          {data.isError ? (
            <p className="text-sm text-destructive">Couldn't load approvals. Reload the page to try again.</p>
          ) : (
            <Skeleton className="h-24" />
          )}
        </CardContent>
      </Card>
    )

  const a = data.data
  const c = edit ?? a.config
  const dirty = edit !== null
  const disabled = !canManage || save.isPending
  const set = (next: ApprovalConfig) => {
    setEdit(next)
    setErrors(new Map())
    setFieldErrors({})
  }
  const setText = (key: WordingKey) => (value: string) => set({ ...c, [key]: value })
  const setStep = (i: number, s: ApprovalStepConfig) => set({ ...c, steps: c.steps.map((x, j) => (j === i ? s : x)) })
  const move = (i: number, by: -1 | 1) => {
    const steps = [...c.steps]
    ;[steps[i], steps[i + by]] = [steps[i + by], steps[i]]
    set({ ...c, steps })
  }
  const confirmedAvailable = form.accessMode !== 'public'
  const outcomeTarget = c.respondentEmailField ?? (confirmedAvailable ? CONFIRMED : '')
  const outcomePossible = confirmedAvailable || a.emailFields.length > 0
  // Which emails the steps send: the approver's (link and code) and/or the "to review" notice.
  const byEmail = c.steps.some((s) => s.source !== 'editors')
  const byStudio = c.steps.some((s) => s.source === 'editors')
  const savedByEmail = a.config.steps.some((s) => s.source !== 'editors')
  const savedByStudio = a.config.steps.some((s) => s.source === 'editors')
  // Warnings describe the saved settings; hide them while editing.
  const warnings = (n: number) => (dirty ? [] : a.issues.filter((i) => i.step === n && i.level === 'warning'))

  return (
    <Card className="rounded-md border shadow-none ring-0">
      {header}
      <CardContent className="flex flex-col gap-5">
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor="approvals-on">Ask for approval</FieldLabel>
            <FieldDescription>New responses stay In review until the last step decides.</FieldDescription>
          </FieldContent>
          <Switch
            id="approvals-on"
            checked={c.enabled}
            disabled={disabled}
            onCheckedChange={(on) => set({ ...c, enabled: on, steps: on && !c.steps.length ? [newStep(a)] : c.steps })}
          />
        </Field>
        {c.enabled && (
          <>
            <div className="flex flex-col gap-3">
              {c.steps.map((s, i) => (
                <StepEditor
                  key={i}
                  step={s}
                  n={i + 1}
                  total={c.steps.length}
                  a={a}
                  disabled={disabled}
                  error={errors.get(i + 1)}
                  warnings={warnings(i + 1)}
                  onChange={(next) => setStep(i, next)}
                  onMove={(by) => move(i, by)}
                  onRemove={() => set({ ...c, steps: c.steps.filter((_, j) => j !== i) })}
                />
              ))}
              {c.steps.length < MAX_STEPS && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="self-start"
                  disabled={disabled}
                  onClick={() => set({ ...c, steps: [...c.steps, newStep(a)] })}
                >
                  <PlusIcon />
                  Add step
                </Button>
              )}
              {errors.get(0) && <FieldError>{errors.get(0)}</FieldError>}
            </div>
            <FieldSeparator />
            <FieldSet className="gap-4">
              <FieldLegend variant="label">{byEmail ? "The approver's email" : 'The "to review" email'}</FieldLegend>
              <FieldDescription>
                {byEmail &&
                  'It has Approve and Reject buttons. Each opens the response with that choice made; the approver confirms their email with a code and then their decision, so opening the email alone changes nothing.'}
                {byEmail && byStudio && ' '}
                {byStudio &&
                  `${byEmail ? 'Steps decided in the studio send the same wording as a "New response to review" email' : 'Steps decided in the studio send it to their Notify addresses'}, with a button that opens the submission after signing in. No Approve or Reject buttons and no code.`}
              </FieldDescription>
              <WordingField
                id="approvals-request-subject"
                label="Subject"
                description={`Leave empty for "${byEmail ? 'Approval needed' : 'New response to review'}: {form_title} ({reference})". ${PLACEHOLDER_HELP}`}
                placeholder={`${byEmail ? 'Approval needed' : 'New response to review'}: {form_title} ({reference})`}
                value={c.requestSubject}
                disabled={disabled}
                error={fieldErrors.requestSubject}
                onChange={setText('requestSubject')}
              />
              <WordingField
                id="approvals-request-message"
                label="Message"
                description={`${byEmail ? 'Shown above the buttons' : 'Replaces the built-in sentence'}, for example who applied. Plain text. ${PLACEHOLDER_HELP}`}
                value={c.requestMessage}
                multiline
                disabled={disabled}
                error={fieldErrors.requestMessage}
                onChange={setText('requestMessage')}
              />
              <Field orientation="horizontal">
                <FieldContent>
                  <FieldLabel htmlFor="approvals-request-answers">Include answers</FieldLabel>
                  <FieldDescription>Sensitive answers are never emailed.</FieldDescription>
                </FieldContent>
                <Switch
                  id="approvals-request-answers"
                  checked={c.requestIncludeAnswers ?? false}
                  disabled={disabled}
                  onCheckedChange={(on) => set({ ...c, requestIncludeAnswers: on })}
                />
              </Field>
            </FieldSet>
            <FieldSeparator />
            <FieldGroup className="gap-4">
              <Field orientation="horizontal" data-disabled={!outcomePossible ? true : undefined}>
                <FieldContent>
                  <FieldLabel htmlFor="approvals-outcome">Email the respondent the outcome</FieldLabel>
                  <FieldDescription>
                    {outcomePossible
                      ? 'The email has the final signed PDF attached.'
                      : 'Add an email question, or ask people to confirm their email, to send the outcome.'}
                  </FieldDescription>
                </FieldContent>
                <Switch
                  id="approvals-outcome"
                  checked={c.notifyRespondent && outcomePossible}
                  disabled={disabled || !outcomePossible}
                  onCheckedChange={(on) =>
                    set({
                      ...c,
                      notifyRespondent: on,
                      respondentEmailField: c.respondentEmailField ?? (confirmedAvailable ? null : (a.emailFields[0]?.id ?? null)),
                    })
                  }
                />
              </Field>
              {c.notifyRespondent && outcomePossible && (
                <Field className="ps-4">
                  <FieldLabel htmlFor="approvals-outcome-to">Send to</FieldLabel>
                  <NativeSelect
                    id="approvals-outcome-to"
                    value={outcomeTarget}
                    disabled={disabled}
                    {...contentProps(a.language)}
                    onChange={(e) => set({ ...c, respondentEmailField: e.target.value === CONFIRMED ? null : e.target.value })}
                  >
                    {confirmedAvailable && (
                      <NativeSelectOption value={CONFIRMED} lang="en" dir="ltr">
                        {form.accessMode === 'staff' ? 'The signed-in person' : 'The confirmed email'}
                      </NativeSelectOption>
                    )}
                    {a.emailFields.map((f) => (
                      <NativeSelectOption key={f.id} value={f.id}>
                        {f.label || f.id}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </Field>
              )}
              {c.notifyRespondent && outcomePossible && (
                <FieldGroup className="gap-4 ps-4">
                  <WordingField
                    id="approvals-outcome-approved"
                    label="Message when approved"
                    description={`Leave empty for "Your response {reference} was approved." The reference follows. Plain text. ${PLACEHOLDER_HELP}`}
                    value={c.outcomeApprovedMessage}
                    multiline
                    disabled={disabled}
                    error={fieldErrors.outcomeApprovedMessage}
                    onChange={setText('outcomeApprovedMessage')}
                  />
                  <WordingField
                    id="approvals-outcome-rejected"
                    label="Message when not approved"
                    description={`Leave empty for "Your response {reference} was not approved." The reference and the approver's comment follow. Plain text. ${PLACEHOLDER_HELP}`}
                    value={c.outcomeRejectedMessage}
                    multiline
                    disabled={disabled}
                    error={fieldErrors.outcomeRejectedMessage}
                    onChange={setText('outcomeRejectedMessage')}
                  />
                  <WordingField
                    id="approvals-outcome-reply-to"
                    label="Reply-to address"
                    description="Replies to the outcome email go here. Leave empty to use the sender address."
                    placeholder="team@example.org"
                    value={c.outcomeReplyTo}
                    email
                    disabled={disabled}
                    error={fieldErrors.outcomeReplyTo}
                    onChange={setText('outcomeReplyTo')}
                  />
                </FieldGroup>
              )}
            </FieldGroup>
          </>
        )}
        {canManage && (dirty || save.isPending) && (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button type="button" variant="ghost" disabled={save.isPending} onClick={() => (setEdit(null), setErrors(new Map()))}>
              Discard
            </Button>
            <Button
              type="button"
              disabled={save.isPending}
              onClick={() => {
                const local = localErrors(c)
                if (local.size) return setErrors(local)
                const replyTo = c.outcomeReplyTo?.trim().toLowerCase() || null
                if (replyTo && !EMAIL.test(replyTo))
                  return setFieldErrors({ outcomeReplyTo: 'Enter an email address like name@example.org' })
                save.mutate({
                  ...c,
                  steps: c.steps.map((s) => ({ ...s, name: s.name.trim(), email: s.email?.trim() || null })),
                  requestSubject: c.requestSubject?.trim() || null,
                  requestMessage: c.requestMessage?.trim() || null,
                  outcomeApprovedMessage: c.outcomeApprovedMessage?.trim() || null,
                  outcomeRejectedMessage: c.outcomeRejectedMessage?.trim() || null,
                  outcomeReplyTo: replyTo,
                })
              }}
            >
              {save.isPending && <Spinner />}
              Save approvals
            </Button>
          </div>
        )}
        {canManage && a.smtpEnabled && a.config.enabled && a.config.steps.length > 0 && !dirty && (
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor="approvals-test">Try the emails</FieldLabel>
              <FieldDescription>
                Sends {savedByEmail && savedByStudio ? `the approver's and the "to review" email` : savedByEmail ? "the approver's email" : 'the "to review" email'}
                {a.config.notifyRespondent ? ' and both outcome emails' : ''} to you only, with sample answers and [Test] in
                the subject. The buttons in the test open the submissions.
              </FieldDescription>
            </FieldContent>
            <Button id="approvals-test" type="button" variant="outline" size="sm" disabled={test.isPending} onClick={() => test.mutate()}>
              {test.isPending ? <Spinner /> : <MailIcon />}
              Send test emails
            </Button>
          </Field>
        )}
        {form.status === 'live' && c.enabled && (
          <p className="text-sm text-muted-foreground">
            Changes apply to new responses. Responses already waiting keep their steps.
          </p>
        )}
        {!a.smtpEnabled && c.enabled && (
          <Alert>
            <TriangleAlertIcon />
            <AlertDescription>
              Email isn't set up on this install, so {byEmail ? "approvers won't get their links" : 'nobody is emailed'}. An
              administrator can set the{' '}
              <code className="font-mono text-xs">JUSTFORMS_SMTP_*</code> settings.
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}
