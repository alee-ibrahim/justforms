/**
 * State of the AI assistant in one builder (PHASE-5-SCREENS): the chat, the request being
 * streamed, and the pending suggestion, which is shown on the canvas through a read-only
 * builder store while the real draft is locked. Nothing reaches the draft until Apply.
 */
import { createContext, useContext, useSyncExternalStore } from 'react'
import { toast } from 'sonner'

import { BuilderStore } from '@/components/builder/store'
import { ApiError } from '@/lib/api'

import { type AiEvent, type AiSession, aiApi, type Proposal, type Step } from './api'

export interface LiveRequest {
  /** What the person asked, or the file they uploaded. */
  text: string
  file?: { name: string }
  steps: Step[]
  reply: string
}

export interface AiState {
  open: boolean
  session: AiSession | null
  loading: boolean
  live: LiveRequest | null
  busy: 'sending' | 'applying' | 'discarding' | null
  /** Error code from the last request (see errorText). */
  error: { code: string } | null
  /** The last request reported a filled-in paper form. */
  filledIn: boolean
  /** Apply failed because the draft changed in the same places. */
  stale: boolean
  composer: string
  /** "suggestion" shows the AI's version on the canvas, "current" the real draft. */
  showing: 'suggestion' | 'current'
  preview: BuilderStore | null
}

export const MAX_REQUEST = 4000

/** Plain-English text for an error code (PHASE-5-SCREENS 3.2). */
export function errorText(error: AiState['error']): string {
  if (!error) return ''
  switch (error.code) {
    case 'provider_unavailable':
    case 'provider_error':
    case 'timeout':
    case 'network':
      return "The AI service didn't answer. Try again in a minute."
    case 'too_many_requests':
      return "You've sent a lot of requests. Wait a few minutes, then try again."
    case 'ai_budget_exceeded':
      return "You've used today's AI allowance. It resets tomorrow."
    case 'tool_limit':
    case 'no_valid_result':
      return "The AI couldn't finish this change. Try a smaller request, like one page at a time."
    case 'form_too_large':
      return 'This form is too large for the AI assistant. Edit it by hand, or split it into smaller forms.'
    case 'ai_busy':
      return 'The AI is still finishing your last request. Try again in a moment.'
    case 'unsaved':
      return 'Your latest changes are not saved yet. Reconnect, then try again.'
    case 'file_too_large':
      return 'This file is larger than 20 MB. Scan it at a lower resolution.'
    case 'unsupported_file':
      return 'Choose a PDF, JPG, PNG or WebP file.'
    case 'too_many_pages':
      return 'This document has more than 10 pages. Upload the pages of one form at a time.'
    case 'unreadable_file':
      return "This file couldn't be opened. Try another copy or a photo of the pages."
    default:
      return "Something went wrong with the AI request. Try again; if it keeps happening, edit the form by hand."
  }
}

/** Ids to wash on the canvas: added, changed and moved questions. */
export function changedIds(p: Proposal): string[] {
  return p.changes.filter((c) => c.kind === 'element' && c.change !== 'removed' && c.id).map((c) => c.id!)
}

function codeOf(err: unknown): AiState['error'] {
  if (err instanceof ApiError) return { code: typeof err.detail === 'string' ? err.detail : `http_${err.status}` }
  return { code: 'network' }
}

const INITIAL: AiState = {
  open: false,
  session: null,
  loading: false,
  live: null,
  busy: null,
  error: null,
  filledIn: false,
  stale: false,
  composer: '',
  showing: 'suggestion',
  preview: null,
}

export class AiController {
  private state: AiState = INITIAL
  private listeners = new Set<() => void>()
  private abort: AbortController | null = null
  private lastRequest: { text: string } | { file: File } | null = null
  readonly formId: string
  readonly builder: BuilderStore

