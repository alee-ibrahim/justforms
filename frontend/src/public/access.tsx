/**
 * Respondent access and CAPTCHA for the public form (PHASE-4-SCREENS 2-3). A lazy chunk: forms
 * open to anyone without spam protection never load it.
 * Copy (English system text, for every form) lives in `access-lib.ts`.
 */
import { BadgeCheckIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp'
import { Spinner } from '@/components/ui/spinner'
import { StatusScreen } from '@/renderer/form-view'
import { En, Msg } from '@/renderer/msg'

import { ACCESS as msgs } from './access-lib'
import { formPath, type CaptchaConfig, type LiveForm } from './api'

function maskEmail(email: string): string {
  const [local, domain] = email.split('@')
  return domain ? `${local.slice(0, 1)}••••@${domain}` : email
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const RESEND_SECONDS = 60

/** Step 1 asks for the email, step 2 for the code; on success the form loads. */
export function OtpGate({
  live,
  slug,
  onVerified,
}: {
  live: LiveForm
  slug: string
  onVerified: (token: string, email: string) => void
}) {
  const [step, setStep] = useState<'email' | 'code'>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [wait, setWait] = useState(0)
  const [announce, setAnnounce] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (wait <= 0) return
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000)
    return () => window.clearTimeout(t)
  }, [wait])
  useEffect(() => heading.current?.focus(), [step])

  const send = async () => {
    const value = email.trim().toLowerCase()
    if (!EMAIL.test(value)) return setError(msgs.emailInvalid)
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(`${formPath(slug)}/otp/request`, {
        method: 'POST',
        credentials: 'omit',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email: value }),
      })
      const body = (await res.json().catch(() => null)) as { detail?: string } | null
      if (res.status === 202) {
        setStep('code')
        setCode('')
        setWait(RESEND_SECONDS)
        setAnnounce(msgs.announceSent)
      } else if (res.status === 429) setError(msgs.tooMany)
      else if (body?.detail === 'domain_not_allowed')
        setError(msgs.domain.replace('{domains}', (live.otp?.allowedDomains ?? []).join(', ')))
      else setError(msgs.failed)
    } catch {
      setError(msgs.failed)
    } finally {
      setBusy(false)
    }
  }

  const verify = async (value: string) => {
    if (value.length !== 6) return
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(`${formPath(slug)}/otp/verify`, {
        method: 'POST',
        credentials: 'omit',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), code: value }),
      })
      const body = (await res.json().catch(() => null)) as { detail?: string; token?: string; email?: string } | null
      if (res.ok && body?.token && body.email) return onVerified(body.token, body.email)
      if (res.status === 409) return onVerified('', '') // already responded: the caller reloads
      setCode('')
      setError(
        res.status === 429 ? msgs.tooMany : body?.detail === 'code_expired' ? msgs.expired : msgs.wrong,
      )
    } catch {
      setError(msgs.failed)
    } finally {
      setBusy(false)
    }
  }

  const minutes = `${Math.floor(wait / 60)}:${String(wait % 60).padStart(2, '0')}`
  return (
    // System text only, so left to right even for a Dhivehi form (the header above is content).
    <div className="flex flex-col gap-6" lang="en" dir="ltr">
      {step === 'email' ? (
        <form
          className="flex flex-col gap-5"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            void send()
          }}
        >
          <div className="flex flex-col gap-1">
            <h2 ref={heading} tabIndex={-1} className="text-xl font-semibold outline-none">
              {msgs.otpTitle}
            </h2>
            <p className="text-muted-foreground">{msgs.otpIntro}</p>
          </div>
          <Field data-invalid={error ? true : undefined}>
            <FieldLabel htmlFor="otp-email" className="text-lg">
              {msgs.email}
            </FieldLabel>
            {live.otp?.allowedDomains.length ? (
              <FieldDescription>
                <bdi dir="ltr">{live.otp.allowedDomains.map((d) => `@${d}`).join(', ')}</bdi>
              </FieldDescription>
            ) : null}
            <Input
              id="otp-email"
              type="email"
              dir="ltr"
              autoComplete="email"
              inputMode="email"
              className="h-12 text-base"
              value={email}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? 'otp-error' : undefined}
              onChange={(e) => {
                setEmail(e.target.value)
                setError(null)
              }}
            />
            {error && (
              <FieldError id="otp-error">
                <Msg t={error} params={{}} />
              </FieldError>
            )}
          </Field>
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
            <h2 ref={heading} tabIndex={-1} className="text-xl font-semibold outline-none">
              {msgs.codeTitle}
            </h2>
            <p className="text-muted-foreground">
              <Msg t={msgs.codeSent} params={{ email: maskEmail(email.trim().toLowerCase()) }} />
            </p>
          </div>
          <Field data-invalid={error ? true : undefined}>
            <FieldLabel htmlFor="otp-code" className="sr-only">
              {msgs.codeLabel}
            </FieldLabel>
            <div dir="ltr" className="self-start">
              <InputOTP
                id="otp-code"
                maxLength={6}
                value={code}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="^[0-9]*$"
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? 'otp-error' : undefined}
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
            {error && <FieldError id="otp-error">{error}</FieldError>}
          </Field>
          <Button type="submit" className="h-12 text-base max-md:w-full md:self-start" disabled={busy || code.length !== 6}>
            {busy && <Spinner />}
            {msgs.continue}
          </Button>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <Button type="button" variant="link" className="h-11 px-0" disabled={wait > 0 || busy} onClick={() => void send()}>
              {wait > 0 ? <Msg t={msgs.resendIn} params={{ time: minutes }} /> : msgs.resend}
            </Button>
            <Button
              type="button"
              variant="link"
              className="h-11 px-0"
              onClick={() => {
                setStep('email')
                setError(null)
              }}
            >
              {msgs.differentEmail}
            </Button>
          </div>
        </form>
      )}
      <span className="sr-only start-0 top-0" aria-live="polite">
        {announce}
      </span>
    </div>
  )
}

