/**
 * Builder state: the draft schema, selection, autosave and undo/redo (PHASE-2-SCREENS 2.3, 2.9).
 *
 * Edits apply locally at once and are autosaved as RFC 6902 patches (debounced 800 ms) against
 * the last saved revision. Undo first walks the local stack of edits that are not saved yet,
 * then the server's draft history (`POST /draft/undo|redo`).
 */
import { compare } from 'fast-json-patch'
import { createContext, useContext, useSyncExternalStore } from 'react'

import { api, ApiError, type Draft } from '@/lib/api'
import type { Form } from '@/schema'

export type Selection =
  | { type: 'form' }
  | { type: 'page'; pageId: string }
  | { type: 'element'; id: string }

export type SaveStatus = 'saved' | 'saving' | 'offline' | 'error'

export interface BuilderState {
  schema: Form
  saved: { schema: Form; revision: number }
  serverCanUndo: boolean
  serverCanRedo: boolean
  undoStack: Form[]
  redoStack: Form[]
  status: SaveStatus
  error: string | null
  conflict: boolean
  selection: Selection
  pageId: string
  /** The text being edited in place on the canvas (`textKey`), e.g. `label:full_name`. */
  editing: string | null
  /** Bumped when a block is picked outside its text: phones open the inspector drawer. */
  inspect: number
  /** Referenced questions to wash on the canvas (logic editor hover). */
  highlight: ReadonlySet<string>
  /** A delete that needs confirmation (other rules read the question), or a page delete. */
  confirm: { kind: 'element'; id: string } | { kind: 'page'; pageIndex: number } | null
  /** Command dialog "Add a question" is open. */
  inserting: boolean
  publishing: boolean
  /** Publish was tried once: the inspector shows missing-text errors without waiting for a blur. */
  publishTried: boolean
  /** An AI suggestion is shown on the canvas: nothing can be edited until it is applied or discarded. */
  locked: boolean
}

const SAVE_DELAY = 800
const UNDO_LIMIT = 100

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: string }
      return first.msg ?? `HTTP ${err.status}`
    }
    return typeof detail === 'string' ? detail : `HTTP ${err.status}`
  }
  return err instanceof Error ? err.message : String(err)
}

export class BuilderStore {
  private state: BuilderState
  private listeners = new Set<() => void>()
  private timer: number | undefined
  private inFlight: Promise<void> | null = null
  private retryTimer: number | undefined
  private flashing = false
  readonly formId: string
  /** A read-only store shows a form (an AI suggestion) on the canvas; edits do nothing. */
  readonly readOnly: boolean

  constructor(formId: string, draft: Draft, opts: { readOnly?: boolean } = {}) {
    this.formId = formId
    this.readOnly = !!opts.readOnly
    this.state = {
      schema: draft.schema,
      saved: { schema: draft.schema, revision: draft.revision },
      serverCanUndo: draft.canUndo,
      serverCanRedo: draft.canRedo,
      undoStack: [],
      redoStack: [],
      status: 'saved',
      error: null,
      conflict: false,
      selection: { type: 'form' },
      pageId: draft.schema.pages[0].id,
      editing: null,
      inspect: 0,
      highlight: new Set(),
      confirm: null,
      inserting: false,
      publishing: false,
      publishTried: false,
      locked: false,
    }
  }

  /** Start listening for reconnects (paired with dispose; safe to call again). */
  attach(): void {
    window.addEventListener('online', this.onOnline)
  }

  dispose(): void {
    window.removeEventListener('online', this.onOnline)
    window.clearTimeout(this.timer)
    window.clearTimeout(this.retryTimer)
  }

