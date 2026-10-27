/**
 * "Ask your submissions" (INSIGHTS-SCREENS 4): a chat over the form's submissions, built like
 * the builder's assistant panel (header, conversation, composer). The AI counts with tools on
 * the server; each answer leads with the number it counted, shows any chart, table or list
 * drawn from the counted result (never from the AI's words), links to exactly the submissions
 * it counted, and says how it was calculated. One chat per person and form.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import {
  ArrowUpIcon,
  CalculatorIcon,
  CheckIcon,
  ChevronDownIcon,
  CopyIcon,
  ListIcon,
  MessageSquarePlusIcon,
  RotateCcwIcon,
  SparklesIcon,
  SquareIcon,
  TriangleAlertIcon,
  XIcon,
} from 'lucide-react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { useFormSummary } from '@/components/builder/form-context'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { FieldError } from '@/components/ui/field'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from '@/components/ui/input-group'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, type Condition } from '@/lib/api'
import { versionQuery } from '@/lib/queries'
import { formLanguage } from '@/schema/language'

import {
  askErrorText,
  insightsApi,
  plain,
  type AnswerLink,
  type AskMessage,
  type AskState,
  type ChartSpec,
  type QueryStep,
} from './api'
import { askExamples, fieldLabels } from './ask-examples'
import { useAsk } from './ask-state'
import { BarList } from './charts'
import { ListTable } from './list-table'

const MAX = 2000

const thaana = /[ހ-޿]/

const OPS: Record<string, string> = {
  count: 'Count',
  sum: 'Total',
  avg: 'Average',
  min: 'Lowest',
  max: 'Highest',
  median: 'Median',
  distinct: 'Different answers',
}

function columnLabel(col: string, labels: Map<string, string>, unit: string): string {
  if (col === 'count') return unit.startsWith('rows') ? 'Rows' : 'Submissions'
  if (col === 'value') return 'Value'
  const [op, key] = col.split(':')
  return `${OPS[op] ?? op}${key ? ` of ${labels.get(key) ?? key}` : ''}`
}

function rowLabel(label: string, labels: Map<string, string>): string {
  const [op, key] = label.split(':')
  return key && OPS[op] ? `${OPS[op]} of ${labels.get(key) ?? key}` : label
}

const count = (n: number) => n.toLocaleString('en')
const plural = (n: number, one: string, many = `${one}s`) => `${count(n)} ${n === 1 ? one : many}`

function langOf(text: string, language: string) {
  return thaana.test(text) ? 'dv' : language === 'dv' ? 'dv' : 'en'
}

function ResultChart({
  chart,
  labels,
  language,
  formId,
}: {
  chart: ChartSpec
  labels: Map<string, string>
  language: string
  formId: string
}) {
  const first = chart.columns[0]
  const numeric = chart.rows.every((r) => typeof r.values[first] === 'number')
  return (
    <figure className="flex min-w-0 flex-col gap-2">
      {chart.title && (
        <figcaption className="text-sm font-medium">
          <bdi dir="auto">{chart.title}</bdi>
        </figcaption>
      )}
      {chart.display === 'list' ? (
        <ListTable chart={chart} formId={formId} language={language} />
      ) : chart.display === 'bar' && numeric && chart.columns.length === 1 ? (
        <BarList
          data={chart.rows.map((r, i) => ({
            id: String(i),
            label: rowLabel(r.label, labels),
            count: Number(r.values[first]),
            muted: r.label === 'Other',
          }))}
          language={language}
          unit={chart.unit}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead />
              {chart.columns.map((c) => (
                <TableHead key={c} className="text-end">
                  {columnLabel(c, labels, chart.unit)}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {chart.rows.map((r, i) => (
              <TableRow key={i}>
                <TableCell className="whitespace-normal">
                  <bdi dir="auto" lang={langOf(r.label, language)}>
                    {rowLabel(r.label, labels)}
                  </bdi>
                </TableCell>
                {chart.columns.map((c) => (
                  <TableCell key={c} className="text-end tabular-nums">
                    {r.values[c] ?? '-'}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {chart.truncated && chart.display !== 'list' && (
        <p className="text-xs text-muted-foreground">Showing the largest groups only.</p>
      )}
    </figure>
  )
}

function matchedText(step: QueryStep): string {
  const m = step.matched
  if (!m) return ''
  const subs = plural(m.submissions, 'submission')
  return m.rows !== undefined ? `${plural(m.rows, 'row')} in ${subs}` : subs
}

/** Older answers carry no link: the newest query, as before. */
function fallbackLink(steps: QueryStep[]): AnswerLink | null {
  const main = [...steps].reverse().find((s) => s.ok && s.tool === 'query_submissions' && s.matched)
  if (!main?.matched) return null
  return {
    queryId: main.queryId ?? '',
    kind: main.where?.where?.length || main.where?.whereAny?.length ? 'count' : 'all',
    count: main.matched.submissions,
    total: null,
    description: main.description ?? '',
    where: main.where ?? { where: [], whereAny: [] },
  }
}

