/**
 * Approver page (`/a/{token}`, APPROVALS-SCREENS 4). Lazy chunk of the document entry. The
 * approver confirms the address the link was sent to with a one-time code, reads the response
 * (sensitive answers hidden), and approves or rejects. The page is system text, so English and
 * left to right for every form; the form's title, questions and answers take the form's language
 * and direction. The session token lives in memory only.
 */
import { DownloadIcon, FileIcon, InfoIcon, LockIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

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
import { Card, CardContent } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { answerText } from '@/components/submissions/format'
import { applyBrand, type Brand } from '@/lib/branding'
import { loadThaanaFont } from '@/lib/thaana-font'
import { formatSize } from '@/renderer/util'
import { En, Msg } from '@/renderer/msg'
import type { Element, FieldElement, Form, FormLanguage } from '@/schema'
import { contentProps } from '@/schema/language'
import { displayText } from '@/thaana/display'

import { APPROVER as msgs } from './approver-messages'
import { formatDay, scriptLang } from './messages'
import { Page } from './page'

interface LinkInfo {
  state: 'pending' | 'approved' | 'rejected' | 'stopped'
  language: FormLanguage
  orgName: string
  brand?: Brand
  formTitle: string
  reference: string
  submittedAt: string
  step: number
  total: number
  stepName: string
  maskedEmail: string
  decidedAt: string | null
  decidedName?: string | null
  decidedVia?: 'email' | 'studio' | null
  codeMinutes: number
  thaanaFontCssUrl: string
}

interface ApproverView {
  schema: Form
  data: Record<string, unknown>
  hidden: string[]
  files: Record<string, { name: string; size: number; mime: string }>
  signatures: string[]
  steps: { step: number; name: string; state: string; decidedName: string | null; decidedAt: string | null }[]
  current: number
}

type Decision = 'approve' | 'reject'

/** The decision chosen with the email's Approve / Reject button (`?decision=`), if any. */
function intentFromUrl(search: string): Decision | null {
  const v = new URLSearchParams(search).get('decision')
  return v === 'approve' || v === 'reject' ? v : null
}

/** The approver's name, remembered on this device for the next approval. */
const NAME_KEY = 'justforms:approver-name'
function rememberedName(): string {
  try {
    return window.localStorage.getItem(NAME_KEY) ?? ''
  } catch {
    return ''
  }
}
function rememberName(name: string) {
  try {
    window.localStorage.setItem(NAME_KEY, name)
  } catch {
    // Storage may be off; the name is only a convenience.
  }
}

type Stage =
  | { kind: 'loading' }
  | { kind: 'invalid' }
  | { kind: 'error' }
  | { kind: 'intro' }
  | { kind: 'code' }
  | { kind: 'review'; bearer: string; view: ApproverView }
  | { kind: 'done'; approved: boolean }

/**
 * A question label: ink, not muted, and never smaller than its answer. Inside a Dhivehi form the
 * `:lang(dv)` scale makes it Thaana `text-lg` at weight 400 (Faruma has one weight, synthetic bold
 * is muddy at this size); in English it is `text-base` semibold over a `text-base` answer.
 */
const LABEL = 'text-base font-semibold [&:lang(dv)]:text-lg [&:lang(dv)]:font-normal'

/** Left-to-right answers: Latin data, and Yes / No (system words, English for every form). */
const LATIN = new Set(['email', 'phone', 'number', 'date', 'time', 'yes_no'])

function base(token: string) {
  return `/api/v1/public/approvals/${encodeURIComponent(token)}`
}

async function call(token: string, path: string, init: RequestInit = {}, bearer?: string): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (init.body) headers['Content-Type'] = 'application/json'
  if (bearer) headers.Authorization = `Bearer ${bearer}`
  return fetch(`${base(token)}${path}`, { ...init, headers, referrerPolicy: 'no-referrer' })
}

/** Download a file or image with the approver's bearer token, as an object URL. */
async function blobUrl(token: string, path: string, bearer: string): Promise<string | null> {
  const res = await call(token, path, {}, bearer)
  return res.ok ? URL.createObjectURL(await res.blob()) : null
}

