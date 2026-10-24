/** Import report for a Jotform form (JOTFORM-IMPORT-SCREENS 2.2). */
import { CheckIcon, ChevronDownIcon, PencilIcon, XIcon } from 'lucide-react'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item'
import type { FormImport, ItemStatus, ReportItem } from '@/lib/imports'
import { contentProps } from '@/schema'

import { importOutcome, jotformTypeName } from './type-names'

const STATUS: Record<ItemStatus, { label: string; icon: typeof CheckIcon; variant: 'secondary' | 'outline' | 'destructive' }> = {
  imported: { label: 'Imported', icon: CheckIcon, variant: 'secondary' },
  changed: { label: 'Changed', icon: PencilIcon, variant: 'outline' },
  skipped: { label: 'Not imported', icon: XIcon, variant: 'destructive' },
}

export function StatusBadge({ status, count }: { status: ItemStatus; count?: number }) {
  const s = STATUS[status]
  const Icon = s.icon
  return (
    <Badge variant={s.variant}>
      <Icon data-icon="inline-start" />
      {count === undefined ? s.label : `${count} ${s.label.toLowerCase()}`}
    </Badge>
  )
}

export function FormImportReport({ preview, language }: { preview: FormImport; language: FormImport['language'] }) {
  const { report } = preview
  const total = report.items.length
  const skippedItems = report.items.filter((i) => i.status === 'skipped')
  const changedItems = report.items.filter((i) => i.status !== 'imported')
  // Long forms: open what needs a look, keep the full list one click away.
  const open = [
    ...(changedItems.length ? ['review'] : []),
    ...(total <= 20 ? ['questions'] : []),
    ...(skippedItems.length || report.conditions.some((c) => c.status === 'not_imported') ? ['skipped'] : []),
  ]
  const rows = (items: ReportItem[]) => (
    <ItemGroup className="gap-1">
      {items.map((item) => (
        <Item key={item.qid} size="xs" variant="muted" className="items-start">
          <ItemContent className="min-w-0">
            <ItemTitle className="w-full flex-wrap justify-between">
              <bdi {...contentProps(language)} className="min-w-0 break-words">
                {item.label || <span className="text-muted-foreground">No label</span>}
              </bdi>
              <StatusBadge status={item.status} />
            </ItemTitle>
            <ItemDescription>{importOutcome(item.jotformType, item.justformsType)}</ItemDescription>
            {item.notes.map((n) => (
              <ItemDescription key={n} className="line-clamp-none">
                {n}
              </ItemDescription>
            ))}
          </ItemContent>
        </Item>
      ))}
    </ItemGroup>
  )
  return (
    <Card>
      <CardHeader>
        <CardTitle>Import report</CardTitle>
        <CardDescription>
          {total} Jotform {total === 1 ? 'question' : 'questions'} became {preview.pageCount}{' '}
          {preview.pageCount === 1 ? 'page' : 'pages'} with {preview.fieldCount}{' '}
          {preview.fieldCount === 1 ? 'question' : 'questions'}.
        </CardDescription>
        <div className="flex flex-wrap gap-2 pt-1">
          <StatusBadge status="imported" count={report.counts.imported} />
          <StatusBadge status="changed" count={report.counts.changed} />
          {report.counts.skipped > 0 && <StatusBadge status="skipped" count={report.counts.skipped} />}
        </div>
        {report.logo?.status === 'imported' && (
          <p className="flex items-center gap-1.5 pt-1 text-sm text-muted-foreground">
            <CheckIcon className="size-4" aria-hidden />
            Logo imported.
          </p>
        )}
      </CardHeader>
      <CardContent>
        <Accordion type="multiple" defaultValue={open}>
          {changedItems.length > 0 && (
            <AccordionItem value="review">
              <AccordionTrigger>Changed or not imported ({changedItems.length})</AccordionTrigger>
              <AccordionContent>{rows(changedItems)}</AccordionContent>
            </AccordionItem>
          )}
          <AccordionItem value="questions">
            <AccordionTrigger>All questions ({total})</AccordionTrigger>
            <AccordionContent>{rows(report.items)}</AccordionContent>
          </AccordionItem>
          <AccordionItem value="conditions">
            <AccordionTrigger>Conditions ({report.conditions.length})</AccordionTrigger>
            <AccordionContent className="flex flex-col gap-2">
              {report.conditionsNote && <p className="text-sm text-muted-foreground">{report.conditionsNote}</p>}
              <ItemGroup className="gap-1">
                {report.conditions.map((c, i) => (
                  <Item key={i} size="xs" variant="muted" className="items-start">
                    <ItemContent className="min-w-0">
                      <ItemTitle className="w-full flex-wrap justify-between">
                        <bdi {...contentProps(language)} className="min-w-0 break-words">
                          {c.description}
                        </bdi>
                        <StatusBadge status={c.status === 'imported' ? 'imported' : 'skipped'} />
                      </ItemTitle>
                      {c.reason && <ItemDescription className="line-clamp-none">{c.reason}</ItemDescription>}
                    </ItemContent>
                  </Item>
                ))}
              </ItemGroup>
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value="skipped">
            <AccordionTrigger>Not imported</AccordionTrigger>
            <AccordionContent>
              <ul className="flex list-disc flex-col gap-1 ps-5 text-sm">
                {skippedItems.map((i) => (
                  <li key={i.qid}>
                    <bdi {...contentProps(language)}>
                      {i.label || jotformTypeName(i.jotformType)}
                    </bdi>
                    : {i.notes.join(' ')}
                  </li>
                ))}
                {report.conditions
                  .filter((c) => c.status === 'not_imported')
                  .map((c, i) => (
                    <li key={`c${i}`}>
                      Condition: {c.reason}
                    </li>
                  ))}
                {report.logo?.status === 'not_imported' && <li>Logo: {report.logo.reason ?? "it couldn't be downloaded."}</li>}
                {report.dropped.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
              {report.notes.map((n) => (
                <p key={n} className="mt-2 text-sm text-muted-foreground">
                  {n}
                </p>
              ))}
            </AccordionContent>
          </AccordionItem>
        </Accordion>
        <Collapsible className="mt-4">
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="-ms-2 [&[data-state=open]>svg]:rotate-180">
              Technical details
              <ChevronDownIcon data-icon="inline-end" className="transition-transform motion-reduce:transition-none" />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <p className="pt-2 text-sm text-muted-foreground">Jotform question ids and types, and the JustForms type each became.</p>
            <ul className="flex flex-col gap-1 pt-2 font-mono text-xs" dir="ltr">
              {report.items.map((item) => (
                <li key={item.qid}>
                  {item.qid}: {item.jotformType} → {item.justformsType ?? 'not imported'}
                </li>
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}
