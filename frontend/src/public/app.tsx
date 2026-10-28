/**
 * Public form app UI (`/{slug}`, `?embed=1`). A separate entry from the studio: no router,
 * no query cache, only the components the renderer needs, so it stays within its bundle budget.
 * Forms that ask for an email code, staff sign-in or a CAPTCHA continue in a lazy chunk
 * (`protected.tsx`), so forms open to anyone don't pay for it.
 */
import { lazy, Suspense, useEffect, useState } from 'react'

import { Skeleton } from '@/components/ui/skeleton'
import { applyBrand } from '@/lib/branding'
import { loadThaanaFont } from '@/lib/thaana-font'
import { useDelayed } from '@/lib/use-delayed'
import type { Uploader } from '@/renderer/context'
import { FormRenderer, StatusScreen, type SubmitOutcome } from '@/renderer/form-view'
import { MSG } from '@/renderer/messages'
import { themeAttrs } from '@/renderer/theme'

import { loadForm, submitAnswers, type Access, type LiveForm, type LoadResult } from './api'
import { changedQuestions, embed, formSlug, postHeight } from './helpers'
import { useAutosave, type AutosaveLib } from './use-autosave'
import { useFriction } from './use-friction'

const ProtectedApp = lazy(() => import('./protected').then((m) => ({ default: m.ProtectedApp })))
const PUBLIC: Access = { mode: 'public' }
// Saved progress is a lazy chunk, fetched alongside the form so it never delays the first paint.
const autosaveLib: Promise<AutosaveLib | null> = import('./autosave').catch(() => null)

export function Loading() {
  const show = useDelayed(true)
  return (
    <div className="min-h-svh bg-background md:px-6 md:py-12" {...themeAttrs(null)} data-df-frame="page">
      <div className="mx-auto flex max-w-[var(--df-sheet,40rem)] flex-col gap-6 bg-card p-5 md:rounded-md md:border md:p-10">
        {show && (
          <>
            <Skeleton className="h-9 w-3/4" />
            {Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="flex flex-col gap-2">
                <Skeleton className="h-6 w-1/3" />
                <Skeleton className="h-12 w-full" />
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}

/** The form needs the access chunk: an email code, staff sign-in or a CAPTCHA. */
function needsAccess(state: LoadResult): boolean {
  if (!state.ok) return state.reason === 'login' || state.reason === 'already'
  return state.form.accessMode !== 'public' || state.form.captcha !== null
}

export function App() {
  const [state, setState] = useState<LoadResult | null>(null)
  const [highlighted, setHighlighted] = useState<Set<string>>(new Set())
  const [lib, setLib] = useState<AutosaveLib | null>(null)

  useEffect(() => {
    void Promise.all([loadForm(formSlug), autosaveLib]).then(([result, autosave]) => {
      setLib(autosave)
      setState(result)
    })
  }, [])

  useEffect(() => {
    if (!state?.ok) return
    loadThaanaFont(state.form.thaanaFontCssUrl)
    applyBrand(state.form.brand ?? null, state.form.title || 'Form')
  }, [state])

  useEffect(() => {
    if (!embed) return
    document.documentElement.style.background = 'transparent'
    const ro = new ResizeObserver(postHeight)
    ro.observe(document.body)
    return () => ro.disconnect()
  }, [])

  const autosave = useAutosave(lib, state && !needsAccess(state) && state.ok ? state.form : null)
  const onFriction = useFriction(formSlug, state && !needsAccess(state) && state.ok ? state.form : null)

  if (!state) return <Loading />
  if (needsAccess(state))
    return (
      <Suspense fallback={<Loading />}>
        <ProtectedApp first={state} />
      </Suspense>
    )
  if (!state.ok || !state.form.schema) {
    const reason = state.ok ? 'error' : state.reason
    const screen =
      reason === 'closed'
        ? { title: MSG.closedTitle, body: MSG.closedBody }
        : reason === 'not_found'
          ? { title: MSG.notFoundTitle, body: MSG.notFoundBody }
          : { title: MSG.loadFailedTitle, body: MSG.loadFailedBody }
    return (
      <div className="min-h-svh bg-background md:px-6 md:py-12" {...themeAttrs(null)} data-df-frame="page">
        <main className="mx-auto max-w-[var(--df-sheet,40rem)] bg-card p-5 md:rounded-md md:border md:p-10">
          <StatusScreen title={screen.title} body={screen.body} />
        </main>
      </div>
    )
  }

  const current: LiveForm = state.form
  const form = state.form.schema
  const nonce = current.uploadNonce ?? ''
  const onSubmit = async (answers: Record<string, unknown>): Promise<SubmitOutcome> => {
    const res = await submitAnswers(formSlug, PUBLIC, current.versionId, answers, nonce)
    switch (res.status) {
      case 'ok':
        autosave.onSubmitted()
        return { ok: true, reference: res.reference }
      case 'invalid':
        return { ok: false, kind: 'invalid', errors: res.errors }
      case 'closed':
        return { ok: false, kind: 'closed' }
      case 'version': {
        const fresh = await loadForm(formSlug)
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
    return uploadFile(formSlug, PUBLIC, nonce, file, fieldId, onProgress, signal)
  }

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
        notice={autosave.notice}
        highlighted={highlighted}
        onFriction={onFriction}
      />
    </main>
  )
}