type Conditions = { where?: Condition[]; whereAny?: Condition[] }

function useOpenList(formId: string, onNavigate?: () => void) {
  const navigate = useNavigate()
  return (w: Conditions | undefined, label: string) => {
    onNavigate?.()
    void navigate({
      to: '/forms/$formId/submissions',
      params: { formId },
      search: {
        status: 'all',
        where: w?.where?.length ? w.where : undefined,
        whereAny: w?.whereAny?.length ? w.whereAny : undefined,
        whereLabel: label,
      },
    } as never)
  }
}

function Calculation({ steps, formId, onNavigate }: { steps: QueryStep[]; formId: string; onNavigate?: () => void }) {
  const open = useOpenList(formId, onNavigate)
  const done = steps.filter((s) => s.ok && s.description)
  if (!done.length) return null
  return (
    <Collapsible className="w-full">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="group -ms-2.5 text-muted-foreground">
          <CalculatorIcon />
          How this was calculated
          <ChevronDownIcon className="transition-transform group-data-[state=open]:rotate-180" />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ol className="flex list-decimal flex-col gap-2 ps-5 pt-1 text-sm">
          {done.map((s, i) => (
            <li key={i}>
              {s.tool === 'read_answers' && (
                <span>
                  Read the answers to {(s.fieldLabels ?? []).map((l) => `“${l}”`).join(', ')} in{' '}
                  {plural(s.count ?? 0, 'submission')}.{' '}
                </span>
              )}
              {s.tool === 'list_submissions' && (
                <span>Listed {(s.fieldLabels ?? []).map((l) => `“${l}”`).join(', ')}. </span>
              )}
              <bdi dir="auto">{s.description}</bdi>
              {s.matched && (s.tool === 'query_submissions' || s.tool === 'list_submissions') && (
                <span className="text-muted-foreground tabular-nums">: {matchedText(s)}</span>
              )}
              {s.where && (
                <Button
                  variant="link"
                  size="sm"
                  className="h-auto px-1 align-baseline"
                  onClick={() => open(s.where, s.description ?? '')}
                >
                  Show them
                </Button>
              )}
            </li>
          ))}
        </ol>
      </CollapsibleContent>
    </Collapsible>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const t = window.setTimeout(() => setCopied(false), 2000)
    return () => window.clearTimeout(t)
  }, [copied])
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={copied ? 'Answer copied' : 'Copy answer'}
          onClick={() =>
            void navigator.clipboard.writeText(text).then(
              () => setCopied(true),
              () => toast("Couldn't copy the answer"),
            )
          }
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{copied ? 'Copied' : 'Copy answer'}</TooltipContent>
    </Tooltip>
  )
}

function Headline({ link }: { link: AnswerLink }) {
  if (link.kind !== 'count' && link.kind !== 'group') return null
  const of = link.total !== null && link.total !== undefined && link.total !== link.count ? link.total : null
  return (
    <p className="flex flex-wrap items-baseline gap-x-2">
      <span className="text-3xl leading-none font-semibold tracking-tight tabular-nums">{count(link.count)}</span>
      <span className="text-sm text-muted-foreground">
        {of !== null ? `of ${plural(of, 'submission')}` : link.count === 1 ? 'submission' : 'submissions'}
      </span>
    </p>
  )
}