function Status({ title, body }: { title: string; body: ReactNode }) {
  return (
    <Empty className="flex-none items-start justify-start p-0 text-start">
      <EmptyHeader className="items-start">
        <EmptyMedia variant="icon">
          <InfoIcon />
        </EmptyMedia>
        <EmptyTitle>
          <h1 className="text-xl font-semibold outline-none" tabIndex={-1} ref={(el) => el?.focus()}>
            {title}
          </h1>
        </EmptyTitle>
        <EmptyDescription className="text-base">{body}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

function Header({ info }: { info: LinkInfo }) {
  return (
    <header className="flex flex-col gap-1">
      {info.orgName && !info.brand?.logoUrl && (
        <p className="text-sm text-muted-foreground" lang={scriptLang(info.orgName)}>
          {info.orgName}
        </p>
      )}
      <p className="text-2xl font-bold" {...contentProps(info.language)}>
        {displayText(info.formTitle, info.language)}
      </p>
    </header>
  )
}

function StepIntro({ info, headingRef }: { info: LinkInfo; headingRef?: React.Ref<HTMLHeadingElement> }) {
  return (
    <div className="flex flex-col gap-1">
      <h1 ref={headingRef} tabIndex={-1} className="text-xl font-semibold outline-none">
        <Msg t={msgs.approvalNeeded} params={{ step: <bdi dir="auto">{info.stepName}</bdi> }} />
      </h1>
      <p className="text-muted-foreground">
        <Msg
          t={msgs.responseLine}
          params={{
            ref: info.reference,
            date: formatDay(info.submittedAt),
            n: info.step,
            total: info.total,
          }}
        />
      </p>
    </div>
  )
}

function CodeStep({
  token,
  info,
  intent,
  onVerified,
  onDone,
}: {
  token: string
  info: LinkInfo
  intent: Decision | null
  onVerified: (bearer: string) => void
  onDone: () => void
}) {
  const [sent, setSent] = useState(false)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [wait, setWait] = useState(0)
  const [announce, setAnnounce] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (wait <= 0) return
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000)
    return () => window.clearTimeout(t)
  }, [wait])
  useEffect(() => heading.current?.focus(), [sent])

  const send = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await call(token, '/code', { method: 'POST' })
      if (res.status === 409) return onDone()
      if (res.status === 429) return setError(msgs.tooMany)
      if (!res.ok) return setError(msgs.failed)
      setSent(true)
      setCode('')
      setWait(60)
      setAnnounce(msgs.codeAnnounce)
    } catch {
      setError(msgs.failed)
    } finally {
      setBusy(false)
    }
  }

  const verify = async (value: string) => {
    if (busy || value.length !== 6) return
    setBusy(true)
    setError(null)
    try {
      const res = await call(token, '/verify', { method: 'POST', body: JSON.stringify({ code: value }) })
      const body = (await res.json().catch(() => null)) as { token?: string; detail?: string } | null
      if (res.ok && body?.token) return onVerified(body.token)
      if (res.status === 409) return onDone()
      setCode('')
      setError(res.status === 429 ? msgs.tooMany : body?.detail === 'code_expired' ? msgs.codeExpired : msgs.codeWrong)
    } catch {
      setError(msgs.failed)
    } finally {
      setBusy(false)
    }
  }

  const time = `${Math.floor(wait / 60)}:${String(wait % 60).padStart(2, '0')}`
  return (
    <div className="flex flex-col gap-6">
      {!sent ? (
        <form
          className="flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            void send()
          }}
        >
          <StepIntro info={info} headingRef={heading} />
          {intent && <p className="font-medium">{intent === 'approve' ? msgs.intentApprove : msgs.intentReject}</p>}
          <p>
            <Msg t={msgs.confirmIntro} params={{ email: info.maskedEmail }} />
          </p>
          {error && <FieldError>{error}</FieldError>}
          <Button type="submit" className="h-12 text-base max-md:w-full md:self-start" disabled={busy}>
            {busy && <Spinner />}
            {msgs.sendCode}
          </Button>
        </form>
      ) : (
        <form
          className="flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            void verify(code)
          }}
        >
          <div className="flex flex-col gap-1">
            <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold outline-none">
              {msgs.enterCode}
            </h1>
            <p className="text-muted-foreground">
              <Msg t={msgs.codeSent} params={{ email: info.maskedEmail, minutes: info.codeMinutes }} />
            </p>
          </div>
          <Field data-invalid={error ? true : undefined}>
            <FieldLabel htmlFor="approver-code" className="sr-only">
              {msgs.codeLabel}
            </FieldLabel>
            <div dir="ltr" className="self-start">
              <InputOTP
                id="approver-code"
                maxLength={6}
                value={code}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="^[0-9]*$"
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? 'approver-code-error' : undefined}
                autoFocus
                onChange={(v) => {
                  setCode(v)
                  setError(null)
                }}
                onComplete={(v: string) => void verify(v)}
              >
                <InputOTPGroup>
                  {Array.from({ length: 6 }, (_, i) => (
                    <InputOTPSlot key={i} index={i} className="size-12 text-lg" />
                  ))}
                </InputOTPGroup>
              </InputOTP>
            </div>
            {error && <FieldError id="approver-code-error">{error}</FieldError>}
          </Field>
          <Button type="submit" className="h-12 text-base max-md:w-full md:self-start" disabled={busy || code.length !== 6}>
            {busy && <Spinner />}
            {msgs.continue}
          </Button>
          <Button type="button" variant="link" className="h-11 self-start px-0" disabled={wait > 0 || busy} onClick={() => void send()}>
            {wait > 0 ? <Msg t={msgs.resendIn} params={{ time }} /> : msgs.resend}
          </Button>
        </form>
      )}
      <span className="sr-only" aria-live="polite">
        {announce}
      </span>
    </div>
  )
}