/** Shown inside the form (which may be RTL); the English run is isolated by `Msg`. */
export function RespondingAs({ email }: { email: string }) {
  return (
    <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
      <BadgeCheckIcon className="size-4 shrink-0" aria-hidden />
      <span>
        <Msg t={msgs.respondingAs} params={{ email: <bdi dir="ltr">{email}</bdi> }} />
      </span>
    </p>
  )
}

// -- CAPTCHA ----------------------------------------------------------------------------------

type Widget = {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string
  reset: (id?: string) => void
}

const SCRIPTS = {
  turnstile: 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit',
  hcaptcha: 'https://js.hcaptcha.com/1/api.js?render=explicit&recaptchacompat=off',
} as const

function loadScript(src: string, global: 'turnstile' | 'hcaptcha'): Promise<Widget> {
  const w = window as unknown as Record<string, Widget | undefined>
  if (w[global]) return Promise.resolve(w[global])
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = src
    s.async = true
    s.onload = () => {
      const poll = () => (w[global] ? resolve(w[global]) : setTimeout(poll, 50))
      poll()
    }
    s.onerror = () => reject(new Error('captcha_script'))
    document.head.appendChild(s)
  })
}

/** The provider's widget (Turnstile / hCaptcha) above the submit button. */
export function CaptchaWidget({
  config,
  error,
  onToken,
}: {
  config: CaptchaConfig
  error: boolean
  onToken: (token: string | null) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)
  const latest = useRef(onToken)
  useEffect(() => {
    latest.current = onToken
  })
  useEffect(() => {
    if (config.provider === 'altcha' || !box.current) return
    let cancelled = false
    const provider = config.provider
    loadScript(SCRIPTS[provider], provider)
      .then((widget) => {
        if (cancelled || !box.current) return
        widget.render(box.current, {
          sitekey: config.siteKey,
          callback: (t: string) => latest.current(t),
          'expired-callback': () => latest.current(null),
          'error-callback': () => latest.current(null),
          // The widget is system UI too: English for every form.
          ...(provider === 'turnstile' ? { language: 'en' } : { hl: 'en' }),
        })
      })
      .catch(() => setFailed(true))
    return () => {
      cancelled = true
    }
  }, [config.provider, config.siteKey])
  if (config.provider === 'altcha') return null
  return (
    <Field data-invalid={error || failed ? true : undefined}>
      <FieldLabel className="text-lg">
        <En>{msgs.captchaLabel}</En>
      </FieldLabel>
      <div ref={box} dir="ltr" className="min-h-16" />
      {(error || failed) && (
        <FieldError>
          <En>{failed ? msgs.captchaFailed : msgs.captchaRequired}</En>
        </FieldError>
      )}
    </Field>
  )
}

/** Status line for the proof-of-work check while the respondent submits. */
export function CaptchaStatus({
  state,
  onRetry,
}: {
  state: 'checking' | 'failed'
  onRetry: () => void
}) {
  return state === 'checking' ? (
    <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
      <Spinner />
      <En>{msgs.checking}</En>
    </p>
  ) : (
    <p className="flex flex-wrap items-center gap-2 text-sm text-destructive" role="alert">
      <En>{msgs.captchaFailed}</En>
      <Button type="button" variant="link" className="h-auto p-0" onClick={onRetry}>
        <En>{msgs.retry}</En>
      </Button>
    </p>
  )
}

/** "You've already responded" and the staff sign-in redirect notice. */
export function AccessScreen({ kind }: { kind: 'already' | 'signin' }) {
  return (
    <StatusScreen
      title={kind === 'already' ? msgs.alreadyTitle : msgs.signInTitle}
      body={kind === 'already' ? msgs.alreadyBody : msgs.signInBody}
    />
  )
}
