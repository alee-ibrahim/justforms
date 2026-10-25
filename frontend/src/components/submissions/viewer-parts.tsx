/** Pieces of the submission view's header and Details tab (SUBMISSIONS-VIEWER-SCREENS 1.2, 1.6). */
import { BadgeCheckIcon, HistoryIcon } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { SubmissionDetail } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import type { Element, FieldElement } from '@/schema'

import { FileCards } from './file-cards'
import { formLanguage } from '@/schema/language'

function walkFields(elements: Element[] | undefined, out: FieldElement[]): FieldElement[] {
  for (const el of elements ?? []) {
    if (el.kind === 'field') out.push(el)
    if (el.kind === 'section' || el.kind === 'repeater') walkFields(el.elements, out)
  }
  return out
}

function allFields(schema: SubmissionDetail['schema']): FieldElement[] {
  return schema.pages.flatMap((p) => walkFields(p.elements, []))
}

/**
 * Rows brought over from a Jotform export (JOTFORM-IMPORT-SCREENS 3.4). Copied files and
 * signatures show with their questions on the sheet; files of questions the form no longer has
 * are listed here, with links to anything not copied yet.
 */
export function ImportedNote({ d }: { d: SubmissionDetail }) {
  if (d.source !== 'jotform_import') return null
  const links = Object.entries(d.importedLinks ?? {})
  const fields = allFields(d.schema)
  const labels = new Map(fields.map((f) => [f.id, f.label || f.id]))
  const onSheet = new Set(fields.filter((f) => f.type === 'file' || f.type === 'signature').map((f) => f.id))
  const elsewhere = (d.importedFiles ?? []).filter((f) => !onSheet.has(f.fieldId))
  const copied = (d.importedFiles ?? []).length
  return (
    <Alert className="min-w-0">
      <HistoryIcon />
      <AlertTitle className="line-clamp-none">Imported from Jotform</AlertTitle>
      <AlertDescription className="min-w-0">
        {d.externalId && (
          <p className="min-w-0 break-all">
            Jotform submission <bdi dir="ltr" className="tabular-nums">{d.externalId}</bdi>
          </p>
        )}
        <p>
          Imported <span className="tabular-nums">{formatDateTime(d.createdAt)}</span>. Signatures from Jotform are not part of
          JustForms' audit trail.
        </p>
        {copied > 0 && <p>Files and signatures copied from Jotform are shown with their questions.</p>}
        {elsewhere.length > 0 && (
          <div className="flex w-full min-w-0 flex-col gap-2">
            <p>Files of questions no longer on the form:</p>
            <FileCards
              files={elsewhere.map((f) => ({
                key: `${f.fieldId}-${f.index}`,
                url: f.url,
                name: `${labels.get(f.fieldId) ?? f.fieldId}: ${f.name}`,
                mime: f.mime,
                size: f.size,
                importedSignature: f.kind === 'signature',
              }))}
            />
          </div>
        )}
        {links.length > 0 && (
          <>
            <p>{copied > 0 ? 'Not copied yet, still on Jotform:' : 'Files and signatures stay on Jotform:'}</p>
            <ul className="flex min-w-0 list-disc flex-col gap-1 ps-5">
              {links.flatMap(([fieldId, urls]) =>
                urls.map((u) => (
                  <li key={u} className="min-w-0 break-all">
                    <bdi dir="auto">{labels.get(fieldId) ?? fieldId}</bdi>:{' '}
                    <a href={u} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-4">
                      <bdi dir="ltr">{u.split('/').pop() || u}</bdi>
                    </a>
                  </li>
                )),
              )}
            </ul>
          </>
        )}
      </AlertDescription>
    </Alert>
  )
}

/** ", by {email}" with how the address was confirmed (PHASE-4-SCREENS 4). */
export function RespondentLine({ d }: { d: SubmissionDetail }) {
  const via = d.events.find((e) => e.type === 'created')?.payload.respondentVia
  return (
    <>
      , by{' '}
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex max-w-full items-center gap-1 text-foreground" tabIndex={0}>
            <BadgeCheckIcon className="size-3.5 shrink-0" aria-hidden />
            <bdi dir="ltr" className="truncate">
              {d.respondentEmail}
            </bdi>
          </span>
        </TooltipTrigger>
        <TooltipContent>{via === 'staff' ? 'Signed in' : 'Email confirmed with a code'}</TooltipContent>
      </Tooltip>
    </>
  )
}

/** Values the link filled into hidden questions; they are not on the sheet. */
export function HiddenValues({ d }: { d: SubmissionDetail }) {
  const hidden = allFields(d.schema).filter((f) => f.type === 'hidden' && d.data[f.id] !== undefined && d.data[f.id] !== '')
  if (!hidden.length) return null
  const language = formLanguage(d.schema)
  return (
    <section aria-labelledby="hidden-values" className="flex flex-col gap-2">
      <h3 id="hidden-values" className="text-sm font-medium">
        Hidden values
      </h3>
      <dl className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
        {hidden.map((f) => (
          <div key={f.id} className="contents">
            <dt className="truncate font-mono text-muted-foreground" title={f.label}>
              {f.id}
            </dt>
            <dd className="min-w-0 break-words">
              <bdi dir="auto" lang={language}>
                {String(d.data[f.id])}
              </bdi>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
