/**
 * Everything inside one form: the form bar, the builder store (draft, autosave, undo) and the
 * Edit / Preview / Share pages below it.
 */
import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useParams, useRouterState } from '@tanstack/react-router'
import { compare } from 'fast-json-patch'
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'

import { AiContext, AiController } from '@/components/ai/controller'
import { ConfirmDialogs, ConflictDialog } from '@/components/builder/dialogs'
import { FormBar } from '@/components/builder/form-bar'
import { FormContext, useFormSummary } from '@/components/builder/form-context'
import { PublishDialog } from '@/components/builder/publish'
import { PublishedContext } from '@/components/builder/published'
import { ReviewChangesSheet } from '@/components/builder/review-changes'
import { BuilderContext, BuilderStore, useBuilder } from '@/components/builder/store'
import { usePublish } from '@/components/builder/use-publish'
import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError, type Draft, type FormSummary } from '@/lib/api'
import { draftQuery, formQuery, metaQuery, versionQuery } from '@/lib/queries'
import { useDelayed } from '@/lib/use-delayed'
import { buildIndex } from '@/logic/form-index'

function isEditable(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
}

/** Builder-wide keyboard shortcuts (PHASE-2-SCREENS 2.13). */
function useShortcuts(store: BuilderStore, onPublish: () => void) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const editing = pathname.endsWith('/edit')
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey
      const typing = isEditable(e.target)
      const inDialog = (e.target as HTMLElement | null)?.closest('[role=dialog],[role=alertdialog],[role=menu]')
      if (mod && e.key === 'Enter') {
        e.preventDefault()
        onPublish()
        return
      }
      if (typing || inDialog) return // native text undo and typing win inside fields
      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        void (e.shiftKey ? store.redo() : store.undo())
      } else if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        void store.redo()
      } else if (editing && e.key === '/' && !mod) {
        e.preventDefault()
        store.setInserting(true)
      } else if (editing && e.key === '?' && !mod) {
        e.preventDefault()
        document.querySelector<HTMLButtonElement>('button[aria-label="Keyboard shortcuts"]')?.click()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [store, onPublish, editing])
}

function EditorScope({ form, draft, children }: { form: FormSummary; draft: Draft; children: ReactNode }) {
  const [store] = useState(() => new BuilderStore(form.id, draft))
  useEffect(() => {
    store.attach()
    return () => store.dispose()
  }, [store])
  const live = useQuery(versionQuery(form.id, form.currentVersion))
  // The AI assistant exists only when the install has a provider (DESIGN 12.1).
  const aiOn = !!useQuery(metaQuery).data?.features.ai
  const ai = useMemo(() => (aiOn ? new AiController(store) : null), [aiOn, store])
  useEffect(() => () => ai?.dispose(), [ai])
  return (
    <BuilderContext.Provider value={store}>
      <AiContext.Provider value={ai}>
        <EditorChrome form={form} store={store} liveSchema={live.data?.schema ?? null}>
          {children}
        </EditorChrome>
      </AiContext.Provider>
    </BuilderContext.Provider>
  )
}

function EditorChrome({
  form,
  store,
  liveSchema,
  children,
}: {
  form: FormSummary
  store: BuilderStore
  liveSchema: Draft['schema'] | null
  children: ReactNode
}) {
  const schema = useBuilder((s) => s.schema)
  const dirty = useBuilder((s) => s.status !== 'saved')
  const unpublished = form.currentVersion === null || !liveSchema || compare(liveSchema, schema).length > 0
  const published = useMemo(() => {
    if (!liveSchema) return new Set<string>()
    const index = buildIndex(liveSchema)
    return new Set<string>([...index.elements.keys()])
  }, [liveSchema])
  const { start, mutation } = usePublish(form)
  const publish = useCallback(() => start(), [start])
  useShortcuts(store, publish)
  useEffect(() => {
    if (!dirty) return
    const handler = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])
  const editing = useRouterState({ select: (s) => s.location.pathname.endsWith('/edit') })
  return (
    <PublishedContext.Provider value={published}>
      {/* The builder fills the screen under the app header and scrolls inside; dvh follows the
          phone's address bar, so no gap opens or content hides when it shows or hides. */}
      <div className={editing ? 'flex h-[calc(100dvh-var(--app-bar-h,0px))] flex-col overflow-hidden' : 'contents'}>
        <FormBar form={form} store={store} unpublished={unpublished} onPublish={publish} sticky={!editing} />
        {children}
      </div>
      <PublishDialog form={form} mutation={mutation} />
      <ReviewChangesSheet form={form} onPublish={() => start({ reviewed: true })} />
      <ConfirmDialogs />
      <ConflictDialog />
    </PublishedContext.Provider>
  )
}

