import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useRouteContext, useSearch } from '@tanstack/react-router'
import { REGEXP_ONLY_DIGITS } from 'input-otp'
import { CircleAlertIcon, FlaskConicalIcon, KeyRoundIcon, RotateCwIcon } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { api, ApiError, ssoLoginUrl, type Me } from '@/lib/api'
import { brandQuery, metaQuery } from '@/lib/queries'
import { clearSignedOut, isSignedOut, loginTarget } from '@/lib/sso-auto'

const SSO_ERRORS: Record<string, string> = {
  sso_failed: 'Single sign-on failed. Try again.',
  sso_unavailable: 'The sign-in service is unavailable right now.',
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return 'Too many attempts. Wait a few minutes and try again.'
    if (err.detail === 'invalid_code') return 'That code is wrong or has expired.'
  }
  return 'Could not sign in. Try again.'
}

/** Studio routes stay in this app; anything else (a public form at /{slug}) is a page load. */
const isStudioPath = (path: string) => path === '/' || /^\/(login|forms|settings)(\/|$|\?)/.test(path)

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const RESEND_WAIT = 60

/** Email-code sign-in. With `fixedEmail` (an invitation) the address can't be changed;
 * `onSignedIn` replaces the navigation to `next`. */
export function LocalLogin({
  next,
  fixedEmail,
  onSignedIn,
}: {
  next: string
  fixedEmail?: string
  onSignedIn?: (me: Me) => void | Promise<void>
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [email, setEmail] = useState(fixedEmail ?? '')
  const [emailError, setEmailError] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const [wait, setWait] = useState(0)
  const [announce, setAnnounce] = useState('')

  useEffect(() => {
    if (wait <= 0) return
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000)
    return () => window.clearTimeout(t)
  }, [wait])

  const request = useMutation({
    mutationFn: () => api.requestCode(email.trim()),
    onSuccess: () => {
      if (sent) setAnnounce('A new code is on its way.')
      setSent(true)
      setCode('')
      setCodeError(null)
      setWait(RESEND_WAIT)
    },
    onError: (err) => {
      if (sent) setCodeError(errorMessage(err))
    },
  })
  const verify = useMutation({
    mutationFn: (value: string) => api.verifyCode(email.trim(), value),
    onSuccess: async (me) => {
      queryClient.setQueryData(['me'], me)
      if (onSignedIn) return onSignedIn(me)
      // Public forms (/{slug}) are a separate app: leave the studio for them.
      if (isStudioPath(next)) await navigate({ to: next })
      else window.location.assign(next)
    },
    onError: (err) => {
      // Clear the slots so the next code can be typed straight away (REVIEW P2-14).
      setCode('')
      setCodeError(errorMessage(err))
    },
  })

  if (!sent) {
    return (
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          if (!EMAIL.test(email.trim())) {
            setEmailError(email.trim() ? 'Enter an email address like you@example.org' : 'Enter your email address')
            document.getElementById('email')?.focus()
            return
          }
          setEmailError(null)
          request.mutate()
        }}
      >
        <FieldGroup>
          {request.error && (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertDescription>{errorMessage(request.error)}</AlertDescription>
            </Alert>
          )}
          <Field data-invalid={emailError ? true : undefined}>
            <FieldLabel htmlFor="email">Email</FieldLabel>
            <Input
              id="email"
              type="email"
              dir="ltr"
              autoComplete="email"
              readOnly={!!fixedEmail}
              required
              placeholder="you@example.org"
              aria-invalid={emailError ? true : undefined}
              aria-describedby={emailError ? 'email-error' : undefined}
              value={email}
              onChange={(e) => {
                setEmail(e.target.value)
                if (emailError) setEmailError(null)
              }}
            />
            {fixedEmail && <FieldDescription>This invitation is for this address.</FieldDescription>}
            {emailError && <FieldError id="email-error">{emailError}</FieldError>}
          </Field>
          <Button type="submit" disabled={request.isPending}>
            {request.isPending && <Spinner />}
            Email me a sign-in code
          </Button>
        </FieldGroup>
      </form>
    )
  }

  const time = `${Math.floor(wait / 60)}:${String(wait % 60).padStart(2, '0')}`
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        if (code.length === 6) verify.mutate(code)
      }}
    >
      <FieldGroup>
        <Field data-invalid={codeError ? true : undefined}>
          <FieldLabel htmlFor="code">Sign-in code</FieldLabel>
          <div dir="ltr" className="flex justify-center">
            <InputOTP
              id="code"
              maxLength={6}
              pattern={REGEXP_ONLY_DIGITS}
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              aria-invalid={codeError ? true : undefined}
              aria-describedby={codeError ? 'code-error code-help' : 'code-help'}
              onChange={(v) => {
                setCode(v)
                if (codeError) setCodeError(null)
              }}
              autoFocus
            >
              <InputOTPGroup>
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <InputOTPSlot key={i} index={i} />
                ))}
              </InputOTPGroup>
            </InputOTP>
          </div>
          {codeError && (
            <FieldError id="code-error" className="text-center">
              {codeError}
            </FieldError>
          )}
          <FieldDescription id="code-help">
            If <bdi dir="ltr">{email.trim()}</bdi> has an account, a 6-digit code is on its way.
          </FieldDescription>
        </Field>
        <Button type="submit" disabled={code.length !== 6 || verify.isPending}>
          {verify.isPending && <Spinner />}
          Sign in
        </Button>
        <div className="flex flex-wrap justify-center gap-x-4">
          <Button type="button" variant="link" disabled={wait > 0 || request.isPending} onClick={() => request.mutate()}>
            {wait > 0 ? (
              <>
                Send a new code in <span className="tabular-nums">{time}</span>
              </>
            ) : (
              'Send a new code'
            )}
          </Button>
          {!fixedEmail && (
          <Button
            type="button"
            variant="link"
            onClick={() => {
              setSent(false)
              setCode('')
              setCodeError(null)
              setWait(0)
              verify.reset()
              request.reset()
            }}
          >
            Use a different email
          </Button>
          )}
        </div>
      </FieldGroup>
      <span className="sr-only" aria-live="polite">
        {announce}
      </span>
    </form>
  )
}