function Answer({
  msg,
  question,
  formId,
  labels,
  language,
  busy,
  onRetry,
  onNavigate,
}: {
  msg: AskMessage
  question: string
  formId: string
  labels: Map<string, string>
  language: string
  busy: boolean
  onRetry: (question: string) => void
  onNavigate?: () => void
}) {
  const c = msg.content
  const open = useOpenList(formId, onNavigate)
  const steps = c.steps ?? []
  const link = c.status === 'ok' ? (c.link ?? fallbackLink(steps)) : null
  const text = c.text ? plain(c.text) : ''
  if (c.status !== 'ok')
    return (
      <div className="flex flex-col items-start gap-2">
        {c.status === 'cancelled' ? (
          <p className="text-sm text-muted-foreground">Stopped before an answer.</p>
        ) : (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertDescription>{askErrorText(c.error)}</AlertDescription>
          </Alert>
        )}
        <Button variant="outline" size="sm" disabled={busy} onClick={() => onRetry(question)}>
          <RotateCcwIcon />
          {c.status === 'cancelled' ? 'Ask again' : 'Try again'}
        </Button>
      </div>
    )
  return (
    <Card size="sm" className="min-w-0 gap-3 rounded-md py-3 shadow-none ring-0 border">
      <CardContent className="flex min-w-0 flex-col gap-3 px-3">
        {link && <Headline link={link} />}
        {text && (
          <p className="text-sm whitespace-pre-wrap" dir="auto">
            {text}
          </p>
        )}
        {(c.charts ?? []).map((chart, i) => (
          <ResultChart key={i} chart={chart} labels={labels} language={language} formId={formId} />
        ))}
        <Calculation steps={steps} formId={formId} onNavigate={onNavigate} />
      </CardContent>
      <CardFooter className="flex flex-wrap items-center gap-2 border-t px-3 pt-3! pb-0">
        {link && link.count > 0 && (
          <Button variant="outline" size="sm" onClick={() => open(link.where, link.description)}>
            <ListIcon />
            {link.count === 1 ? 'Show this submission' : `Show these ${count(link.count)} submissions`}
          </Button>
        )}
        {text && (
          <div className="ms-auto">
            <CopyButton text={text} />
          </div>
        )}
      </CardFooter>
    </Card>
  )
}

function Question({ text }: { text: string }) {
  return (
    <p className="max-w-[85%] self-end rounded-lg bg-secondary px-3 py-2 text-sm whitespace-pre-wrap" dir="auto">
      <span className="sr-only">You asked: </span>
      {text}
    </p>
  )
}

interface Live {
  question: string
  steps: QueryStep[]
  charts: ChartSpec[]
  text: string
}

