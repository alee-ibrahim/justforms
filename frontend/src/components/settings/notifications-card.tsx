/** "Email notifications" (PHASE-4-SCREENS 1.3): owner notification, respondent receipt, log. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckIcon, MailWarningIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { EmailWording } from '@/components/settings/email-wording'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldSeparator,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { api, ApiError, type EmailLogEntry, type FormSummary, type NotificationRule, type Notifications, type RuleType } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { contentProps } from '@/schema/language'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const CONFIRMED = '__confirmed__'
const MAX_RECIPIENTS = 10

function logTitle(e: EmailLogEntry): string {
  if (e.kind === 'test_owner_new') return `Test notification to ${e.to}`
  if (e.kind === 'test_receipt') return `Test receipt to ${e.to}`
  if (e.kind === 'receipt') return `Receipt to ${e.to}`
  if (e.kind === 'webhook_disabled') return `Webhook warning to ${e.to}`
  if (e.kind === 'approval_request') return `Approval request to ${e.to}`
  if (e.kind === 'approval_outcome') return `Approval outcome to ${e.to}`
  return `New response to ${e.to}`
}

function LogItem({ e }: { e: EmailLogEntry }) {
  const Icon = e.status === 'sent' ? CheckIcon : e.status === 'failed' ? XIcon : Spinner
  return (
    <Item size="sm" className="px-0">
      <ItemMedia variant="icon" className={e.status === 'failed' ? 'text-destructive' : undefined}>
        <Icon aria-hidden />
      </ItemMedia>
      <ItemContent className="min-w-0">
        <ItemTitle className="max-w-full break-all sm:truncate">
          <bdi dir="ltr">{logTitle(e)}</bdi>
        </ItemTitle>
        {e.status === 'failed' && (
          <ItemDescription className="text-destructive">
            Couldn't send{e.error ? `: ${e.error}` : ''}. JustForms tried {e.attempts} {e.attempts === 1 ? 'time' : 'times'}.
          </ItemDescription>
        )}
        {e.status === 'queued' && <ItemDescription>Queued</ItemDescription>}
        {/* Phones: the time goes under the address so the address isn't cut. */}
        <ItemDescription className="tabular-nums sm:hidden">{formatDateTime(e.sentAt ?? e.createdAt)}</ItemDescription>
      </ItemContent>
      <ItemActions className="text-sm tabular-nums text-muted-foreground max-sm:hidden">
        {formatDateTime(e.sentAt ?? e.createdAt)}
      </ItemActions>
    </Item>
  )
}

