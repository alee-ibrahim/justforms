/**
 * Insights › Where people get stuck: anonymous counts from the public form for the last 30 days
 * (docs/ux/ID-NUMBER-AND-FRICTION-SCREENS.md 2). How far visits got (opened, started, each
 * page, submitted) and which questions showed problems, with the kind of problem. Counts only:
 * no answers, nothing about who.
 */
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { buildIndex } from '@/logic/form-index'
import type { Form } from '@/schema'

import { insightsApi } from './api'
import { funnel, kinds } from './friction-lib'

const pct = (n: number, of: number) => (of > 0 ? Math.round((n / of) * 100) : 0)

export function FrictionCard({ formId, schema, language }: { formId: string; schema?: Form; language: string }) {
  const query = useQuery({ queryKey: ['friction', formId], queryFn: () => insightsApi.friction(formId) })
  const index = useMemo(() => (schema ? buildIndex(schema) : null), [schema])
  const data = query.data
  const labelOf = (key: string) => {
    const el = index?.elements.get(key)?.element
    return (el && 'label' in el && el.label?.trim()) || key
  }
  const pageName = (key: string) => {
    const i = schema?.pages.findIndex((p) => p.id === key) ?? -1
    if (i < 0) return key
    return schema!.pages[i].title?.trim() || `Page ${i + 1}`
  }
  const steps = data ? funnel(data, schema) : []
  const opened = steps[0]?.count ?? 0
  const empty = data && opened === 0 && data.started === 0 && data.submitted === 0 && data.fields.length === 0

  return (
    <Card className="rounded-md border shadow-none ring-0" aria-labelledby="friction-title">
      <CardHeader>
        <CardTitle id="friction-title">Where people get stuck</CardTitle>
        <CardDescription>
          Last 30 days, all versions. Anonymous counts from the form: no answers and nothing about who.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {query.isPending ? (
          <Skeleton className="h-40" />
        ) : query.isError || !data ? (
          <p className="text-sm text-muted-foreground">Couldn't load these counts. Reload the page to try again.</p>
        ) : !data.enabled && empty ? (
          <p className="text-sm text-muted-foreground">
            Turned off for this form.{' '}
            <Link to="/forms/$formId/settings" params={{ formId }} hash="access" className="underline underline-offset-4">
              Turn it on in Settings › Access
            </Link>
            .
          </p>
        ) : empty ? (
          <p className="text-sm text-muted-foreground">
            Nothing recorded yet. Counts appear here as people open and fill in the form.
          </p>
        ) : (
          <>
            {!data.enabled && (
              <p className="text-sm text-muted-foreground">Turned off for this form: these are earlier counts.</p>
            )}
            <section aria-labelledby="funnel-title" className="flex flex-col gap-3">
              <h3 id="funnel-title" className="text-sm font-medium">
                How far people got
              </h3>
              <ol className="flex flex-col gap-3">
                {steps.map((s) => (
                  <li key={s.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
                    <span className="truncate text-sm">
                      {s.key.startsWith('page-') ? (
                        <>
                          Reached{' '}
                          <bdi dir="auto" lang={language}>
                            {s.label}
                          </bdi>
                        </>
                      ) : (
                        s.label
                      )}
                    </span>
                    <span className="text-sm tabular-nums text-muted-foreground">
                      {s.count}
                      {s.key !== 'opened' && opened > 0 && ` · ${pct(s.count, opened)}%`}
                    </span>
                    <Progress
                      value={pct(s.count, opened)}
                      className="col-span-2 h-2"
                      aria-label={`${s.label}: ${s.count} of ${opened} visits`}
                    />
                  </li>
                ))}
              </ol>
            </section>

            <section aria-labelledby="stuck-title" className="flex flex-col gap-3">
              <h3 id="stuck-title" className="text-sm font-medium">
                Questions with the most problems
              </h3>
              {data.fields.length === 0 ? (
                <p className="text-sm text-muted-foreground">No problems shown to anyone.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Question</TableHead>
                      <TableHead className="hidden sm:table-cell">Page</TableHead>
                      <TableHead className="text-end">Visits</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.fields.slice(0, 10).map((f) => (
                      <TableRow key={f.field}>
                        <TableCell className="whitespace-normal">
                          <div className="flex flex-col gap-1.5">
                            <bdi dir="auto" lang={language} className="font-medium">
                              {labelOf(f.field)}
                            </bdi>
                            <div className="flex flex-wrap gap-1">
                              {kinds(f.codes).map((k) => (
                                <Badge key={k.kind} variant="secondary" className="font-normal">
                                  {k.kind} <span className="tabular-nums">{k.count}</span>
                                </Badge>
                              ))}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="hidden align-top whitespace-normal text-muted-foreground sm:table-cell">
                          <bdi dir="auto" lang={language}>
                            {pageName(f.page)}
                          </bdi>
                        </TableCell>
                        <TableCell className="text-end align-top tabular-nums">{f.total}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </section>

            {data.codes.length > 0 && (
              <section aria-labelledby="kinds-title" className="flex flex-col gap-3">
                <h3 id="kinds-title" className="text-sm font-medium">
                  Kinds of problems
                </h3>
                <ul className="flex flex-wrap gap-2">
                  {kinds(Object.fromEntries(data.codes.map((c) => [c.code, c.count]))).map((k) => (
                    <li key={k.kind}>
                      <Badge variant="outline" className="h-7 gap-1.5 text-sm font-normal">
                        {k.kind} <span className="tabular-nums text-muted-foreground">{k.count}</span>
                      </Badge>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