function LoadingFrame() {
  const show = useDelayed(true)
  if (!show) return null
  return (
    <div className="flex flex-1 gap-0">
      <div className="hidden w-60 flex-col gap-2 border-e bg-card p-3 lg:flex">
        {Array.from({ length: 10 }, (_, i) => (
          <Skeleton key={i} className="h-8" />
        ))}
      </div>
      <div className="flex flex-1 justify-center p-8">
        <div className="flex w-full max-w-[40rem] flex-col gap-8 rounded-md border bg-card p-10">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="flex flex-col gap-2">
              <Skeleton className="h-6 w-1/3" />
              <Skeleton className="h-11" />
            </div>
          ))}
        </div>
      </div>
      <div className="hidden w-80 flex-col gap-3 border-s bg-card p-4 md:flex">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-8" />
        ))}
      </div>
    </div>
  )
}

export function FormLayout() {
  const { formId } = useParams({ from: '/authed/forms/$formId' })
  const navigate = useNavigate()
  const form = useQuery(formQuery(formId))
  const canEdit = !!form.data && form.data.role !== 'viewer'
  const draft = useQuery({ ...draftQuery(formId), enabled: canEdit, staleTime: Infinity, refetchOnWindowFocus: false })

  const missing = form.error instanceof ApiError && (form.error.status === 404 || form.error.status === 422)
  if (form.isError || draft.isError)
    return (
      <div className="p-4 sm:p-8">
        <Empty className="border bg-card">
          <EmptyHeader>
            <EmptyTitle>{missing ? "This form doesn't exist" : "Couldn't open this form"}</EmptyTitle>
            <EmptyDescription>
              {missing
                ? 'It may have been deleted, or the link is wrong. Your forms are listed on the Forms page.'
                : 'Check your connection and try again. If it keeps happening, the form may have been deleted.'}
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent className="flex-row flex-wrap justify-center">
            {!missing && <Button onClick={() => void (form.isError ? form.refetch() : draft.refetch())}>Try again</Button>}
            <Button variant="outline" onClick={() => void navigate({ to: '/forms' })}>
              Back to forms
            </Button>
          </EmptyContent>
        </Empty>
      </div>
    )
  if (!form.data || (canEdit && !draft.data)) return <LoadingFrame />

  return (
    <FormContext.Provider value={form.data}>
      {canEdit && draft.data ? (
        <EditorScope key={formId} form={form.data} draft={draft.data}>
          <Outlet />
        </EditorScope>
      ) : (
        <>
          <FormBar form={form.data} store={null} unpublished={false} />
          <Outlet />
        </>
      )}
    </FormContext.Provider>
  )
}

/** Shown on Edit / Preview for people with view access only. */
export function NoEditAccess() {
  const form = useFormSummary()
  return (
    <Empty className="m-8 border bg-card">
      <EmptyHeader>
        <EmptyTitle>You can view this form but not edit it</EmptyTitle>
        <EmptyDescription>Ask an owner of this form for editor access.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button asChild variant="outline">
          <Link to="/forms/$formId/share" params={{ formId: form.id }}>
            Open share settings
          </Link>
        </Button>
      </EmptyContent>
    </Empty>
  )
}