function FileRow({ token, bearer, fileId, view }: { token: string; bearer: string; fileId: string; view: ApproverView }) {
  const f = view.files[fileId]
  const [busy, setBusy] = useState(false)
  if (!f) return null
  return (
    <Item variant="outline" size="sm" className="flex-nowrap" lang="en" dir="ltr">
      <ItemMedia variant="icon">
        <FileIcon />
      </ItemMedia>
      <ItemContent className="min-w-0">
        <ItemTitle className="max-w-full">
          <bdi dir="auto" className="truncate">
            {f.name}
          </bdi>
        </ItemTitle>
        <ItemDescription className="tabular-nums">{formatSize(f.size)}</ItemDescription>
      </ItemContent>
      <ItemActions>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-11"
          aria-label={msgs.download.replace('{name}', f.name)}
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            const url = await blobUrl(token, `/files/${fileId}`, bearer)
            setBusy(false)
            if (!url) return
            const a = document.createElement('a')
            a.href = url
            a.download = f.name
            a.click()
            window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
          }}
        >
          {busy ? <Spinner /> : <DownloadIcon />}
        </Button>
      </ItemActions>
    </Item>
  )
}

function SignatureImage({ token, bearer, fieldId }: { token: string; bearer: string; fieldId: string }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    let made: string | null = null
    void blobUrl(token, `/signatures/${fieldId}`, bearer).then((u) => {
      made = u
      if (alive) setUrl(u)
    })
    return () => {
      alive = false
      if (made) URL.revokeObjectURL(made)
    }
  }, [token, bearer, fieldId])
  return (
    <Card className="max-w-md gap-0 overflow-hidden border-input bg-paper py-0">
      <CardContent className="relative min-h-24 p-0">
        {url && <img src={url} alt={msgs.signatureAlt} className="block w-full" />}
        <div className="pointer-events-none absolute inset-x-6 top-[70%] border-t border-paper-ink/25" />
      </CardContent>
    </Card>
  )
}

function Value({
  field,
  value,
  ctx,
}: {
  field: FieldElement
  value: unknown
  ctx: { token: string; bearer: string; view: ApproverView; language: FormLanguage }
}) {
  const { view, language } = ctx
  if (view.hidden.includes(field.id))
    return (
      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
        <LockIcon className="size-4" aria-hidden />
        <En>{msgs.hidden}</En>
      </span>
    )
  if (field.type === 'signature' && view.signatures.includes(field.id))
    return <SignatureImage token={ctx.token} bearer={ctx.bearer} fieldId={field.id} />
  if (value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length))
    return (
      <span className="text-muted-foreground">
        <En>{msgs.noAnswer}</En>
      </span>
    )
  if (field.type === 'file' && Array.isArray(value))
    return (
      <ItemGroup className="gap-2">
        {(value as { fileId: string }[]).map((f) => (
          <FileRow key={f.fileId} token={ctx.token} bearer={ctx.bearer} fileId={f.fileId} view={view} />
        ))}
      </ItemGroup>
    )
  const text = answerText(field, value, language)
  return LATIN.has(field.type) ? (
    <bdi dir="ltr">{text}</bdi>
  ) : (
    <span className="whitespace-pre-wrap">{displayText(text, language)}</span>
  )
}