export function AskPanel({
  title,
  onClose,
  onNavigate,
}: {
  /** The panel's heading (a dialog title inside the phone sheet). */
  title: ReactNode
  onClose: () => void
  /** After "Show these submissions" opens the list (the phone sheet closes). */
  onNavigate?: () => void
}) {
  const form = useFormSummary()
  const formId = form.id
  const client = useQueryClient()
  const key = ['ask', formId]
  const state = useQuery({ queryKey: key, queryFn: () => insightsApi.askState(formId), retry: false })
  const schema = useQuery(versionQuery(formId, form.currentVersion)).data?.schema
  const [text, setText] = useState('')
  const [live, setLive] = useState<Live | null>(null)
  const [failed, setFailed] = useState<{ question: string; message: string } | null>(null)
  const [showAll, setShowAll] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const sessionId = useRef<string | null>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)
  const stick = useRef(true)
  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => {
    composer.current?.focus()
  }, [])

  const data = state.data
  useEffect(() => {
    if (data?.id) sessionId.current = data.id
  }, [data?.id])
  const messages = data?.messages ?? []
  const labels = fieldLabels(schema)
  const language = schema ? formLanguage(schema) : 'en'

  // Follow new content while answering unless the person scrolled up; when an answer lands,
  // bring its question to the top so the answer reads from its start.
  const lastPair = useRef<HTMLDivElement>(null)
  const landed = useRef(false)
  useLayoutEffect(() => {
    const el = viewport.current?.querySelector<HTMLElement>('[data-slot=scroll-area-viewport]')
    if (!el) return
    if (landed.current && lastPair.current) {
      landed.current = false
      el.scrollTop += lastPair.current.getBoundingClientRect().top - el.getBoundingClientRect().top - 12
    } else if (stick.current) el.scrollTop = el.scrollHeight
  })

  const send = async (question: string) => {
    const q = question.trim()
    if (!q || live || q.length > MAX) return
    setFailed(null)
    setText('')
    stick.current = true
    setLive({ question: q, steps: [], charts: [], text: '' })
    const ctrl = new AbortController()
    abort.current = ctrl
    try {
      let sid = sessionId.current
      if (!sid) {
        const opened = await insightsApi.askOpen(formId)
        sid = opened.id
        sessionId.current = sid
      }
      if (!sid) throw new Error('no session')
      await insightsApi.ask(
        formId,
        sid,
        q,
        (e) => {
          if (e.event === 'tool.applied' || e.event === 'tool.error')
            setLive((l) => (l ? { ...l, steps: [...l.steps, e.data] } : l))
          else if (e.event === 'chart') setLive((l) => (l ? { ...l, charts: [...l.charts, e.data] } : l))
          else if (e.event === 'message.delta') setLive((l) => (l ? { ...l, text: l.text + e.data.text } : l))
        },
        ctrl.signal,
      )
    } catch (err) {
      if (!ctrl.signal.aborted) {
        const code = err instanceof ApiError ? String((err.body as { detail?: string } | null)?.detail ?? '') : ''
        setFailed({ question: q, message: askErrorText(code) })
      }
    } finally {
      abort.current = null
      await client.invalidateQueries({ queryKey: key })
      landed.current = stick.current
      setLive(null)
      composer.current?.focus()
    }
  }

  // A question chosen on the Insights page (an example) waits here until the panel is ready.
  const ask = useAsk()
  const sendRef = useRef(send)
  useLayoutEffect(() => {
    sendRef.current = send
  })
  const queued = ask?.queued ?? null
  const clearQueued = ask?.clearQueued
  const busy = !!live || state.isPending
  useEffect(() => {
    if (!queued || busy) return
    clearQueued?.()
    void sendRef.current(queued)
  }, [queued, busy, clearQueued])

  const stop = () => {
    if (sessionId.current) void insightsApi.cancel(formId, sessionId.current).catch(() => undefined)
  }

  const fresh = async () => {
    abort.current?.abort()
    setFailed(null)
    setShowAll(false)
    const opened = await insightsApi.askOpen(formId, true)
    sessionId.current = opened.id
    client.setQueryData<AskState>(key, opened)
    composer.current?.focus()
  }

  const pairs: { q: AskMessage; a?: AskMessage }[] = []
  for (const m of messages) {
    if (m.role === 'user') pairs.push({ q: m })
    else if (pairs.length) pairs[pairs.length - 1].a = m
  }
  const hidden = showAll ? 0 : Math.max(0, pairs.length - 3)
  const tooLong = text.length > MAX
  const canSend = !live && !tooLong && text.trim().length > 0
  const ideas = askExamples(schema, !!data?.readAnswers)

  return (
    <div className="flex h-full min-h-0 flex-col bg-card">
      <div className="flex items-center gap-1 border-b px-3 py-2">
        <div className="me-auto min-w-0">{title}</div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              aria-label="New chat"
              disabled={!!live || !pairs.length}
              onClick={() => void fresh()}
            >
              <MessageSquarePlusIcon />
              <span className="max-sm:hidden">New chat</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>Start over with an empty chat</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Close Ask your submissions" onClick={onClose}>
              <XIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Close</TooltipContent>
        </Tooltip>
      </div>
      <div ref={viewport} className="min-h-0 flex-1">
        <ScrollArea
          className="h-full [&_[data-slot=scroll-area-viewport]>div]:block!"
          onScrollCapture={(e) => {
            const el = e.target as HTMLElement
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
          }}
        >
          <div role="log" aria-live="polite" aria-busy={!!live} className="flex flex-col gap-4 p-3">
            {state.isPending ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Spinner />
                Opening the chat…
              </p>
            ) : state.isError ? (
              <Alert variant="destructive">
                <TriangleAlertIcon />
                <AlertDescription className="flex flex-col items-start gap-2">
                  Couldn't open the chat. Check your connection.
                  <Button size="sm" variant="outline" onClick={() => void state.refetch()}>
                    Try again
                  </Button>
                </AlertDescription>
              </Alert>
            ) : (
              !pairs.length &&
              !live && (
                <div className="flex flex-col gap-3 py-2">
                  <div className="flex items-start gap-3">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <SparklesIcon className="size-4" aria-hidden />
                    </span>
                    <div className="flex flex-col gap-1">
                      <h3 className="text-sm font-medium">Ask about this form's submissions</h3>
                      <p className="text-sm text-muted-foreground">
                        Answers are counted from the submissions, and every answer links to the ones it counted.
                      </p>
                    </div>
                  </div>
                  {ideas.length > 0 && (
                    <div className="flex flex-col items-start gap-2">
                      <p className="text-xs font-medium text-muted-foreground">Try asking</p>
                      <div className="flex flex-wrap gap-2">
                        {ideas.map((idea) => (
                          <Button
                            key={idea}
                            variant="outline"
                            size="sm"
                            className="h-auto max-w-full py-1.5 text-start font-normal whitespace-normal"
                            onClick={() => void send(idea)}
                          >
                            <bdi dir="auto" lang={langOf(idea, language)}>
                              {idea}
                            </bdi>
                          </Button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            )}
            {hidden > 0 && (
              <Button variant="ghost" size="sm" className="self-start text-muted-foreground" onClick={() => setShowAll(true)}>
                Show {plural(hidden, 'earlier question')}
              </Button>
            )}
            {pairs.slice(hidden).map(({ q, a }, i, shown) => (
              <div key={q.id} ref={i === shown.length - 1 ? lastPair : undefined} className="flex flex-col gap-2">
                <Question text={q.content.text ?? ''} />
                {a && (
                  <Answer
                    msg={a}
                    question={q.content.text ?? ''}
                    formId={formId}
                    labels={labels}
                    language={language}
                    busy={!!live}
                    onRetry={(question) => void send(question)}
                    onNavigate={onNavigate}
                  />
                )}
              </div>
            ))}
            {live && (
              <div className="flex flex-col gap-2">
                <Question text={live.question} />
                <Card size="sm" className="gap-2 rounded-md py-3 shadow-none ring-0 border">
                  <CardContent className="flex flex-col gap-2 px-3">
                    {live.text && (
                      <p className="text-sm whitespace-pre-wrap" dir="auto">
                        {plain(live.text)}
                      </p>
                    )}
                    {live.charts.map((chart, i) => (
                      <ResultChart key={i} chart={chart} labels={labels} language={language} formId={formId} />
                    ))}
                    <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
                      {live.steps
                        .filter((s) => s.ok && s.description)
                        .map((s, i) => (
                          <li key={i}>
                            <bdi dir="auto">{s.description}</bdi>
                            {s.matched && <span className="tabular-nums">: {matchedText(s)}</span>}
                          </li>
                        ))}
                      <li className="flex items-center gap-2">
                        <Spinner />
                        {live.steps.length ? 'Counting…' : 'Reading your question…'}
                      </li>
                    </ul>
                  </CardContent>
                </Card>
              </div>
            )}
            {failed && !live && (
              <Alert variant="destructive">
                <TriangleAlertIcon />
                <AlertDescription className="flex flex-col items-start gap-2">
                  {failed.message}
                  <Button size="sm" variant="outline" onClick={() => void send(failed.question)}>
                    <RotateCcwIcon />
                    Try again
                  </Button>
                </AlertDescription>
              </Alert>
            )}
          </div>
        </ScrollArea>
      </div>
      <div className="flex flex-col gap-2 border-t p-3">
        <InputGroup>
          <InputGroupTextarea
            ref={composer}
            id="ask-composer"
            aria-label="Question about the submissions"
            placeholder="Ask a question about the submissions…"
            dir="auto"
            rows={1}
            className="max-h-40 min-h-11"
            value={text}
            aria-invalid={tooLong || undefined}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                if (canSend) void send(text)
              } else if (e.key === 'Escape' && live) {
                e.preventDefault()
                e.stopPropagation()
                stop()
              }
            }}
          />
          <InputGroupAddon align="block-end" className="justify-between">
            <span className="text-xs text-muted-foreground max-sm:hidden">Enter to send, Shift+Enter for a new line</span>
            {live ? (
              <InputGroupButton variant="outline" size="sm" className="ms-auto" onClick={stop}>
                <SquareIcon />
                Stop
              </InputGroupButton>
            ) : (
              <InputGroupButton
                variant="default"
                size="icon-sm"
                aria-label="Ask (Enter)"
                aria-disabled={!canSend}
                className="ms-auto aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
                onClick={() => canSend && void send(text)}
              >
                <ArrowUpIcon />
              </InputGroupButton>
            )}
          </InputGroupAddon>
        </InputGroup>
        {tooLong && <FieldError>Keep questions under 2,000 characters.</FieldError>}
      </div>
    </div>
  )
}