  private onOnline = () => {
    if (this.state.status === 'offline') void this.flush()
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  get = () => this.state

  private set(patch: Partial<BuilderState>) {
    this.state = { ...this.state, ...patch }
    this.listeners.forEach((fn) => fn())
  }

  // -- selection ---------------------------------------------------------------------------

  /** Select something; `edit` also starts editing one of its texts, `inspect` asks phones to
   * open the inspector drawer (a tap on the block outside its text). */
  select(selection: Selection, opts: { edit?: string; inspect?: boolean } = {}) {
    if (this.flashing) {
      this.flashing = false
      this.state = { ...this.state, highlight: new Set() }
    }
    const canEdit = !this.readOnly && !this.state.locked
    const patch: Partial<BuilderState> = { selection, editing: canEdit && opts.edit ? opts.edit : null }
    if (opts.inspect) patch.inspect = this.state.inspect + 1
    if (selection.type === 'page') patch.pageId = selection.pageId
    this.set(patch)
  }

  setPage(pageId: string) {
    this.set({ pageId, selection: { type: 'page', pageId }, editing: null })
  }

  setEditing(key: string | null) {
    if ((this.readOnly || this.state.locked) && key) return
    if (this.state.editing === key) return
    this.set({ editing: key })
  }

  setConfirm(confirm: BuilderState['confirm']) {
    if (this.readOnly || this.state.locked) return
    this.set({ confirm })
  }

  setInserting(inserting: boolean) {
    if ((this.readOnly || this.state.locked) && inserting) return
    this.set({ inserting })
  }

  /** Lock editing while an AI suggestion is shown on the canvas. */
  setLocked(locked: boolean) {
    this.set({ locked, editing: null, inserting: false, confirm: null })
  }

  /** Take a draft the server produced (an applied AI suggestion); local history is saved already. */
  loadDraft(draft: Draft) {
    this.set({
      schema: draft.schema,
      saved: { schema: draft.schema, revision: draft.revision },
      serverCanUndo: draft.canUndo,
      serverCanRedo: draft.canRedo,
      undoStack: [],
      redoStack: [],
      status: 'saved',
      error: null,
      ...this.fixSelection(draft.schema),
    })
  }

  setPublishing(publishing: boolean) {
    this.set(publishing ? { publishing, publishTried: true } : { publishing })
  }

  setHighlight(ids: Iterable<string>) {
    this.flashing = false
    this.set({ highlight: new Set(ids) })
  }

  /** Wash questions that just changed (an applied AI suggestion) until the next click. */
  flash(ids: Iterable<string>) {
    this.set({ highlight: new Set(ids) })
    this.flashing = true
  }

  // -- edits -------------------------------------------------------------------------------

  /** Apply a change to the draft; it shows at once and autosaves. */
  edit(change: (form: Form) => Form, after?: Partial<Pick<BuilderState, 'selection' | 'pageId' | 'editing'>>) {
    if (this.readOnly || this.state.locked) return
    const prev = this.state.schema
    const next = change(prev)
    if (next === prev) {
      if (after) this.set(after)
      return
    }
    this.set({
      schema: next,
      undoStack: [...this.state.undoStack, prev].slice(-UNDO_LIMIT),
      redoStack: [],
      ...this.fixSelection(next, after),
    })
    this.scheduleSave()
  }

  /** Keep the selection and current page pointing at things that exist. */
  private fixSelection(form: Form, after?: Partial<BuilderState>): Partial<BuilderState> {
    const out: Partial<BuilderState> = { ...after }
    const pageId = out.pageId ?? this.state.pageId
    if (!form.pages.some((p) => p.id === pageId)) out.pageId = form.pages[0].id
    const sel = out.selection ?? this.state.selection
    if (sel.type === 'page' && !form.pages.some((p) => p.id === sel.pageId))
      out.selection = { type: 'form' }
    if (sel.type === 'element' && !JSON.stringify(form.pages).includes(`"id":"${sel.id}"`))
      out.selection = { type: 'form' }
    return out
  }

  private scheduleSave() {
    window.clearTimeout(this.timer)
    this.timer = window.setTimeout(() => void this.flush(), SAVE_DELAY)
  }

  /** Save now (also used before server undo/redo and publish). */
  async flush(): Promise<void> {
    window.clearTimeout(this.timer)
    if (this.readOnly) return
    if (this.inFlight) {
      await this.inFlight
      if (compare(this.state.saved.schema, this.state.schema).length) return this.flush()
      return
    }
    const sent = this.state.schema
    const ops = compare(this.state.saved.schema, sent)
    if (!ops.length) {
      if (this.state.status !== 'saved') this.set({ status: 'saved', error: null })
      return
    }
    this.set({ status: 'saving' })
    this.inFlight = (async () => {
      try {
        const draft = await api.patchDraft(this.formId, this.state.saved.revision, ops)
        const untouched = this.state.schema === sent
        this.set({
          saved: { schema: draft.schema, revision: draft.revision },
          serverCanUndo: draft.canUndo,
          serverCanRedo: draft.canRedo,
          status: untouched ? 'saved' : 'saving',
          error: null,
          ...(untouched ? { schema: draft.schema, undoStack: [], redoStack: [] } : {}),
        })
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) this.set({ conflict: true, status: 'error' })
        else if (!(err instanceof ApiError) || !navigator.onLine) {
          this.set({ status: 'offline' })
          window.clearTimeout(this.retryTimer)
          this.retryTimer = window.setTimeout(() => void this.flush(), 10_000)
        } else this.set({ status: 'error', error: errorMessage(err) })
      } finally {
        this.inFlight = null
      }
    })()
    await this.inFlight
    if (this.state.status === 'saving') return this.flush()
  }

