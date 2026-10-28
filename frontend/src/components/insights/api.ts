/**
 * Insights summaries and "Ask your submissions" (DESIGN 15.4, 12.6): the summary request, and
 * the AI chat (Server-Sent Events over a POST, read with fetch like the builder assistant).
 */
import { parseSse } from '@/components/ai/api'
import { ApiError, csrfToken, filterParams, type Condition, type ListFilters } from '@/lib/api'
import type { FieldType } from '@/schema'

export interface Bar {
  key: string | number | boolean
  label: string
  count: number
  percent: number
  where: Condition[]
}

interface Base {
  key: string
  type: FieldType
  label: string
  repeater: string | null
  versions: number[]
  sensitive: boolean
  answered: number
}

export interface ChoiceSummary extends Base {
  kind: 'choice'
  multi: boolean
  noAnswer: number
  bars: Bar[]
  other?: { count: number; percent: number; texts: { text: string; count: number }[]; where: Condition[] }
  truncated?: boolean
}

export interface NumberSummary extends Base {
  kind: 'number'
  stats: { min: number | null; avg: number | null; median: number | null; max: number | null; sum: number | null }
  bins: (Bar & { from: number; to: number })[]
}

export interface DateSummary extends Base {
  kind: 'date'
  bucket: 'month' | 'year'
  bars: Bar[]
  min: string | null
  max: string | null
}

export interface TextSummary extends Base {
  kind: 'text' | 'sensitive'
  examples: { ref: number; text: string }[]
  where: Condition[]
}

export interface PresenceSummary extends Base {
  kind: 'file' | 'signature'
  where: Condition[]
}

export type QuestionSummary = ChoiceSummary | NumberSummary | DateSummary | TextSummary | PresenceSummary

export interface RepeaterSummary {
  key: string
  type: 'repeater'
  label: string
  versions: number[]
  mapped: boolean
  rows: number
  submissions: number
  avgRows: number
  questions: QuestionSummary[]
}