  constructor(builder: BuilderStore) {
    this.builder = builder
    this.formId = builder.formId
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  get = () => this.state

  private set(patch: Partial<AiState>) {
    this.state = { ...this.state, ...patch }
    this.listeners.forEach((fn) => fn())
  }

  dispose() {
    this.abort?.abort()
    this.builder.setLocked(false)
  }

  // -- panel -------------------------------------------------------------------------------

  setOpen(open: boolean) {
    this.set({ open })
    if (open && !this.state.session && !this.state.loading) void this.load()
  }

  setComposer(composer: string) {
    this.set({ composer })
  }

  async load(fresh = false) {
    this.set({ loading: true, error: null })
    try {
      this.setSession(await aiApi.open(this.formId, fresh))
    } catch (err) {
      this.set({ error: codeOf(err) })
    } finally {
      this.set({ loading: false })
    }
  }

  async newChat() {
    if (this.state.busy) return
    this.set({ stale: false, filledIn: false })
    await this.load(true)
  }

  /** Take a session from the server and show its suggestion (if any) on the canvas. */
  private setSession(session: AiSession) {
    const proposal = session.proposal
    let preview = this.state.preview
    if (proposal) {
      preview = new BuilderStore(
        this.formId,
        { schema: proposal.schema, revision: 0, canUndo: false, canRedo: false },
        { readOnly: true },
      )
      const page = this.builder.get().pageId
      if (proposal.schema.pages.some((p) => p.id === page)) preview.setPage(page)
      // Nothing selected: the marker wash shows only what changed.
      preview.select({ type: 'element', id: '' })
      preview.setHighlight(changedIds(proposal))
    } else preview = null
    this.builder.setLocked(!!proposal)
    this.set({ session, preview, showing: 'suggestion' })
  }

  setShowing(showing: AiState['showing']) {
    this.set({ showing })
  }

  /** Jump the suggestion preview to a changed question. */
  reveal(id: string | null, pageId: string | null) {
    const preview = this.state.preview
    if (!preview) return
    this.set({ showing: 'suggestion' })
    if (pageId) preview.setPage(pageId)
    if (id) {
      preview.select({ type: 'element', id })
      window.requestAnimationFrame(() =>
        document.querySelector(`[data-ai-preview] [data-block="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' }),
      )
    }
  }

  // -- requests ----------------------------------------------------------------------------

  private onEvent = (e: AiEvent) => {
    const live = this.state.live
    if (!live) return
    switch (e.event) {
      case 'tool.applied':
      case 'tool.error':
        this.set({ live: { ...live, steps: [...live.steps, e.data] } })
        break
      case 'message.delta':
        this.set({ live: { ...live, reply: e.data.text } })
        break
      case 'filled_in':
        this.set({ filledIn: true })
        break
      default:
        break
    }
  }

  private async run(request: { text: string } | { file: File }) {
    if (this.state.busy) return
    this.lastRequest = request
    await this.builder.flush()
    if (this.builder.get().status !== 'saved') {
      this.set({ error: { code: 'unsaved' } })
      return
    }
    if (!this.state.session) await this.load()
    const session = this.state.session
    if (!session) return
    const abort = new AbortController()
    this.abort = abort
    this.set({
      busy: 'sending',
      error: null,
      filledIn: false,
      stale: false,
      live: {
        text: 'text' in request ? request.text : '',
        file: 'file' in request ? { name: request.file.name } : undefined,
        steps: [],
        reply: '',
      },
      composer: 'text' in request ? '' : this.state.composer,
    })
    try {
      if ('text' in request) await aiApi.send(this.formId, session.id, request.text, this.onEvent, abort.signal)
      else await aiApi.importFile(this.formId, session.id, request.file, this.onEvent, abort.signal)
    } catch (err) {
      if (!abort.signal.aborted) {
        this.set({ error: codeOf(err) })
        if ('text' in request && this.state.composer === '') this.set({ composer: request.text })
      }
    } finally {
      this.abort = null
      // A stopped request is recorded by the server as it closes; give it a moment.
      if (abort.signal.aborted) await new Promise((r) => window.setTimeout(r, 400))
      try {
        this.setSession(await aiApi.get(this.formId, session.id))
      } catch {
        // keep what we have
      }
      this.set({ busy: null, live: null })
    }
  }

  send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || trimmed.length > MAX_REQUEST) return
    void this.run({ text: trimmed })
  }

  importFile(file: File) {
    void this.run({ file })
  }

  retry() {
    if (this.lastRequest) void this.run(this.lastRequest)
  }

  stop() {
    const session = this.state.session
    if (!this.abort || !session) return
    void aiApi.cancel(this.formId, session.id).catch(() => undefined)
    this.abort.abort()
  }

  // -- suggestion --------------------------------------------------------------------------

  async apply() {
    const session = this.state.session
    const proposal = session?.proposal
    if (!session || !proposal || this.state.busy) return
    this.set({ busy: 'applying', error: null, stale: false })
    try {
      await this.builder.flush()
      const res = await aiApi.apply(this.formId, session.id, this.builder.get().saved.revision)
      this.builder.setLocked(false)
      this.builder.loadDraft(res.draft)
      this.builder.flash(changedIds(proposal))
      this.setSession(res.session)
      toast.success('Changes applied', {
        action: { label: 'Undo', onClick: () => void this.builder.undo() },
      })
    } catch (err) {
      if (err instanceof ApiError && err.detail === 'proposal_stale') this.set({ stale: true })
      else this.set({ error: codeOf(err) })
    } finally {
      this.set({ busy: null })
    }
  }

  async discard() {
    const session = this.state.session
    if (!session || this.state.busy) return
    this.set({ busy: 'discarding', error: null, stale: false })
    try {
      this.setSession(await aiApi.discard(this.formId, session.id))
    } catch (err) {
      this.set({ error: codeOf(err) })
    } finally {
      this.set({ busy: null })
    }
  }

  /** After a clash: drop the stale suggestion and ask the same thing of the current draft. */
  async askAgain() {
    const last = [...(this.state.session?.messages ?? [])].reverse().find((m) => m.role === 'user')
    await this.discard()
    if (last?.content.text) this.send(last.content.text)
  }
}

export const AiContext = createContext<AiController | null>(null)

/** The assistant for this builder, or null when AI is off. */
export function useAiController(): AiController | null {
  return useContext(AiContext)
}

const noSubscribe = () => () => {}

/** Select from the assistant's state; with no assistant (AI off) from the initial state. */
export function useAi<T>(ai: AiController | null, select: (s: AiState) => T): T {
  return useSyncExternalStore(ai ? ai.subscribe : noSubscribe, () => select(ai ? ai.get() : INITIAL))
}

/** The suggestion preview store, or null (also when AI is off). */
export function useSuggestion(): { ai: AiController; preview: NonNullable<AiState['preview']>; showing: AiState['showing'] } | null {
  const ai = useAiController()
  const preview = useAi(ai, (s) => s.preview)
  const showing = useAi(ai, (s) => s.showing)
  if (!ai || !preview) return null
  return { ai, preview, showing }
}
