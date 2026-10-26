/**
 * The public form for respondents who must confirm their email, sign in as staff, or pass a
 * CAPTCHA (PHASE-4-SCREENS 2-3). Loaded lazily by `app.tsx`.
 */
import { hasThaana } from '@yashau/thaana-react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { BrandLogo } from '@/components/brand/brand-parts'
import { applyBrand } from '@/lib/branding'
import { loadThaanaFont } from '@/lib/thaana-font'
import type { Uploader } from '@/renderer/context'
import { FormRenderer, StatusScreen, type SubmitOutcome } from '@/renderer/form-view'
import { MSG } from '@/renderer/messages'
import { themeAttrs } from '@/renderer/theme'

import { AccessScreen, CaptchaStatus, CaptchaWidget, OtpGate, RespondingAs } from './access'
import { freshChallenge, solveAltcha } from './access-lib'
import { loadForm, submitAnswers, type Access, type CaptchaChallenge, type LiveForm, type LoadResult } from './api'
import * as autosaveLib from './autosave'
import { changedQuestions, embed, formSlug } from './helpers'
import { useAutosave } from './use-autosave'

/** The sheet on the desk, for screens shown before the form itself. */
function Sheet({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-svh bg-background md:px-6 md:py-12" {...themeAttrs(null)} data-df-frame="page">
      <main className="mx-auto flex max-w-[var(--df-sheet,40rem)] flex-col gap-6 bg-card p-5 md:rounded-md md:border md:p-10">{children}</main>
    </div>
  )
}

function GateHeader({ live }: { live: LiveForm }) {
  return (
    <header className="flex flex-col gap-2" lang={live.language} dir={live.language === 'dv' ? 'rtl' : 'ltr'}>
      {live.brand?.logoUrl ? (
        <div className="mb-2 flex">
          <BrandLogo brand={live.brand} />
        </div>
      ) : live.orgName && (
        // Latin org names keep the Latin face inside a dv form (DESIGN-SYSTEM 4.1).
        <p className="text-sm text-muted-foreground" lang={hasThaana(live.orgName) ? 'dv' : 'en'}>
          {live.orgName}
        </p>
      )}
      <h1 className="df-title text-2xl font-bold sm:text-3xl">{live.title}</h1>
    </header>
  )
}

type CaptchaState = 'idle' | 'checking' | 'failed' | 'missing'

/** Proof-of-work (altcha) solved in the background as soon as the form opens. */
function useAltcha(challenge: CaptchaChallenge | undefined) {
  const solving = useRef<Promise<string> | null>(null)
  const start = useCallback((c: CaptchaChallenge) => {
    solving.current = solveAltcha(c)
    solving.current.catch(() => undefined)
  }, [])
  useEffect(() => {
    if (challenge) start(challenge)
  }, [challenge, start])
  return { solving, restart: start }
}

