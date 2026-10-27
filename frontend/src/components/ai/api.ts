/**
 * AI assistant API (DESIGN 12, 17): sessions, streamed requests (Server-Sent Events over a
 * POST, read with fetch) and apply / discard / stop.
 */
import { ApiError, csrfToken, type Draft } from '@/lib/api'
import type { Form, FormLanguage } from '@/schema'

export type ChangeKind = 'added' | 'changed' | 'removed' | 'moved'

export interface Change {
  kind: 'element' | 'page' | 'settings'
  id: string | null
  label: string
  change: ChangeKind
  pageId: string | null
  /** changed elements: the properties that differ. */
  properties?: string[]
}

export interface Flag {
  targetId: string
  note: string
  label?: string
  source?: 'language' | 'security'
}

export interface Proposal {
  baseRevision: number
  schema: Form
  changes: Change[]
  flags: Flag[]
  language: FormLanguage
}

export interface Step {
  tool: string
  ok: boolean
  action: string
  label: string
  targetId: string | null
  error?: string
}

export type AiOutcome = 'ok' | 'error' | 'cancelled' | 'filled_in'

export interface AiMessage {
  id: string
  role: 'user' | 'assistant' | 'status'
  content: {
    text?: string
    attachment?: { name: string; pages: number; mime: string }
    steps?: Step[]
    status?: AiOutcome | 'applied' | 'discarded'
    error?: string | null
    changed?: boolean
  }
  createdAt: string
}

export interface AiSession {
  id: string
  mode: 'create' | 'edit' | 'import'
  status: 'idle' | 'proposal' | 'closed'
  provider: string
  model: string
  messages: AiMessage[]
  proposal: Proposal | null
}

export type AiEvent =
  | { event: 'message.delta'; data: { text: string } }
  | { event: 'tool.applied' | 'tool.error'; data: Step }
  | { event: 'proposal'; data: Proposal }
  | { event: 'error'; data: { code: string } }
  | { event: 'cancelled'; data: Record<string, never> }
  | { event: 'filled_in'; data: { note: string } }
  | { event: 'done'; data: { usage: { in: number; out: number } } }

/** Split a Server-Sent Events buffer into complete events plus the unfinished rest. */
export function parseSse(buffer: string): { events: AiEvent[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: AiEvent[] = []
  for (const block of blocks) {
    let event = ''
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (!event || !data.length) continue
    try {
      events.push({ event, data: JSON.parse(data.join('\n')) } as AiEvent)
    } catch {
      // ignore a malformed event
    }
  }
  return { events, rest }
}

async function json<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(method !== 'GET' ? { 'X-CSRF-Token': csrfToken() } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 204) return undefined as T
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

async function stream(
  path: string,
  init: { body: BodyInit; contentType: string },
  onEvent: (e: AiEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/v1${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Accept: 'text/event-stream', 'Content-Type': init.contentType, 'X-CSRF-Token': csrfToken() },
    body: init.body,
    signal,
  })
  if (!res.ok || !res.body) {
    const data: unknown = await res.json().catch(() => null)
    throw new ApiError(res.status, data)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    const parsed = parseSse(buffer + value)
    buffer = parsed.rest
    parsed.events.forEach(onEvent)
  }
  parseSse(buffer + '\n\n').events.forEach(onEvent)
}

const base = (formId: string) => `/forms/${formId}/ai/sessions`

export const aiApi = {
  open: (formId: string, fresh = false) => json<AiSession>('POST', base(formId), { fresh }),
  get: (formId: string, id: string) => json<AiSession>('GET', `${base(formId)}/${id}`),
  apply: (formId: string, id: string, baseRevision: number) =>
    json<{ draft: Draft; session: AiSession }>('POST', `${base(formId)}/${id}/apply`, { baseRevision }),
  discard: (formId: string, id: string) => json<AiSession>('POST', `${base(formId)}/${id}/discard`),
  cancel: (formId: string, id: string) => json<void>('POST', `${base(formId)}/${id}/cancel`),
  send: (formId: string, id: string, content: string, onEvent: (e: AiEvent) => void, signal: AbortSignal) =>
    stream(
      `${base(formId)}/${id}/messages`,
      { body: JSON.stringify({ content }), contentType: 'application/json' },
      onEvent,
      signal,
    ),
  importFile: (formId: string, id: string, file: File, onEvent: (e: AiEvent) => void, signal: AbortSignal) =>
    stream(
      `${base(formId)}/${id}/import?blankConfirmed=true&name=${encodeURIComponent(file.name)}`,
      { body: file, contentType: file.type || 'application/octet-stream' },
      onEvent,
      signal,
    ),
}
