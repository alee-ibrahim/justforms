/**
 * A submission's answers, rendered with the submission's own schema version and language
 * (PHASE-2-SCREENS 5.3): labels and values in a two-column list, repeaters as tables.
 */
import { DownloadIcon, FileIcon, FileTextIcon, LockIcon } from 'lucide-react'
import { createContext, useContext, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { evaluate } from '@/logic/engine'
import type { Element, FieldElement, Form } from '@/schema'
import { contentProps, formLanguage } from '@/schema/language'
import { formatSize } from '@/renderer/util'
import type { FileRef } from '@/renderer/validation'
import { displayText } from '@/thaana/display'

import type { SignatureInfo } from '@/lib/api'

import { answerText } from './format'
import { SignatureBlock } from './signature-block'

interface AnswerContextValue {
  signatures: SignatureInfo[]
  /** Set when the viewer may unmask sensitive answers (editors and owners). */
  reveal?: (fieldId: string, row?: number) => Promise<string>
  /** Questions the form's logic hid from this respondent. */
  skipped?: ReadonlySet<string>
}

const AnswerContext = createContext<AnswerContextValue>({ signatures: [] })

const isEmpty = (value: unknown) =>
  value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length)

/** An empty answer: "No answer", or why there is none when logic hid the question (REVIEW P3-9). */
function NoAnswer({ id }: { id: string }) {
  const { skipped } = useContext(AnswerContext)
  return (
    <span className="text-muted-foreground" lang="en" dir="ltr">
      {skipped?.has(id) ? 'Skipped (not shown to the respondent)' : 'No answer'}
    </span>
  )
}

/** What the form's logic hid for these answers: questions, and pages the respondent never saw. */
function useSkipped(form: Form, data: Record<string, unknown>) {
  return useMemo(() => {
    try {
      const ev = evaluate(form, data)
      return { elements: new Set(ev.hidden), pages: new Set(form.pages.map((p) => p.id).filter((id) => !ev.path.includes(id))) }
    } catch {
      // A rule loop in an old version: show every question as before.
      return { elements: new Set<string>(), pages: new Set<string>() }
    }
  }, [form, data])
}

/** True when any field on the page (or nested in it) has an answer. */
function hasAnswers(elements: Element[], data: Record<string, unknown>): boolean {
  return elements.some((el) =>
    el.kind === 'section' ? hasAnswers(el.elements ?? [], data) : el.kind !== 'content' && !isEmpty(data[el.id]),
  )
}

/** A masked sensitive answer; "Show" asks the server for it (and is logged). */
function Sensitive({ masked, fieldId, row }: { masked: string; fieldId: string; row?: number }) {
  const { reveal } = useContext(AnswerContext)
  const [shown, setShown] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (shown !== null) return <bdi dir="auto">{shown}</bdi>
  return (
    <span className="inline-flex items-center gap-2" lang="en" dir="ltr">
      <LockIcon className="size-3.5 text-muted-foreground" aria-hidden />
      <span className="tabular-nums">{masked}</span>
      {reveal ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0"
              disabled={busy}
              onClick={() => {
                setBusy(true)
                reveal(fieldId, row)
                  .then(setShown)
                  .catch(() => toast.error("Couldn't show the answer. Try again."))
                  .finally(() => setBusy(false))
              }}
            >
              Show
            </Button>
          </TooltipTrigger>
          <TooltipContent>Viewing is recorded</TooltipContent>
        </Tooltip>
      ) : (
        <span className="text-xs text-muted-foreground">Sensitive</span>
      )}
    </span>
  )
}

const PREVIEW = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])

/** Uploaded files: thumbnail or type icon, name, size and a download link (DESIGN 10). */
function Files({ files }: { files: FileRef[] }) {
  return (
    <ItemGroup className="gap-2" lang="en" dir="ltr">
      {files.map((f) => {
        const url = `/api/v1/files/${f.fileId}`
        return (
          <Item key={f.fileId} variant="outline" size="sm" className="flex-nowrap">
            <ItemMedia variant={PREVIEW.has(f.mime) ? 'image' : 'icon'}>
              {PREVIEW.has(f.mime) ? (
                <img src={`${url}?preview=1`} alt="" loading="lazy" />
              ) : f.mime === 'application/pdf' ? (
                <FileTextIcon />
              ) : (
                <FileIcon />
              )}
            </ItemMedia>
            <ItemContent className="min-w-0">
              <ItemTitle className="max-w-full">
                <bdi dir="auto" className="truncate">
                  {f.name}
                </bdi>
              </ItemTitle>
              <ItemDescription className="tabular-nums">{formatSize(f.size)}</ItemDescription>
            </ItemContent>
            <ItemActions>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon-sm" asChild>
                    <a href={url} download={f.name} aria-label={`Download ${f.name}`}>
                      <DownloadIcon />
                    </a>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Download</TooltipContent>
              </Tooltip>
            </ItemActions>
          </Item>
        )
      })}
    </ItemGroup>
  )
}