export function NotificationsCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const queryClient = useQueryClient()
  const key = ['notifications', form.id]
  const data = useQuery({ queryKey: key, queryFn: () => api.getNotifications(form.id) })
  const save = useMutation({
    mutationFn: ({ type, rule }: { type: RuleType; rule: NotificationRule }) => api.putNotification(form.id, type, rule),
    onSuccess: (next) => {
      queryClient.setQueryData(key, next)
      toast('Saved')
    },
    // 422s (a bad placeholder or address) are shown next to the field instead.
    onError: (e) => {
      if (!(e instanceof ApiError && e.status === 422)) toast.error("Couldn't save. Try again.")
    },
  })
  const test = useMutation({
    mutationFn: () => api.sendTestEmails(form.id),
    onSuccess: (next) => {
      queryClient.setQueryData(key, next)
      toast('Test emails are on their way to you')
    },
    onError: (e) =>
      toast.error(
        e instanceof ApiError && e.status === 429
          ? 'Too many test emails. Try again in an hour.'
          : "Couldn't send test emails. Try again.",
      ),
  })
  const [recipients, setRecipients] = useState<string | null>(null)
  const [recipientsError, setRecipientsError] = useState<string | null>(null)

  if (!data.data)
    return (
      <Card className="rounded-md border shadow-none ring-0">
        <CardHeader>
          <CardTitle>Email notifications</CardTitle>
        </CardHeader>
        <CardContent>
          {data.isError ? (
            <p className="text-sm text-destructive">Couldn't load email settings. Reload the page to try again.</p>
          ) : (
            <Skeleton className="h-24" />
          )}
        </CardContent>
      </Card>
    )

  const n: Notifications = data.data
  const owner = n.ownerEmail
  const receipt = n.respondentReceipt
  const disabled = !canManage || save.isPending
  const confirmedAvailable = form.accessMode !== 'public'
  const receiptTarget = receipt.emailField ?? (confirmedAvailable ? CONFIRMED : '')
  const receiptPossible = confirmedAvailable || n.emailFields.length > 0
  const put = (type: RuleType, rule: NotificationRule) => save.mutate({ type, rule })
  const saveRule = (type: RuleType) => (rule: NotificationRule) => save.mutateAsync({ type, rule })
  const recipientsText = recipients ?? owner.recipients.join(', ')

  return (
    <Card className="rounded-md border shadow-none ring-0">
      <CardHeader>
        <CardTitle>Email notifications</CardTitle>
        <CardDescription>
          Emails JustForms sends when a response arrives. Changes save as you make them.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {!n.smtpEnabled && (
          <Alert>
            <MailWarningIcon />
            <AlertTitle>Email isn't set up on this install</AlertTitle>
            <AlertDescription>
              Nothing will be sent. An administrator can set the <code className="font-mono text-xs">JUSTFORMS_SMTP_*</code>{' '}
              settings.
            </AlertDescription>
          </Alert>
        )}
        <FieldGroup className="gap-5">
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor="notify-owner">Email me about new responses</FieldLabel>
              <FieldDescription>A short summary with a link to the submission.</FieldDescription>
            </FieldContent>
            <Switch
              id="notify-owner"
              checked={owner.enabled}
              disabled={disabled}
              onCheckedChange={(on) => put('owner_email', { ...owner, enabled: on })}
            />
          </Field>
          {owner.enabled && (
            <FieldGroup className="gap-4 ps-4">
              <Field data-invalid={recipientsError ? true : undefined}>
                <FieldLabel htmlFor="notify-to">Send to</FieldLabel>
                <Input
                  id="notify-to"
                  dir="ltr"
                  type="text"
                  inputMode="email"
                  placeholder="owner@example.org, team@example.org"
                  value={recipientsText}
                  disabled={!canManage}
                  aria-invalid={recipientsError ? true : undefined}
                  onChange={(e) => setRecipients(e.target.value)}
                  onBlur={() => {
                    const list = recipientsText
                      .split(',')
                      .map((x) => x.trim().toLowerCase())
                      .filter(Boolean)
                    if (list.some((x) => !EMAIL.test(x)))
                      return setRecipientsError('Enter email addresses like name@example.org, separated by commas')
                    if (new Set(list).size > MAX_RECIPIENTS)
                      return setRecipientsError(`Enter up to ${MAX_RECIPIENTS} addresses`)
                    setRecipientsError(null)
                    setRecipients(null)
                    if (list.join(',') !== owner.recipients.join(',')) put('owner_email', { ...owner, recipients: list })
                  }}
                />
                <FieldDescription>
                  Up to {MAX_RECIPIENTS} addresses, inside or outside your organisation. Leave empty to email the form's
                  owners.
                </FieldDescription>
                {recipientsError && <FieldError>{recipientsError}</FieldError>}
              </Field>
              <Field orientation="horizontal">
                <FieldContent>
                  <FieldLabel htmlFor="notify-answers">Include answers</FieldLabel>
                  <FieldDescription>Sensitive answers are never emailed.</FieldDescription>
                </FieldContent>
                <Switch
                  id="notify-answers"
                  checked={owner.includeAnswers}
                  disabled={disabled}
                  onCheckedChange={(on) => put('owner_email', { ...owner, includeAnswers: on })}
                />
              </Field>
              <EmailWording
                idPrefix="notify"
                rule={owner}
                defaultSubject="New response to {form_title} ({reference})"
                messageHelp="Shown above the link to the submission."
                disabled={disabled}
                save={saveRule('owner_email')}
              />
            </FieldGroup>
          )}
          <FieldSeparator />
          <Field orientation="horizontal" data-disabled={!receiptPossible ? true : undefined}>
            <FieldContent>
              <FieldLabel htmlFor="notify-receipt">Send respondents a receipt</FieldLabel>
              <FieldDescription>
                {receiptPossible
                  ? 'A copy of their answers and the reference number.'
                  : 'Add an email question, or ask people to confirm their email, to send receipts.'}
              </FieldDescription>
            </FieldContent>
            <Switch
              id="notify-receipt"
              checked={receipt.enabled}
              disabled={disabled || (!receiptPossible && !receipt.enabled)}
              onCheckedChange={(on) =>
                put('respondent_receipt', {
                  ...receipt,
                  enabled: on,
                  emailField: receipt.emailField ?? (confirmedAvailable ? null : (n.emailFields[0]?.id ?? null)),
                })
              }
            />
          </Field>
          {receipt.enabled && (
            <FieldGroup className="gap-4 ps-4">
              <Field>
                <FieldLabel htmlFor="receipt-to">Send to</FieldLabel>
                <NativeSelect
                  id="receipt-to"
                  value={receiptTarget}
                  disabled={disabled}
                  {...contentProps(n.language)}
                  onChange={(e) =>
                    put('respondent_receipt', {
                      ...receipt,
                      emailField: e.target.value === CONFIRMED ? null : e.target.value,
                    })
                  }
                >
                  {confirmedAvailable && (
                    <NativeSelectOption value={CONFIRMED} lang="en" dir="ltr">
                      {form.accessMode === 'staff' ? 'The signed-in person' : 'The confirmed email'}
                    </NativeSelectOption>
                  )}
                  {!confirmedAvailable && !receipt.emailField && <NativeSelectOption value="">Choose a question</NativeSelectOption>}
                  {n.emailFields.map((f) => (
                    <NativeSelectOption key={f.id} value={f.id}>
                      {f.label || f.id}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </Field>
              <Field orientation="horizontal" data-disabled={!n.hasSignature ? true : undefined}>
                <FieldContent>
                  <FieldLabel htmlFor="receipt-pdf">Attach the signed PDF</FieldLabel>
                  <FieldDescription>
                    {n.hasSignature
                      ? 'The receipt waits until the PDF is ready.'
                      : 'Only for forms with a signature question.'}
                  </FieldDescription>
                </FieldContent>
                <Switch
                  id="receipt-pdf"
                  checked={receipt.attachPdf}
                  disabled={disabled || (!n.hasSignature && !receipt.attachPdf)}
                  onCheckedChange={(on) => put('respondent_receipt', { ...receipt, attachPdf: on })}
                />
              </Field>
              <EmailWording
                idPrefix="receipt"
                rule={receipt}
                defaultSubject="Your response to {form_title} ({reference})"
                messageHelp="Replaces the opening thank-you (or the form's success message). The reference and their answers follow."
                replyTo
                disabled={disabled}
                save={saveRule('respondent_receipt')}
              />
            </FieldGroup>
          )}
        </FieldGroup>
        {form.role === 'owner' && n.smtpEnabled && (owner.enabled || receipt.enabled) && (
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor="notify-test">Send test emails</FieldLabel>
              <FieldDescription>
                Both emails, filled with sample answers and marked [Test], go to you only. No PDF is attached.
              </FieldDescription>
            </FieldContent>
            <Button id="notify-test" variant="outline" disabled={test.isPending} onClick={() => test.mutate()}>
              {test.isPending && <Spinner data-icon="inline-start" />}
              Send to me
            </Button>
          </Field>
        )}
        {form.role === 'owner' && (
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">Recent emails</h3>
            {n.recent.length === 0 ? (
              <p className="text-sm text-muted-foreground">No emails sent yet.</p>
            ) : (
              <ItemGroup className="gap-0">
                {n.recent.map((e) => (
                  <LogItem key={e.id} e={e} />
                ))}
              </ItemGroup>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