/** The minimal state shown while the browser leaves for the identity provider. */
export function SigningIn() {
  return (
    <main className="mx-auto flex w-full max-w-sm flex-col gap-6 px-4 py-8">
      <p role="status" className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
        <Spinner /> Signing you in…
      </p>
    </main>
  )
}

export function LoginPage() {
  const { next, error, manual } = useSearch({ from: '/login' })
  const { autoSignIn } = useRouteContext({ from: '/login' })
  const meta = useQuery(metaQuery)
  const brand = useQuery(brandQuery('_'))
  const target = loginTarget(next)
  // Read once: clicking "Sign in again" clears the flag on the way out.
  const [signedOut] = useState(() => isSignedOut())

  if (autoSignIn) return <SigningIn />
  const oidc = !!meta.data?.features.oidc
  const showSignedOut = oidc && signedOut && !error && !manual
  const ssoUrl = ssoLoginUrl(target)

  if (showSignedOut)
    return (
      <main className="mx-auto flex w-full max-w-sm flex-col gap-6 px-4 py-8">
        <Card>
          <CardHeader>
            <CardTitle>
              <h1>You&apos;re signed out</h1>
            </CardTitle>
            <CardDescription>You can close this tab, or sign in again.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Button asChild>
              <a href={ssoUrl} onClick={() => clearSignedOut()}>
                <KeyRoundIcon />
                Sign in again
              </a>
            </Button>
          </CardContent>
        </Card>
      </main>
    )

  return (
    <main className="mx-auto flex w-full max-w-sm flex-col gap-6 px-4 py-8">
      <Card>
        <CardHeader>
          <CardTitle>
            <h1>
              {brand.data?.custom ? (
                <>
                  Sign in to <bdi dir="auto">{brand.data.name}</bdi>
                </>
              ) : (
                'Sign in'
              )}
            </h1>
          </CardTitle>
          <CardDescription>Sign in to build forms and review submissions.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error && (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertDescription>{SSO_ERRORS[error] ?? SSO_ERRORS.sso_failed}</AlertDescription>
            </Alert>
          )}
          {meta.isPending ? (
            <Skeleton className="h-9 w-full" />
          ) : meta.isError ? (
            <Alert variant="destructive">
              <AlertDescription>Something went wrong.</AlertDescription>
            </Alert>
          ) : (
            <>
              {meta.data.features.demo && meta.data.features.localLogin && (
                <Alert>
                  <FlaskConicalIcon />
                  <AlertTitle>Demo instance</AlertTitle>
                  <AlertDescription>
                    This is a demo. Don&apos;t enter real or personal data.
                  </AlertDescription>
                </Alert>
              )}
              {meta.data.features.oidc && (
                <Button asChild>
                  <a href={ssoUrl} onClick={() => clearSignedOut()}>
                    {error ? <RotateCwIcon /> : <KeyRoundIcon />}
                    {error ? 'Try again' : 'Sign in with single sign-on'}
                  </a>
                </Button>
              )}
              {meta.data.features.oidc && meta.data.features.localLogin && <Separator />}
              {meta.data.features.localLogin && <LocalLogin next={target} />}
              {!meta.data.features.oidc && !meta.data.features.localLogin && (
                <p className="text-sm text-muted-foreground">No sign-in method is configured.</p>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </main>
  )
}