function Value({ field, value, form, row }: { field: FieldElement; value: unknown; form: Form; row?: number }) {
  const { signatures } = useContext(AnswerContext)
  const language = formLanguage(form)
  if (isEmpty(value)) return <NoAnswer id={field.id} />
  if (field.type === 'file' && Array.isArray(value)) return <Files files={value as FileRef[]} />
  if (field.type === 'signature') {
    const sig = signatures.find((s) => s.fieldId === field.id)
    if (sig) return <SignatureBlock sig={sig} language={language} />
  }
  const text = answerText(field, value, language)
  if (field.sensitive) return <Sensitive masked={text} fieldId={field.id} row={row} />
  const latin = ['email', 'phone', 'number', 'date', 'time', 'yes_no'].includes(field.type)
  return latin ? <bdi dir="ltr">{text}</bdi> : <span className="whitespace-pre-wrap">{displayText(text, language)}</span>
}

function Rows({ elements, data, form }: { elements: Element[]; data: Record<string, unknown>; form: Form }) {
  return (
    <>
      {elements.map((el) => {
        if (el.kind === 'content') return null
        if (el.kind === 'section')
          return <Rows key={el.id} elements={el.elements ?? []} data={data} form={form} />
        if (el.kind === 'repeater') {
          const rows = Array.isArray(data[el.id]) ? (data[el.id] as Record<string, unknown>[]) : []
          const cols = (el.elements ?? []).filter((c): c is FieldElement => c.kind === 'field')
          return (
            <div key={el.id} className="contents">
              <dt className="text-muted-foreground">{el.label}</dt>
              <dd className="min-w-0">
                {rows.length ? (
                  <div className="overflow-x-auto rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-8">#</TableHead>
                          {cols.map((c) => (
                            <TableHead key={c.id}>{c.label}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {rows.map((row, i) => (
                          <TableRow key={i}>
                            <TableCell className="tabular-nums">{i + 1}</TableCell>
                            {cols.map((c) => (
                              <TableCell key={c.id}>
                                <Value field={c} value={row[c.id]} form={form} row={i} />
                              </TableCell>
                            ))}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <NoAnswer id={el.id} />
                )}
              </dd>
            </div>
          )
        }
        if (el.type === 'hidden' && data[el.id] === undefined) return null
        return (
          <div key={el.id} className="contents">
            <dt className="text-muted-foreground">{el.label}</dt>
            <dd className="min-w-0 break-words">
              <Value field={el} value={data[el.id]} form={form} />
            </dd>
          </div>
        )
      })}
    </>
  )
}

export function Answers({
  form,
  data,
  signatures = [],
  reveal,
}: {
  form: Form
  data: Record<string, unknown>
  signatures?: SignatureInfo[]
  reveal?: AnswerContextValue['reveal']
}) {
  const content = contentProps(formLanguage(form))
  const skipped = useSkipped(form, data)
  return (
    <AnswerContext value={{ signatures, reveal, skipped: skipped.elements }}>
      <div {...content} className="flex flex-col gap-6">
        {form.pages.map((page, i) =>
          // A page the respondent never reached is left out, unless it holds answers (imports).
          skipped.pages.has(page.id) && !hasAnswers(page.elements ?? [], data) ? null : (
          <section key={page.id} className="flex flex-col gap-3">
            <h3 className="text-sm font-medium text-muted-foreground">{page.title || <span lang="en" dir="ltr">Page {i + 1}</span>}</h3>
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-[minmax(0,14rem)_1fr]">
              <Rows elements={page.elements ?? []} data={data} form={form} />
            </dl>
          </section>
          ),
        )}
      </div>
    </AnswerContext>
  )
}
