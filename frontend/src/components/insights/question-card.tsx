/**
 * One question on the Insights page (INSIGHTS-SCREENS 3): its summary as a chart or a table,
 * with "Other" answers, numbers, examples, and a way into the matching submissions.
 */
import { Link } from '@tanstack/react-router'
import {
  ChartBarIcon,
  ChevronDownIcon,
  DownloadIcon,
  EllipsisIcon,
  ListIcon,
  LockIcon,
  TableIcon,
} from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Condition } from '@/lib/api'

import type { Bar, ChoiceSummary, DateSummary, NumberSummary, QuestionSummary, TextSummary } from './api'
import { BarList, Columns, type Datum } from './charts'
import { chartPng, download, fileName } from './png'

export type OpenList = (where: Condition[], label: string) => void

const thaana = /[ހ-޿]/
const langOf = (text: string, language: string) => (language === 'dv' || thaana.test(text) ? 'dv' : 'en')

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`
}

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '-'
  return Number.isInteger(n) ? n.toLocaleString('en') : n.toLocaleString('en', { maximumFractionDigits: 2 })
}

interface Row extends Datum {
  where: Condition[]
}

function rowsOf(q: QuestionSummary): Row[] {
  const bar = (b: Bar, i: number, muted = false): Row => ({
    id: `${i}`,
    label: b.label,
    count: b.count,
    percent: b.percent,
    where: b.where,
    muted,
  })
  if (q.kind === 'choice') {
    const out = q.bars.map((b, i) => bar(b, i))
    if (q.other)
      out.push({ id: 'other', label: 'Other', count: q.other.count, percent: q.other.percent, where: q.other.where, muted: true })
    return out
  }
  if (q.kind === 'number') return q.bins.map((b, i) => bar(b, i))
  if (q.kind === 'date') return q.bars.map((b, i) => bar(b, i))
  return []
}

function AnswerTable({
  rows,
  language,
  onPick,
  unit,
}: {
  rows: Row[]
  language: string
  onPick: (r: Row) => void
  unit: string
}) {
  const shares = rows.some((r) => r.percent !== undefined)
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Answer</TableHead>
          <TableHead className="text-end capitalize">{unit}</TableHead>
          {shares && <TableHead className="text-end">Share</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.id}>
            <TableCell className="max-w-0 w-full">
              <Button
                variant="link"
                className="h-auto max-w-full justify-start p-0 text-start whitespace-normal"
                onClick={() => onPick(r)}
                aria-label={`Show the ${plural(r.count, unit.replace(/s$/, ''))} for ${r.label}`}
              >
                <bdi dir="auto" lang={langOf(r.label, language)}>
                  {r.label}
                </bdi>
              </Button>
            </TableCell>
            <TableCell className="text-end tabular-nums">{r.count}</TableCell>
            {shares && <TableCell className="text-end text-muted-foreground tabular-nums">{r.percent ?? '-'}%</TableCell>}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function Stats({ q }: { q: NumberSummary }) {
  const items: [string, number | null][] = [
    ['Lowest', q.stats.min],
    ['Average', q.stats.avg],
    ['Median', q.stats.median],
    ['Highest', q.stats.max],
  ]
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
      {items.map(([k, v]) => (
        <div key={k} className="flex flex-col">
          <dt className="text-xs text-muted-foreground">{k}</dt>
          <dd className="text-lg font-semibold tabular-nums">{fmt(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

function OtherAnswers({ q, language }: { q: ChoiceSummary; language: string }) {
  const texts = q.other?.texts ?? []
  if (!texts.length) return null
  return (
    <Collapsible>
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="group -ms-2.5 text-muted-foreground">
          “Other” answers ({q.other?.count})
          <ChevronDownIcon className="transition-transform group-data-[state=open]:rotate-180" />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="flex flex-col gap-1 pt-1 text-sm">
          {texts.map((t) => (
            <li key={t.text} className="flex items-baseline justify-between gap-3">
              <bdi dir="auto" lang={langOf(t.text, language)} className="min-w-0 break-words">
                {t.text}
              </bdi>
              <span className="shrink-0 text-muted-foreground tabular-nums">{t.count}</span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}

function Examples({ q, language, formId }: { q: TextSummary; language: string; formId: string }) {
  if (!q.examples.length) return null
  return (
    <ul className="flex flex-col divide-y text-sm">
      {q.examples.map((e) => (
        <li key={e.ref}>
          <Link
            to="/forms/$formId/submissions/$ref"
            params={{ formId, ref: String(e.ref) }}
            className="-mx-2 flex min-h-11 items-baseline gap-3 rounded-md px-2 py-2.5 outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <span className="shrink-0 text-muted-foreground tabular-nums">#{e.ref}</span>
            <bdi
              dir="auto"
              lang={langOf(e.text, language)}
              className="line-clamp-3 min-w-0 break-words"
            >
              {e.text}
            </bdi>
          </Link>
        </li>
      ))}
    </ul>
  )
}

export function QuestionCard({
  q,
  of,
  unit,
  language,
  formId,
  multipleVersions,
  onOpen,
}: {
  q: QuestionSummary
  /** Submissions (or rows, inside a repeater) the shares are out of. */
  of: number
  unit: 'submissions' | 'rows'
  language: string
  formId: string
  multipleVersions: boolean
  onOpen: OpenList
}) {
  const [asTable, setAsTable] = useState(false)
  const chartRef = useRef<HTMLDivElement>(null)
  const rows = rowsOf(q)
  const charted = rows.length > 0
  const pick = (r: Row) => onOpen(r.where, `${q.label}: ${r.label}`)
  const answeredWhere: Condition[] = [{ field: q.key, op: 'answered' }]
  const savePng = async () => {
    const box = chartRef.current
    const blob = box ? await chartPng(box, q.label).catch(() => null) : null
    if (blob) download(blob, fileName(q.label))
    else toast.error("Couldn't make the image. Try again.")
  }
  const versions =
    multipleVersions && q.versions.length
      ? q.versions.length === 1
        ? `Version ${q.versions[0]} only`
        : `Versions ${q.versions[0]}–${q.versions[q.versions.length - 1]}`
      : null

  return (
    <Card className="min-w-0 rounded-md border shadow-none ring-0" data-question={q.key}>
      <CardHeader>
        <CardTitle className="text-base leading-snug">
          <bdi dir="auto" lang={langOf(q.label, language)}>
            {q.label}
          </bdi>
        </CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="tabular-nums">
            {q.answered} of {plural(of, unit === 'rows' ? 'row' : 'submission')} answered
          </span>
          {q.sensitive && (
            <Badge variant="outline" className="gap-1">
              <LockIcon /> Sensitive
            </Badge>
          )}
          {versions && <span>{versions}</span>}
        </CardDescription>
        <CardAction>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={`More for ${q.label}`}>
                <EllipsisIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {charted && (
                <DropdownMenuItem onSelect={() => setAsTable((t) => !t)}>
                  {asTable ? <ChartBarIcon /> : <TableIcon />}
                  {asTable ? 'Show as chart' : 'Show as table'}
                </DropdownMenuItem>
              )}
              {charted && !asTable && (
                <DropdownMenuItem onSelect={() => void savePng()}>
                  <DownloadIcon />
                  Download as PNG
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => onOpen(answeredWhere, `${q.label}: answered`)}>
                <ListIcon />
                Show submissions that answered
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {q.kind === 'number' && q.answered > 0 && <Stats q={q} />}
        {charted && q.answered > 0 && (
          <div ref={chartRef}>
            {asTable ? (
              <AnswerTable rows={rows} language={language} onPick={pick} unit={unit} />
            ) : q.kind === 'choice' ? (
              <BarList data={rows} language={language} onPick={(d) => pick(d as Row)} unit={unit} />
            ) : (
              <Columns data={rows} onPick={(d) => pick(d as Row)} unit={unit} />
            )}
          </div>
        )}
        {q.kind === 'choice' && (
          <>
            {q.multi && q.answered > 0 && (
              <p className="text-xs text-muted-foreground">
                People could tick more than one, so the shares add up to more than 100%.
              </p>
            )}
            <OtherAnswers q={q} language={language} />
            {q.truncated && <p className="text-xs text-muted-foreground">Showing the first 100 answers.</p>}
          </>
        )}
        {q.kind === 'date' && q.answered > 0 && (
          <p className="text-xs text-muted-foreground">
            By {(q as DateSummary).bucket}, from {q.min} to {q.max}.
          </p>
        )}
        {(q.kind === 'text' || q.kind === 'sensitive') && (
          <>
            <Examples q={q} language={language} formId={formId} />
          </>
        )}
        {(q.kind === 'file' || q.kind === 'signature') && (
          <p className="text-sm text-muted-foreground">
            {q.kind === 'file' ? 'Files' : 'Signatures'} are counted, not shown here.
          </p>
        )}
        {q.answered === 0 ? (
          <p className="text-sm text-muted-foreground">No answers yet.</p>
        ) : (
          (q.kind === 'text' || q.kind === 'sensitive' || q.kind === 'file' || q.kind === 'signature') && (
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => onOpen(answeredWhere, `${q.label}: answered`)}
            >
              {unit === 'rows' ? 'Show submissions with an answer' : `Show the ${plural(q.answered, 'submission')}`}
            </Button>
          )
        )}
      </CardContent>
    </Card>
  )
}