export function ProtectedApp({ first }: { first: LoadResult }) {
  const [state, setState] = useState<LoadResult>(first)
  const [access, setAccess] = useState<Access>({ mode: first.ok ? first.form.accessMode : 'public' })
  const [highlighted, setHighlighted] = useState<Set<string>>(new Set())
  const [widgetToken, setWidgetToken] = useState<string | null>(null)
  const [captchaState, setCaptchaState] = useState<CaptchaState>('idle')

  const load = useCallback(async (next: Access) => {
    const result = await loadForm(formSlug, next)
    if (result.ok) {
      setAccess((a) => ({ ...a, mode: result.form.accessMode }))
    }
    setState(result)
  }, [])

  useEffect(() => {
    if (state?.ok === false && state.reason === 'login')
      window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`)
  }, [state])

  useEffect(() => {
    if (!state?.ok) return
    loadThaanaFont(state.form.thaanaFontCssUrl)
    applyBrand(state.form.brand ?? null, state.form.title || 'Form')
  }, [state])

  const live = state?.ok ? state.form : null
  const autosave = useAutosave(autosaveLib, live)
  const altcha = useAltcha(live?.schema && live.captcha?.provider === 'altcha' ? live.captcha.challenge : undefined)

  if (!state.ok) {
    if (state.reason === 'login' || state.reason === 'already')
      return (
        <Sheet>
          <AccessScreen kind={state.reason === 'login' ? 'signin' : 'already'} />
        </Sheet>
      )
    const screen =
      state.reason === 'closed'
        ? { title: MSG.closedTitle, body: MSG.closedBody }
        : state.reason === 'not_found'
          ? { title: MSG.notFoundTitle, body: MSG.notFoundBody }
          : { title: MSG.loadFailedTitle, body: MSG.loadFailedBody }
    return (
      <Sheet>
        <StatusScreen title={screen.title} body={screen.body} />
      </Sheet>
    )
  }

  const current: LiveForm = state.form
  if (!current.schema)
    // Email-code form: confirm the address first; the questions load afterwards.
    return (
      <Sheet>
        <GateHeader live={current} />
        <OtpGate
            live={current}
            slug={formSlug}
            onVerified={(token) => {
              if (!token) return setState({ ok: false, reason: 'already' })
              const next: Access = { mode: 'otp', token }
              setAccess(next)
              void load(next)
            }}
          />
      </Sheet>
    )

  const form = current.schema
  const nonce = current.uploadNonce ?? ''
  const captcha = current.captcha
  const renewChallenge = () => void freshChallenge(formSlug).then((c) => c && altcha.restart(c))

  /** The CAPTCHA token for this submit: undefined when none is needed, null when missing. */
  const captchaToken = async (): Promise<string | undefined | null> => {
    if (!captcha) return undefined
    if (captcha.provider !== 'altcha') return widgetToken
    if (!altcha.solving.current) return null
    setCaptchaState('checking')
    try {
      const token = await altcha.solving.current
      setCaptchaState('idle')
      return token
    } catch {
      setCaptchaState('failed')
      return null
    }
  }

  const onSubmit = async (answers: Record<string, unknown>): Promise<SubmitOutcome> => {
    const token = await captchaToken()
    if (token === null) {
      if (captcha?.provider !== 'altcha') setCaptchaState('missing')
      return { ok: false, kind: 'handled' }
    }
    const res = await submitAnswers(formSlug, access, current.versionId, answers, nonce, token)
    if (captcha && res.status !== 'invalid') {
      // A token works once: get a fresh one for the next try (or the next response).
      setWidgetToken(null)
      if (captcha.provider === 'altcha') renewChallenge()
    }
    switch (res.status) {
      case 'ok':
        autosave.onSubmitted()
        return { ok: true, reference: res.reference }
      case 'invalid':
        return { ok: false, kind: 'invalid', errors: res.errors }
      case 'closed':
        return { ok: false, kind: 'closed' }
      case 'captcha':
        setCaptchaState(captcha?.provider === 'altcha' ? 'failed' : 'missing')
        return { ok: false, kind: 'handled' }
      case 'already':
        setState({ ok: false, reason: 'already' })
        return { ok: false, kind: 'handled' }
      case 'expired':
        // The respondent token ran out: confirm the email again.
        setAccess({ mode: current.accessMode })
        void load({ mode: current.accessMode })
        return { ok: false, kind: 'handled' }
      case 'version': {
        const fresh = await loadForm(formSlug, access)
        if (fresh.ok && fresh.form.schema) {
          // Files already uploaded belong to this page load's upload session.
          fresh.form.uploadNonce = nonce
          setHighlighted(changedQuestions(form, fresh.form.schema))
          setState(fresh)
        }
        return { ok: false, kind: 'version' }
      }
      default:
        return { ok: false, kind: 'network' }
    }
  }

  const uploader: Uploader = async (file, fieldId, onProgress, signal) => {
    const { uploadFile } = await import('./upload')
    return uploadFile(formSlug, access, nonce, file, fieldId, onProgress, signal)
  }

  const beforeSubmit = captcha ? (
    <>
      {captcha.provider === 'altcha' ? (
        (captchaState === 'checking' || captchaState === 'failed') && (
          <CaptchaStatus
            state={captchaState}
            onRetry={() => {
              setCaptchaState('idle')
              renewChallenge()
            }}
          />
        )
      ) : (
        <CaptchaWidget
          config={captcha}
          error={captchaState === 'missing' && !widgetToken}
          onToken={(t) => {
            setWidgetToken(t)
            if (t) setCaptchaState('idle')
          }}
        />
      )}
    </>
  ) : undefined

  return (
    <main>
      <FormRenderer
        key={autosave.key}
        form={form}
        orgName={current.orgName}
        brand={current.brand}
        mode="live"
        embed={embed}
        onSubmit={onSubmit}
        uploader={uploader}
        initialAnswers={autosave.initialAnswers}
        initialPage={autosave.initialPage}
        onProgress={autosave.onProgress}
        highlighted={highlighted}
        notice={
          <>
            {current.respondentEmail && <RespondingAs email={current.respondentEmail} />}
            {autosave.notice}
          </>
        }
        beforeSubmit={beforeSubmit}
        allowAnother={!current.otp?.oneResponse}
      />
    </main>
  )
}