export interface Insights {
  total: number
  language: 'en' | 'dv'
  questions: QuestionSummary[]
  repeaters: RepeaterSummary[]
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

// -- Ask your submissions ---------------------------------------------------------------

export interface QueryStep {
  tool: 'query_submissions' | 'list_submissions' | 'read_answers' | string
  ok: boolean
  error?: string
  queryId?: string
  description?: string
  matched?: { submissions: number; rows?: number }
  unit?: string
  where?: { where: Condition[]; whereAny: Condition[] }
  aggregates?: Record<string, number | string | null>
  groups?: { label: Record<string, string>; count?: number; [k: string]: unknown }[]
  fields?: string[]
  fieldLabels?: string[]
  count?: number
}

export interface ChartSpec {
  queryId: string
  /** list: matching submissions with the answers to `columns` (read on the server). */
  display: 'bar' | 'table' | 'list'
  title: string
  unit: string
  columns: string[]
  /** list: the questions' labels. */
  columnLabels?: Record<string, string>
  /** list: each column's question type ("meta" for submission details). */
  columnTypes?: Record<string, string>
  rows: { label: string; ref?: number; values: Record<string, number | string | null> }[]
  /** list: how many submissions match (rows holds the newest of them). */
  total?: number
  /** list: how many listed submissions answered each column. */
  answered?: Record<string, number>
  /** list: columns that are sensitive questions. */
  sensitive?: string[]
  truncated: boolean
  /** list in a stored answer: the rows are read again when it is shown (askList). */
  stored?: boolean
  /** list stored by an older version: its rows were removed and can't be read again. */
  expired?: boolean
}

/** The submissions an answer is about ("Show these N submissions"): the count it quotes. */
export interface AnswerLink {
  queryId: string
  /** count / group: one number (shown big); breakdown: a grouped query; all: every submission. */
  kind: 'count' | 'group' | 'breakdown' | 'all'
  count: number
  total: number | null
  description: string
  where: { where: Condition[]; whereAny: Condition[] }
}

/** removed: submissions the answer may have used were erased, so it was taken out. */
export type AskStatus = 'ok' | 'error' | 'cancelled' | 'removed'

export interface AskMessage {
  id: string
  role: 'user' | 'assistant'
  content: {
    text?: string
    steps?: QueryStep[]
    charts?: ChartSpec[]
    link?: AnswerLink | null
    status?: AskStatus
    error?: string | null
    /** Whole numbers in the reply that no counted result contains (checked on the server). */
    unverifiedNumbers?: number[]
  }
  createdAt: string
}

export interface AskState {
  id: string | null
  messages: AskMessage[]
  readAnswers: boolean
}

export type AskEvent =
  | { event: 'message.delta'; data: { text: string } }
  | { event: 'tool.applied' | 'tool.error'; data: QueryStep }
  | { event: 'chart'; data: ChartSpec }
  | { event: 'link'; data: AnswerLink }
  | { event: 'check'; data: { unverifiedNumbers: number[] } }
  | { event: 'error'; data: { code: string } }
  | { event: 'cancelled'; data: Record<string, never> }
  | { event: 'done'; data: { usage: { in: number; out: number } } }

async function stream(path: string, body: unknown, onEvent: (e: AskEvent) => void, signal: AbortSignal) {
  const res = await fetch(`/api/v1${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    const data: unknown = await res.json().catch(() => null)
    throw new ApiError(res.status, data)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  const emit = (events: unknown[]) => events.forEach((e) => onEvent(e as AskEvent))
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    const parsed = parseSse(buffer + value)
    buffer = parsed.rest
    emit(parsed.events)
  }
  emit(parseSse(buffer + '\n\n').events)
}

/** Where people get stuck: anonymous counters for the last 30 days (all versions). */
export interface Friction {
  enabled: boolean
  from: string
  to: string
  days: number
  /** Visits that reached each page (page key). */
  pages: { page: string; visits: number }[]
  started: number
  submitted: number
  /** Questions by visits shown a problem, most first; `codes` counts each problem code. */
  fields: { field: string; page: string; total: number; codes: Record<string, number> }[]
  codes: { code: string; count: number }[]
}

export const insightsApi = {
  summary: (formId: string, filters: ListFilters) =>
    json<Insights>('GET', `/forms/${formId}/insights?${filterParams(filters).toString()}`),
  friction: (formId: string) => json<Friction>('GET', `/forms/${formId}/insights/friction`),
  askState: (formId: string) => json<AskState>('GET', `/forms/${formId}/ask`),
  askOpen: (formId: string, fresh = false) => json<AskState>('POST', `/forms/${formId}/ask/sessions`, { fresh }),
  ask: (formId: string, sessionId: string, content: string, onEvent: (e: AskEvent) => void, signal: AbortSignal) =>
    stream(`/forms/${formId}/ask/sessions/${sessionId}/messages`, { content }, onEvent, signal),
  /** The rows of a list in a stored answer, read now (deleted submissions left out). */
  askList: (formId: string, messageId: string, index: number) =>
    json<ChartSpec>('GET', `/forms/${formId}/ask/messages/${messageId}/lists/${index}`),
  cancel: (formId: string, sessionId: string) => json<void>('POST', `/forms/${formId}/ask/sessions/${sessionId}/cancel`),
}

/** Plain-English text for an error code from the stream or the API. */
export function askErrorText(code: string | null | undefined): string {
  switch (code) {
    case 'ai_budget_exceeded':
      return "Today's AI allowance is used up. Try again tomorrow."
    case 'too_many_requests':
      return 'Too many questions in a short time. Wait a few minutes and ask again.'
    case 'too_large':
      return 'This question needs too much data at once. Ask about fewer questions or submissions, or start a new chat.'
    case 'timeout':
      return 'That took too long. Try a simpler question.'
    case 'provider_unavailable':
      return "The AI service didn't respond. Try again in a moment."
    case 'tool_limit':
    case 'no_valid_result':
      return "The AI couldn't work out how to count that. Try asking it another way."
    case 'ai_busy':
      return 'Still answering your last question.'
    case 'internal':
      return 'Something went wrong while counting. Try again.'
    default:
      return "Couldn't get an answer. Try again."
  }
}

/** The reply as plain text: models sometimes add Markdown emphasis anyway. */
export function plain(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, '$1').replace(/^#{1,6}\s+/gm, '')
}
