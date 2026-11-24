/**
 * A submission laid out as the filled form (docs/ux/SUBMISSIONS-VIEWER-SCREENS.md 1): the
 * submission's own schema version, pages stacked, sections and half-width pairs as
 * on the public form, read-only answers on ruled lines.
 */
import { CheckIcon, LockIcon, StarIcon, XIcon } from 'lucide-react'
import { createContext, Fragment, useContext, useMemo, type ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import type { ImportedFile, SignatureInfo } from '@/lib/api'
import { cn } from '@/lib/utils'
import { QuestionGrid } from '@/renderer/elements'
import { Markdown } from '@/renderer/markdown'
import { En } from '@/renderer/msg'
import { placement } from '@/renderer/util'
import { rowTitle, widthClass } from '@/renderer/util'
import type { FileRef } from '@/renderer/validation'
import type { Element, FieldElement, Form } from '@/schema'
import { explicitAlign, isMultiline, textDirection, textLang, type TextAlign } from '@/schema/direction'
import { alignClass, textProps } from '@/schema/align'
import { FormLines, FormText } from '@/thaana/form-text'

import { hasAnswers, isEmptyAnswer, useLogic } from './answer-logic'
import { FileCards, type FileCardEntry } from './file-cards'
import { answerText, chosenOptions, formatAnswerDate, formatPhone } from './format'
import { SignatureBlock } from './signature-block'

type Data = Record<string, unknown>
type Scope = { repeater: string; row: number }

interface AnswerContextValue {
  /** The form's default alignment (`settings.align`). */
  formAlign: TextAlign | null | undefined
  signatures: SignatureInfo[]
  /** Copies of files and signatures imported from Jotform, by question. */
  imported: ReadonlyMap<string, FileCardEntry[]>
  /** Show questions the form's logic hid from this respondent. */
  showSkipped: boolean
  isVisible: (id: string, scope?: Scope) => boolean
}

const AnswerContext = createContext<AnswerContextValue>({
  formAlign: undefined,
  signatures: [],
  imported: new Map(),
  showSkipped: false,
  isVisible: () => true,
})

function NoAnswer({ skipped }: { skipped?: boolean }) {
  return (
    <span className="text-muted-foreground">
      <En>{skipped ? 'Skipped (not shown to the respondent)' : 'No answer'}</En>
    </span>
  )
}

/** A sensitive answer: shown like any other, marked with a lock (opening a submission with
 * sensitive answers is recorded in its activity). */
export function Sensitive({ text }: { text: string }) {
  return (
    <span className="inline-flex items-start gap-2">
      <LockIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <bdi dir="auto" lang={textLang(text)} className="whitespace-pre-wrap">
        {isMultiline(text) ? <FormLines text={text} /> : text}
      </bdi>
      <span className="sr-only">(sensitive)</span>
    </span>
  )
}

const NO_FILES: ImportedFile[] = []

function importedByField(files: ImportedFile[]): Map<string, FileCardEntry[]> {
  const out = new Map<string, FileCardEntry[]>()
  for (const f of files) {
    const entry: FileCardEntry = {
      key: `${f.fieldId}-${f.index}`,
      url: f.url,
      name: f.name,
      mime: f.mime,
      size: f.size,
      importedSignature: f.kind === 'signature',
    }
    out.set(f.fieldId, [...(out.get(f.fieldId) ?? []), entry])
  }
  return out
}

/** A chosen option, yes/no or "Other" answer. */
function Chip({ icon, children }: { icon?: 'check' | 'x'; children: ReactNode }) {
  const Icon = icon === 'x' ? XIcon : CheckIcon
  return (
    <Badge variant="secondary" className="h-auto min-h-6 max-w-full justify-start py-0.5 text-start whitespace-normal">
      <Icon data-icon="inline-start" aria-hidden />
      <span className="min-w-0 break-words">{children}</span>
    </Badge>
  )
}

/**
 * A heading or label of form text: its own direction and language, its alignment (the element's,
 * else the form default) and a lighter weight for Thaana, which reads heavy when bold.
 */
function Heading({
  as: Tag,
  text,
  align,
  className,
  latin,
  thaana,
  id,
}: {
  as: 'h2' | 'h3' | 'dt'
  text: string
  align: TextAlign | null | undefined
  className: string
  /** Weight classes for Latin and Thaana text. */
  latin: string
  thaana: string
  id?: string
}) {
  const { formAlign } = useContext(AnswerContext)
  return (
    <Tag
      id={id}
      {...textProps(text)}
      className={cn(className, textLang(text) === 'dv' ? thaana : latin, alignClass(align, formAlign, textDirection(text)))}
    >
      {/* Auto alignment: a bilingual text is one row, English left and Dhivehi right. */}
      <FormText text={text} split={explicitAlign(align, formAlign) === null} />
    </Tag>
  )
}

/** On a ruled answer line, like ink on a paper form. */
function Line({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('min-h-8 border-b border-border pb-1.5 text-base break-words', className)}>{children}</div>
}

const LATIN = new Set(['email', 'phone', 'number', 'date', 'time'])

/** One answer, by question type (SUBMISSIONS-VIEWER-SCREENS 1.3). */
export function AnswerValue({ field, value, row }: { field: FieldElement; value: unknown; row?: number }) {
  const { signatures, imported, formAlign } = useContext(AnswerContext)
  const copies = row === undefined ? imported.get(field.id) : undefined
  if (isEmptyAnswer(value) && copies?.length) return <FileCards files={copies} />
  if (isEmptyAnswer(value))
    return (
      <Line>
        <NoAnswer />
      </Line>
    )
  if (field.sensitive)
    return (
      <Line>
        <Sensitive text={answerText(field, value)} />
      </Line>
    )
  switch (field.type) {
    case 'file':
      return Array.isArray(value) ? (
        <FileCards
          files={(value as FileRef[]).map((f) => ({ key: f.fileId, url: `/api/v1/files/${f.fileId}`, name: f.name, mime: f.mime, size: f.size }))}
        />
      ) : null
    case 'signature': {
      const sig = signatures.find((s) => s.fieldId === field.id)
      return sig ? (
        <div className="break-inside-avoid">
          <SignatureBlock sig={sig} />
        </div>
      ) : (
        <Line>
          <En>Signed</En>
        </Line>
      )
    }
    case 'single_choice':
    case 'multi_choice': {
      const { chosen, other } = chosenOptions(field, value)
      return (
        // Inline chips, so they follow the question's alignment (text-align) and direction.
        <div className="pt-0.5 [&>[data-slot=badge]]:me-1.5 [&>[data-slot=badge]]:mb-1.5">
          {chosen.map((o) => (
            <Chip key={o.value}>
              <bdi {...textProps(o.label)}>
                <FormText text={o.label} split={explicitAlign(field.align, formAlign) === null && 'inline'} />
              </bdi>
            </Chip>
          ))}
          {other.map((text, i) => (
            <Chip key={`other-${i}`}>
              <En>Other:</En> <bdi dir="auto">{text}</bdi>
            </Chip>
          ))}
        </div>
      )
    }
    case 'yes_no':
      return (
        <div className="pt-0.5">
          <Chip icon={value === true ? 'check' : 'x'}>
            <En>{value === true ? 'Yes' : 'No'}</En>
          </Chip>
        </div>
      )
    case 'rating': {
      const max = field.max ?? 5
      const n = Number(value)
      const label = `${n} out of ${max}`
      return (
        <Line>
          <span className="inline-flex items-center gap-2" lang="en" dir="ltr">
            <span className="inline-flex gap-0.5" role="img" aria-label={label}>
              {Array.from({ length: max }, (_, i) => (
                <StarIcon key={i} aria-hidden className={cn('size-4', i < n ? 'fill-current' : 'text-muted-foreground')} />
              ))}
            </span>
            <span className="tabular-nums" aria-hidden>
              {label}
            </span>
          </span>
        </Line>
      )
    }
    case 'email':
      return (
        <Line>
          <a href={`mailto:${String(value)}`} className="-my-3 inline-block max-w-full py-3 break-all text-primary underline-offset-4 hover:underline">
            <bdi dir="ltr">{String(value)}</bdi>
          </a>
        </Line>
      )
    case 'phone':
      return (
        <Line>
          <a href={`tel:${String(value)}`} className="-my-3 inline-block py-3 text-primary tabular-nums underline-offset-4 hover:underline">
            <bdi dir="ltr">{formatPhone(String(value))}</bdi>
          </a>
        </Line>
      )
    case 'date':
      return (
        <Line className="tabular-nums">
          <bdi dir="ltr">{formatAnswerDate(String(value))}</bdi>
        </Line>
      )
    default: {
      const text = answerText(field, value)
      if (LATIN.has(field.type))
        return (
          <Line className="tabular-nums">
            <bdi dir="ltr">{text}</bdi>
          </Line>
        )
      // Several paragraphs (a long answer): each line in its own direction, aligned to its
      // own start edge unless the question has an explicit alignment.
      if (isMultiline(text))
        return (
          <Line className="whitespace-pre-wrap">
            <FormLines
              text={text}
              align={explicitAlign(field.align, formAlign) ?? 'auto'}
              measure={field.type === 'long_text'}
            />
          </Line>
        )
      return (
        <Line className={cn('whitespace-pre-wrap', field.type === 'long_text' && 'max-w-[36em]')}>
          <bdi {...textProps(text)}>
            <FormText text={text} />
          </bdi>
        </Line>
      )
    }
  }
}

/** One question: the printed label and the written answer (a one-item description list). */
function Question({ field, data, scope }: { field: FieldElement; data: Data; scope?: Scope }) {
  const { showSkipped, isVisible, formAlign } = useContext(AnswerContext)
  const skipped = !isVisible(field.id, scope)
  // Like the live form, the question is one block in its label's direction and alignment; the
  // answer keeps its own direction inside it.
  const place = placement(field.label, field.align, formAlign)
  return (
    <dl
      className="flex h-full flex-col gap-1.5"
      data-question={field.id}
      dir={place.dir}
      lang={place.lang}
      style={place.text}
    >
      {field.label.trim() ? (
        <Heading as="dt" text={field.label} align={field.align} className="text-sm text-muted-foreground" latin="font-medium" thaana="font-normal" />
      ) : (
        <dt className="text-sm font-medium text-muted-foreground">
          <En>Untitled question</En>
        </dt>
      )}
      <dd className={cn('min-w-0', field.width === 'half' && 'mt-auto')}>
        {skipped && showSkipped && isEmptyAnswer(data[field.id]) ? (
          <Line>
            <NoAnswer skipped />
          </Line>
        ) : (
          <AnswerValue field={field} value={data[field.id]} row={scope?.row} />
        )}
      </dd>
    </dl>
  )
}

/** The elements of a page, section or repeater row on the form's own grid. */
function ReadElements({ elements, data, scope }: { elements: Element[]; data: Data; scope?: Scope }) {
  const { showSkipped, isVisible, imported } = useContext(AnswerContext)
  const shown = elements.filter((el) => {
    if (el.kind === 'field' && el.type === 'hidden') return false
    if (el.kind === 'content') return el.contentType !== 'image' && isVisible(el.id, scope)
    // A hidden question that holds an answer (imports) still shows.
    const answered = el.kind !== 'section' && (!isEmptyAnswer(data[el.id]) || (!scope && imported.has(el.id)))
    return showSkipped || isVisible(el.id, scope) || answered
  })
  if (!shown.length) return null
  return (
    <QuestionGrid className="gap-y-6">
      {shown.map((el) => (
        <div key={el.id} className={cn('min-w-0', widthClass(el))}>
          <ReadElement el={el} data={data} scope={scope} />
        </div>
      ))}
    </QuestionGrid>
  )
}

function ReadElement({ el, data, scope }: { el: Element; data: Data; scope?: Scope }) {
  const { formAlign } = useContext(AnswerContext)
  switch (el.kind) {
    case 'field':
      return <Question field={el} data={data} scope={scope} />
    case 'content':
      if (el.contentType === 'divider') return <Separator className="my-2" />
      if (!el.text) return null
      return el.contentType === 'heading' ? (
        <Heading as="h3" text={el.text} align={el.align} className="text-xl tracking-tight" latin="font-semibold" thaana="font-normal" />
      ) : (
        <div {...textProps(el.text)}>
          <Markdown
            text={el.text}
            className="text-base text-muted-foreground"
            align={explicitAlign(el.align, formAlign) ?? 'auto'}
            measure
            rtl={textDirection(el.text) === 'rtl'}
          />
        </div>
      )
    case 'section':
      return (
        <section className="flex flex-col gap-4">
          {el.title && <Heading as="h3" text={el.title} align={el.align} className="text-lg" latin="font-semibold" thaana="font-normal" />}
          <div className="@min-[32rem]:border-s @min-[32rem]:ps-4">
            <ReadElements elements={el.elements ?? []} data={data} scope={scope} />
          </div>
        </section>
      )
    case 'repeater': {
      const rows = Array.isArray(data[el.id]) ? (data[el.id] as Data[]) : []
      return (
        <section className="flex flex-col gap-3" data-question={el.id}>
          <Heading as="h3" text={el.label} align={el.align} className="text-sm text-muted-foreground" latin="font-medium" thaana="font-normal" />
          {rows.length ? (
            rows.map((row, i) => (
              <div key={i} className="flex break-inside-avoid flex-col gap-4 rounded-md border p-4">
                <h4 className="text-sm font-medium">{rowTitle(el, i + 1) ?? <En>Entry {i + 1}</En>}</h4>
                <ReadElements elements={el.elements ?? []} data={row ?? {}} scope={{ repeater: el.id, row: i }} />
              </div>
            ))
          ) : (
            <Line>
              <En>No entries</En>
            </Line>
          )}
        </section>
      )
    }
  }
}

export function Answers({
  form,
  data,
  signatures = [],
  showSkipped = false,
  importedFiles = NO_FILES,
}: {
  form: Form
  data: Data
  signatures?: SignatureInfo[]
  importedFiles?: ImportedFile[]
  showSkipped?: boolean
}) {
  const logic = useLogic(form, data)
  const imported = useMemo(() => importedByField(importedFiles), [importedFiles])
  // A page the respondent never reached is left out, unless it holds answers (imports).
  const pages = form.pages
    .map((page, i) => ({ page, i }))
    .filter(({ page }) => !logic.skippedPages.has(page.id) || hasAnswers(page.elements ?? [], data))
  return (
    <AnswerContext value={{ formAlign: form.settings.align, signatures, imported, showSkipped, isVisible: logic.isVisible }}>
      <div className="flex flex-col gap-[var(--df-space,2rem)]">
        {pages.map(({ page, i }, n) => (
          <Fragment key={page.id}>
            {n > 0 && <Separator />}
            <section
              className="flex flex-col gap-6"
              aria-labelledby={page.title || pages.length > 1 ? `page-${page.id}` : undefined}
            >
              {page.title ? (
                <Heading
                  as="h2"
                  id={`page-${page.id}`}
                  text={page.title}
                  align={page.align}
                  className="df-page-title text-xl"
                  latin="font-[650] tracking-tight"
                  thaana="font-bold"
                />
              ) : (
                pages.length > 1 && (
                  <h2 id={`page-${page.id}`} className="df-page-title text-xl font-[650] tracking-tight">
                    <En>Page {i + 1}</En>
                  </h2>
                )
              )}
              <ReadElements elements={page.elements ?? []} data={data} />
            </section>
          </Fragment>
        ))}
      </div>
    </AnswerContext>
  )
}
