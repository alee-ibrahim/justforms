/**
 * "Ask your submissions" (INSIGHTS-SCREENS 4): a question box over the form's submissions.
 * The AI counts with tools on the server; each answer shows how it was calculated, a link to
 * the matching submissions and, when the AI asks for one, a chart or table drawn from the
 * counted result. One chat per person and form; hidden when the install has no AI provider.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import {
  ArrowUpIcon,
  CalculatorIcon,
  ChevronDownIcon,
  ListIcon,
  MessageSquarePlusIcon,
  SquareIcon,
  TriangleAlertIcon,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { FieldError } from '@/components/ui/field'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from '@/components/ui/input-group'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, type FormRole } from '@/lib/api'

import { askErrorText, insightsApi, type AskMessage, type AskState, type ChartSpec, type Insights, type QueryStep } from './api'
import { BarList } from './charts'

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

function ResultChart({ chart, labels, language }: { chart: ChartSpec; labels: Map<string, string>; language: string }) {
  const first = chart.columns[0]
  const numeric = chart.rows.every((r) => typeof r.values[first] === 'number')
  return (
    <figure className="flex min-w-0 flex-col gap-2 rounded-md border p-3">
      {chart.title && (
        <figcaption className="text-sm font-medium">
          <bdi dir="auto">{chart.title}</bdi>
        </figcaption>
      )}
      {chart.display === 'bar' && numeric && chart.columns.length === 1 ? (
        <BarList
          data={chart.rows.map((r, i) => ({ id: String(i), label: rowLabel(r.label, labels), count: Number(r.values[first]), muted: r.label === 'Other' }))}
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
                  <bdi dir="auto" lang={thaana.test(r.label) ? 'dv' : 'en'}>
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
      {chart.truncated && <p className="text-xs text-muted-foreground">Showing the largest groups only.</p>}
    </figure>
  )
}

function matchedText(step: QueryStep): string {
  const m = step.matched
  if (!m) return ''
  const subs = `${m.submissions} submission${m.submissions === 1 ? '' : 's'}`
  return m.rows !== undefined ? `${m.rows} row${m.rows === 1 ? '' : 's'} in ${subs}` : subs
}

function Calculation({ steps, formId }: { steps: QueryStep[]; formId: string }) {
  const navigate = useNavigate()
  const done = steps.filter((s) => s.ok && s.description)
  if (!done.length) return null
  const open = (s: QueryStep) =>
    void navigate({
      to: '/forms/$formId/submissions',
      params: { formId },
      search: {
        status: 'all',
        where: s.where?.where?.length ? s.where.where : undefined,
        whereAny: s.where?.whereAny?.length ? s.where.whereAny : undefined,
        whereLabel: s.description,
      },
    } as never)
  const main = [...done].reverse().find((s) => s.tool === 'query_submissions') ?? done[done.length - 1]
  return (
    <div className="flex flex-col items-start gap-1">
      {main.matched && (
        <Button variant="link" size="sm" className="h-auto px-0" onClick={() => open(main)}>
          <ListIcon />
          Show {main.matched.submissions === 1 ? 'this submission' : `these ${main.matched.submissions} submissions`}
        </Button>
      )}
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
                <span>
                  {s.tool === 'read_answers'
                    ? `Read the answers to ${(s.fieldLabels ?? []).map((l) => `“${l}”`).join(', ')} in ${s.count} submission${s.count === 1 ? '' : 's'}. `
                    : ''}
                </span>
                <bdi dir="auto">{s.description}</bdi>
                {s.matched && s.tool === 'query_submissions' && (
                  <span className="text-muted-foreground tabular-nums">: {matchedText(s)}</span>
                )}
                {s.where && (
                  <Button variant="link" size="sm" className="h-auto px-1 align-baseline" onClick={() => open(s)}>
                    Show them
                  </Button>
                )}
              </li>
            ))}
          </ol>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

function Answer({
  msg,
  formId,
  labels,
  language,
}: {
  msg: AskMessage
  formId: string
  labels: Map<string, string>
  language: string
}) {
  const c = msg.content
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {c.status === 'ok' && c.text && (
        <p className="text-sm whitespace-pre-wrap" dir="auto">
          {c.text}
        </p>
      )}
      {c.status === 'cancelled' && <p className="text-sm text-muted-foreground">Stopped.</p>}
      {c.status === 'error' && (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertDescription>{askErrorText(c.error)}</AlertDescription>
        </Alert>
      )}
      {(c.charts ?? []).map((chart, i) => (
        <ResultChart key={i} chart={chart} labels={labels} language={language} />
      ))}
      {c.status === 'ok' && <Calculation steps={c.steps ?? []} formId={formId} />}
    </div>
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

function examples(data: Insights | undefined, readAnswers: boolean): string[] {
  const out: string[] = []
  const qs = data?.questions ?? []
  const choice = qs.find((q) => q.kind === 'choice' && q.type === 'multi_choice' && q.bars.length)
  const single = qs.find((q) => q.kind === 'choice' && q.type !== 'multi_choice' && q.bars.length)
  if (choice?.kind === 'choice') out.push(`How many ticked “${choice.bars[0].label}”?`)
  else if (single?.kind === 'choice') out.push(`How many answered “${single.bars[0].label}” to “${single.label}”?`)
  const num = qs.find((q) => q.kind === 'number')
  if (num) out.push(`What is the average “${num.label}”?`)
  out.push('How many submissions came in each month?')
  const text = qs.find((q) => q.kind === 'text' && q.type === 'long_text')
  if (readAnswers && text) out.push(`Summarise the answers to “${text.label}”`)
  return out.slice(0, 3)
}

export function AskPanel({
  formId,
  role,
  insights,
}: {
  formId: string
  role: FormRole
  insights: Insights | undefined
}) {
  const client = useQueryClient()
  const key = ['ask', formId]
  const state = useQuery({ queryKey: key, queryFn: () => insightsApi.askState(formId), retry: false })
  const [text, setText] = useState('')
  const [live, setLive] = useState<{ question: string; steps: QueryStep[]; charts: ChartSpec[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const sessionId = useRef<string | null>(null)
  useEffect(() => () => abort.current?.abort(), [])

  const data = state.data
  useEffect(() => {
    if (data?.id) sessionId.current = data.id
  }, [data?.id])
  const messages = data?.messages ?? []
  const labels = new Map<string, string>()
  for (const q of insights?.questions ?? []) labels.set(q.key, q.label)
  for (const r of insights?.repeaters ?? []) for (const q of r.questions) labels.set(q.key, q.label)
  const language = insights?.language ?? 'en'

  const refresh = async () => {
    await client.invalidateQueries({ queryKey: key })
  }

  const send = async (question: string) => {
    const q = question.trim()
    if (!q || live || q.length > MAX) return
    setError(null)
    setText('')
    setLive({ question: q, steps: [], charts: [] })
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
        },
        ctrl.signal,
      )
    } catch (err) {
      if (!ctrl.signal.aborted) {
        const code = err instanceof ApiError ? String((err.body as { detail?: string } | null)?.detail ?? '') : ''
        setError(askErrorText(code))
        setText(q)
      }
    } finally {
      abort.current = null
      await refresh()
      setLive(null)
    }
  }

  const stop = () => {
    if (sessionId.current) void insightsApi.cancel(formId, sessionId.current).catch(() => undefined)
  }

  const fresh = async () => {
    abort.current?.abort()
    const opened = await insightsApi.askOpen(formId, true)
    sessionId.current = opened.id
    client.setQueryData<AskState>(key, opened)
  }

  if (state.isError) return null // AI is off for this install (404) or unavailable
  const pairs: { q: AskMessage; a?: AskMessage }[] = []
  for (const m of messages) {
    if (m.role === 'user') pairs.push({ q: m })
    else if (pairs.length) pairs[pairs.length - 1].a = m
  }
  const hidden = showAll ? 0 : Math.max(0, pairs.length - 3)
  const tooLong = text.length > MAX
  const canSend = !live && !tooLong && text.trim().length > 0
  const provider = data?.providerLabel || 'the AI service'
  const ideas = examples(insights, !!data?.readAnswers)

  return (
    <Card className="min-w-0 rounded-md border shadow-none ring-0" aria-labelledby="ask-title">
      <CardHeader>
        <CardTitle id="ask-title" className="text-base">
          Ask your submissions
        </CardTitle>
        <CardDescription>
          {data?.readAnswers
            ? `Answers are counted from this form's submissions. Your question, the form's questions, counts and, when needed, the text of answers go to ${provider}.`
            : `Answers are counted from this form's submissions. Your question, the form's questions and counts go to ${provider}; the text of answers doesn't.`}
        </CardDescription>
        {pairs.length > 0 && (
          <CardAction>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label="New chat" onClick={() => void fresh()} disabled={!!live}>
                  <MessageSquarePlusIcon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>New chat</TooltipContent>
            </Tooltip>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {hidden > 0 && (
          <Button variant="ghost" size="sm" className="self-start text-muted-foreground" onClick={() => setShowAll(true)}>
            Show {hidden} earlier question{hidden === 1 ? '' : 's'}
          </Button>
        )}
        {pairs.slice(hidden).map(({ q, a }) => (
          <div key={q.id} className="flex flex-col gap-3">
            <Question text={q.content.text ?? ''} />
            {a && <Answer msg={a} formId={formId} labels={labels} language={language} />}
          </div>
        ))}
        {live && (
          <div className="flex flex-col gap-3" aria-live="polite">
            <Question text={live.question} />
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
                Counting…
              </li>
            </ul>
          </div>
        )}
        {!pairs.length && !live && ideas.length > 0 && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-muted-foreground">Try asking:</p>
            <div className="flex flex-wrap gap-2">
              {ideas.map((idea) => (
                <Button
                  key={idea}
                  variant="outline"
                  size="sm"
                  className="h-auto max-w-full py-1.5 text-start font-normal whitespace-normal"
                  onClick={() => void send(idea)}
                >
                  <bdi dir="auto">{idea}</bdi>
                </Button>
              ))}
            </div>
          </div>
        )}
        {error && (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-col gap-1">
          <InputGroup>
            <InputGroupTextarea
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
                  stop()
                }
              }}
            />
            <InputGroupAddon align="inline-end">
              {live ? (
                <InputGroupButton variant="outline" size="sm" onClick={stop}>
                  <SquareIcon />
                  Stop
                </InputGroupButton>
              ) : (
                <InputGroupButton
                  variant="default"
                  size="icon-sm"
                  aria-label="Ask (Enter)"
                  aria-disabled={!canSend}
                  className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
                  onClick={() => canSend && void send(text)}
                >
                  <ArrowUpIcon />
                </InputGroupButton>
              )}
            </InputGroupAddon>
          </InputGroup>
          {tooLong && <FieldError>Keep questions under 2,000 characters.</FieldError>}
          {!data?.readAnswers && role === 'owner' && (
            <p className="text-xs text-muted-foreground">
              To let the AI summarise written answers, turn on{' '}
              <Link to="/forms/$formId/settings" params={{ formId }} hash="ai" className="underline underline-offset-4">
                Settings › AI
              </Link>
              .
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