  get dirty(): boolean {
    return this.state.schema !== this.state.saved.schema
  }

  get canUndo(): boolean {
    if (this.readOnly || this.state.locked) return false
    return this.state.undoStack.length > 0 || (this.state.serverCanUndo && !this.dirty)
  }

  get canRedo(): boolean {
    if (this.readOnly || this.state.locked) return false
    return this.state.redoStack.length > 0 || (this.state.serverCanRedo && !this.dirty)
  }

  async undo(): Promise<void> {
    if (this.readOnly || this.state.locked) return
    const { undoStack, redoStack, schema } = this.state
    if (undoStack.length) {
      const prev = undoStack[undoStack.length - 1]
      this.set({ schema: prev, undoStack: undoStack.slice(0, -1), redoStack: [...redoStack, schema], ...this.fixSelection(prev) })
      this.scheduleSave()
      return
    }
    await this.serverStep('undo')
  }

  async redo(): Promise<void> {
    if (this.readOnly || this.state.locked) return
    const { undoStack, redoStack, schema } = this.state
    if (redoStack.length) {
      const next = redoStack[redoStack.length - 1]
      this.set({ schema: next, redoStack: redoStack.slice(0, -1), undoStack: [...undoStack, schema], ...this.fixSelection(next) })
      this.scheduleSave()
      return
    }
    await this.serverStep('redo')
  }

  private async serverStep(kind: 'undo' | 'redo') {
    await this.flush()
    if (this.dirty || this.state.status !== 'saved') return
    if (kind === 'undo' ? !this.state.serverCanUndo : !this.state.serverCanRedo) return
    this.set({ status: 'saving' })
    try {
      const draft = await (kind === 'undo' ? api.undo : api.redo)(this.formId, this.state.saved.revision)
      this.set({
        schema: draft.schema,
        saved: { schema: draft.schema, revision: draft.revision },
        serverCanUndo: draft.canUndo,
        serverCanRedo: draft.canRedo,
        status: 'saved',
        ...this.fixSelection(draft.schema),
      })
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) this.set({ conflict: true, status: 'error' })
      else this.set({ status: 'error', error: errorMessage(err) })
    }
  }

  /** After a conflict: load the latest draft and drop local changes. */
  async reload(): Promise<void> {
    const draft = await api.getDraft(this.formId)
    this.set({
      schema: draft.schema,
      saved: { schema: draft.schema, revision: draft.revision },
      serverCanUndo: draft.canUndo,
      serverCanRedo: draft.canRedo,
      undoStack: [],
      redoStack: [],
      status: 'saved',
      error: null,
      conflict: false,
      ...this.fixSelection(draft.schema),
    })
  }

  /** The unsaved change as JSON patch (offered for copying in the conflict dialog). */
  pendingPatch(): string {
    return JSON.stringify(compare(this.state.saved.schema, this.state.schema), null, 2)
  }
}

export const BuilderContext = createContext<BuilderStore | null>(null)

export function useStore(): BuilderStore {
  const store = useContext(BuilderContext)
  if (!store) throw new Error('useStore outside BuilderContext')
  return store
}

export function useBuilder<T>(select: (s: BuilderState) => T): T {
  const store = useStore()
  return useSyncExternalStore(store.subscribe, () => select(store.get()))
}

/** Select something (and optionally start editing one of its texts) in one step. */
export function useActivate(selection: Selection): (edit?: string) => void {
  const store = useStore()
  return (edit?: string) => store.select(selection, { edit })
}