/** Whether a block of elements shows any answer row (answered, or a hidden sensitive answer). */
function hasRows(elements: Element[], data: Record<string, unknown>, hidden: string[]): boolean {
  return elements.some((el) =>
    el.kind === 'section'
      ? hasRows(el.elements ?? [], data, hidden)
      : el.kind !== 'content' && !(el.kind === 'field' && el.type === 'hidden') && (el.id in data || hidden.includes(el.id)),
  )
}

function Rows({ elements, data, ctx }: { elements: Element[]; data: Record<string, unknown>; ctx: Parameters<typeof Value>[0]['ctx'] }) {
  return (
    <>
      {elements.map((el) => {
        if (el.kind === 'content') return null
        if (el.kind === 'section') return <Rows key={el.id} elements={el.elements ?? []} data={data} ctx={ctx} />
        const answered = el.id in data || ctx.view.hidden.includes(el.id)
        if (!answered) return null
        if (el.kind === 'repeater') {
          const rows = Array.isArray(data[el.id]) ? (data[el.id] as Record<string, unknown>[]) : []
          const cols = (el.elements ?? []).filter((c): c is FieldElement => c.kind === 'field' && c.type !== 'hidden')
          return (
            <div key={el.id} className="flex flex-col gap-1">
              <dt className={LABEL}>{displayText(el.label, ctx.language)}</dt>
              <dd className="min-w-0 overflow-x-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-8">#</TableHead>
                      {cols.map((c) => (
                        <TableHead key={c.id}>{c.label}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row, i) => (
                      <TableRow key={i}>
                        <TableCell className="tabular-nums">{i + 1}</TableCell>
                        {cols.map((c) => (
                          <TableCell key={c.id}>
                            <Value field={c} value={row[c.id]} ctx={ctx} />
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </dd>
            </div>
          )
        }
        if (el.type === 'hidden') return null
        return (
          <div key={el.id} className="flex flex-col gap-1">
            <dt className={LABEL}>{displayText(el.label, ctx.language)}</dt>
            <dd className="min-w-0 break-words text-base">
              <Value field={el} value={data[el.id]} ctx={ctx} />
            </dd>
          </div>
        )
      })}
    </>
  )
}

function Review({
  token,
  info,
  bearer,
  view,
  initialIntent,
  onDecided,
  onGone,
}: {
  token: string
  info: LinkInfo
  bearer: string
  view: ApproverView
  initialIntent: Decision | null
  onDecided: (approved: boolean) => void
  onGone: () => void
}) {
  const language = info.language
  // Chosen with the email's button: the decision comes first and needs one confirm.
  const [intent, setIntent] = useState<Decision | null>(initialIntent)
  const [name, setName] = useState(rememberedName)
  const [comment, setComment] = useState('')
  const [errors, setErrors] = useState<{ name?: string; comment?: string; form?: string }>({})
  const [confirm, setConfirm] = useState<'approve' | 'reject' | null>(null)
  const [busy, setBusy] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => heading.current?.focus(), [])
  const ctx = { token, bearer, view, language }
  const earlier = view.steps.filter((s) => s.step < view.current && s.state === 'approved')
  const last = view.current === view.steps.length

  const check = (decision: Decision) => {
    const next: typeof errors = {}
    if (!name.trim()) next.name = msgs.nameRequired
    if (decision === 'reject' && !comment.trim()) next.comment = msgs.commentRequired
    setErrors(next)
    return !next.name && !next.comment
  }
  const ask = (decision: Decision) => {
    if (check(decision)) setConfirm(decision)
  }
  const decide = async (decision: Decision | null = confirm) => {
    if (!decision) return
    setBusy(true)
    try {
      const res = await call(
        token,
        '/decision',
        { method: 'POST', body: JSON.stringify({ decision, name: name.trim(), comment: comment.trim() }) },
        bearer,
      )
      if (res.ok) {
        rememberName(name.trim())
        return onDecided(decision === 'approve')
      }
      if (res.status === 409 || res.status === 401 || res.status === 404) return onGone()
      setErrors({ form: res.status === 429 ? msgs.tooMany : msgs.decisionFailed })
    } catch {
      setErrors({ form: msgs.failed })
    } finally {
      setBusy(false)
      setConfirm(null)
    }
  }

  const nameField = (
    <Field data-invalid={errors.name ? true : undefined}>
      <FieldLabel htmlFor="approver-name" className="text-lg">
        {msgs.yourName}
      </FieldLabel>
      <Input
        id="approver-name"
        autoComplete="name"
        className="h-12 text-base"
        maxLength={200}
        value={name}
        aria-invalid={errors.name ? true : undefined}
        onChange={(e) => setName(e.target.value)}
      />
      {errors.name && <FieldError>{errors.name}</FieldError>}
    </Field>
  )
  const commentField = (hint: string) => (
    <Field data-invalid={errors.comment ? true : undefined}>
      <FieldLabel htmlFor="approver-comment" className="text-lg">
        {msgs.comment}
      </FieldLabel>
      <FieldDescription>{hint}</FieldDescription>
      <Textarea
        id="approver-comment"
        rows={3}
        maxLength={2000}
        className="text-base"
        value={comment}
        aria-invalid={errors.comment ? true : undefined}
        onChange={(e) => setComment(e.target.value)}
      />
      {errors.comment && <FieldError>{errors.comment}</FieldError>}
    </Field>
  )
  const chosen = intent && (
    <form
      aria-labelledby="decision"
      className="flex flex-col gap-5 rounded-md border p-4 sm:p-5"
      onSubmit={(e) => {
        e.preventDefault()
        if (check(intent)) void decide(intent)
      }}
    >
      <div className="flex flex-col gap-1">
        <h2 id="decision" className="text-xl font-semibold">
          {intent === 'approve' ? msgs.confirmApprove : msgs.confirmReject}
        </h2>
        <p className="text-muted-foreground">
          {intent === 'reject' ? msgs.rejectBody : last ? msgs.approveLast : msgs.approveNext}
        </p>
      </div>
      {nameField}
      {commentField(intent === 'reject' ? msgs.commentNeeded : msgs.commentOptional)}
      {errors.form && <FieldError>{errors.form}</FieldError>}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="submit"
          variant={intent === 'reject' ? 'destructive' : 'default'}
          className="h-12 min-w-32 text-base max-sm:w-full"
          disabled={busy}
        >
          {busy && <Spinner />}
          {intent === 'approve' ? msgs.approve : msgs.reject}
        </Button>
        <Button
          type="button"
          variant="link"
          className="h-11 px-0"
          disabled={busy}
          onClick={() => {
            setErrors({})
            setIntent(intent === 'approve' ? 'reject' : 'approve')
          }}
        >
          {intent === 'approve' ? msgs.rejectInstead : msgs.approveInstead}
        </Button>
      </div>
    </form>
  )

  return (
    <div className="flex flex-col gap-8">
      <StepIntro info={info} headingRef={heading} />
      {chosen}
      {chosen && <h2 className="text-sm font-medium text-muted-foreground">{msgs.theResponse}</h2>}
      {earlier.length > 0 && (
        <section className="flex flex-col gap-1">
          <h2 className="text-sm text-muted-foreground">{msgs.earlier}</h2>
          <ul className="flex flex-col gap-1">
            {earlier.map((s) => (
              <li key={s.step}>
                {s.step}. <bdi dir="auto">{s.name}</bdi>:{' '}
                <Msg t={msgs.approvedBy} params={{ name: <bdi dir="auto">{s.decidedName}</bdi> }} />
                {s.decidedAt && (
                  <>
                    {' '}
                    ({formatDay(s.decidedAt)})
                  </>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {/* The response itself is form content: it takes the form's language and direction. */}
      <div className="flex flex-col gap-6" {...contentProps(language)}>
        {view.schema.pages.map((page) => {
          // A page skipped by logic (or with nothing answered) has no heading either.
          if (!hasRows(page.elements ?? [], view.data, view.hidden)) return null
          const rows = <Rows elements={page.elements ?? []} data={view.data} ctx={ctx} />
          return (
            <section key={page.id} className="flex flex-col gap-4">
              {page.title && <h2 className="text-xl font-semibold">{displayText(page.title, language)}</h2>}
              <dl className="flex flex-col gap-4">{rows}</dl>
            </section>
          )
        })}
      </div>
      {view.hidden.length > 0 && <p className="text-sm text-muted-foreground">{msgs.hiddenNote}</p>}
      {!chosen && (
        <section aria-labelledby="decision" className="flex flex-col gap-5 border-t pt-6">
          <h2 id="decision" className="text-xl font-semibold">
            {msgs.decisionTitle}
          </h2>
          {nameField}
          {commentField(msgs.commentHint)}
          {errors.form && <FieldError>{errors.form}</FieldError>}
          <div className="flex flex-wrap gap-3">
            <Button type="button" className="h-12 min-w-32 text-base" disabled={busy} onClick={() => ask('approve')}>
              {msgs.approve}
            </Button>
            <Button type="button" variant="outline" className="h-12 min-w-32 text-base text-destructive" disabled={busy} onClick={() => ask('reject')}>
              {msgs.reject}
            </Button>
          </div>
        </section>
      )}
      <AlertDialog open={confirm !== null} onOpenChange={(o) => !o && !busy && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm === 'reject' ? msgs.rejectTitle : msgs.approveTitle}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirm === 'reject' ? msgs.rejectBody : last ? msgs.approveLast : msgs.approveNext}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>{msgs.cancel}</AlertDialogCancel>
            <Button variant={confirm === 'reject' ? 'destructive' : 'default'} disabled={busy} onClick={() => void decide(confirm)}>
              {busy && <Spinner />}
              {confirm === 'reject' ? msgs.reject : msgs.approve}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export function ApproverPage({ token }: { token: string }) {
  const [intent] = useState(() => intentFromUrl(window.location.search))
  const [info, setInfo] = useState<LinkInfo | null>(null)
  const [stage, setStage] = useState<Stage>({ kind: 'loading' })

  const [attempt, setAttempt] = useState(0)
  const load = () => setAttempt((n) => n + 1)
  useEffect(() => {
    let alive = true
    call(token, '')
      .then(async (res) => {
        if (!alive) return
        if (res.status === 404) return setStage({ kind: 'invalid' })
        if (!res.ok) return setStage({ kind: 'error' })
        const next = (await res.json()) as LinkInfo
        loadThaanaFont(next.language === 'dv' || scriptLang(next.orgName) === 'dv' ? next.thaanaFontCssUrl : null)
        setInfo(next)
        setStage({ kind: 'intro' })
      })
      .catch(() => alive && setStage({ kind: 'error' }))
    return () => {
      alive = false
    }
  }, [token, attempt])

  useEffect(() => {
    applyBrand(info?.brand ?? null, info ? `${msgs.pageTitle}: ${info.formTitle}` : msgs.pageTitle)
  }, [info])

  if (stage.kind === 'loading') return <Page />
  if (stage.kind === 'invalid' || stage.kind === 'error' || !info)
    return (
      <Page>
        <Status
          title={stage.kind === 'invalid' ? msgs.invalidTitle : msgs.loadFailedTitle}
          body={stage.kind === 'invalid' ? msgs.invalidBody : msgs.failed}
        />
      </Page>
    )

  let body: ReactNode
  if (stage.kind === 'done')
    body = <Status title={stage.approved ? msgs.approvedTitle : msgs.rejectedTitle} body={msgs.doneBody} />
  else if (info.state === 'stopped') body = <Status title={msgs.stoppedTitle} body={msgs.stoppedBody} />
  else if (info.state !== 'pending')
    body = (
      <Status
        title={msgs.alreadyTitle}
        body={
          <Msg
            t={
              info.decidedName
                ? info.state === 'approved'
                  ? msgs.alreadyApprovedBy
                  : msgs.alreadyRejectedBy
                : info.state === 'approved'
                  ? msgs.alreadyApproved
                  : msgs.alreadyRejected
            }
            params={{
              name: <bdi dir="auto">{info.decidedName}</bdi>,
              date: info.decidedAt ? formatDay(info.decidedAt) : '',
            }}
          />
        }
      />
    )
  else if (stage.kind === 'review')
    body = (
      <Review
        token={token}
        info={info}
        bearer={stage.bearer}
        view={stage.view}
        initialIntent={intent}
        onDecided={(approved) => setStage({ kind: 'done', approved })}
        onGone={load}
      />
    )
  else
    body = (
      <CodeStep
        token={token}
        info={info}
        intent={intent}
        onDone={load}
        onVerified={async (bearer) => {
          const res = await call(token, '/submission', {}, bearer)
          if (!res.ok) return load()
          setStage({ kind: 'review', bearer, view: (await res.json()) as ApproverView })
        }}
      />
    )

  return (
    <Page brand={info.brand}>
      <Header info={info} />
      {body}
    </Page>
  )
}
