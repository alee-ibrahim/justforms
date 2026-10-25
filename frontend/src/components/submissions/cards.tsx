/** Submissions as cards (SUBMISSIONS-VIEWER-SCREENS 2): the answers that identify each one. */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { LayoutListIcon, LockIcon, PaperclipIcon, SignatureIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { api, type FormSummary, type SubmissionSummary } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { FieldElement, Form, FormLanguage } from '@/schema'
import { contentProps, formLanguage } from '@/schema/language'
import { hasThaana } from '@yashau/thaana-react'

import { attachments, MAX_CARD_FIELDS } from './card-fields'
import { answerText } from './format'
import type { SubmissionsSearch } from './search'
import { SubmissionStatusBadge } from './status-badge'

const reference = (seq: number) => `#${String(seq).padStart(4, '0')}`

function CardValue({ field, row, form }: { field: FieldElement; row: SubmissionSummary; form: Form }) {
  const text = answerText(field, row.data[field.id], formLanguage(form))
  if (!text) return <span className="text-muted-foreground">-</span>
  if (field.sensitive)
    return (
      <span className="inline-flex items-center gap-1 tabular-nums" lang="en" dir="ltr">
        <LockIcon className="size-3.5 text-muted-foreground" aria-label="Sensitive" />
        {text}
      </span>
    )
  const latin = ['email', 'phone', 'number', 'date', 'time'].includes(field.type)
  return (
    <bdi
      dir={latin ? 'ltr' : 'auto'}
      // Latin answers in a dv form keep the Latin face (lang only marks Thaana text).
      lang={!latin && hasThaana(text) ? 'dv' : 'en'}
      className={cn(latin && 'tabular-nums')}
    >
      {text}
    </bdi>
  )
}

export function SubmissionCards({
  form,
  rows,
  schema,
  fields,
  shown,
  canSelect,
  selected,
  onToggle,
  search,
  lastId,
}: {
  form: FormSummary
  rows: SubmissionSummary[]
  schema: Form | undefined
  /** Every top-level question (for the file and signature indicators). */
  fields: FieldElement[]
  /** The questions a card shows. */
  shown: FieldElement[]
  canSelect: boolean
  selected: ReadonlySet<string>
  onToggle: (id: string, on: boolean) => void
  search: SubmissionsSearch
  lastId: string | null
}) {
  const language = schema ? formLanguage(schema) : 'en'
  return (
    <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Submissions">
      {rows.map((row) => {
        const { files, signed } = attachments(fields, row.data)
        const step = row.approval?.state === 'pending' && row.approval.step ? row.approval : null
        return (
          <li key={row.id} className="min-w-0">
            <Card
              size="sm"
              data-state={selected.has(row.id) ? 'selected' : undefined}
              className={cn(
                'relative h-full gap-3 py-4 ring-foreground/10 has-[a:focus-visible]:ring-3 has-[a:focus-visible]:ring-ring/50 hover:ring-foreground/25 data-[state=selected]:ring-primary/60',
                row.id === lastId && 'bg-accent',
              )}
            >
              <CardHeader className="gap-1 px-4">
                <div className="flex min-w-0 items-center gap-2">
                  {canSelect && (
                    <Checkbox
                      aria-label={`Select ${reference(row.seq)}`}
                      checked={selected.has(row.id)}
                      onCheckedChange={(on) => onToggle(row.id, on === true)}
                      className="relative z-10 max-md:hidden"
                    />
                  )}
                  <Link
                    to="/forms/$formId/submissions/$ref"
                    params={{ formId: form.id, ref: String(row.seq) }}
                    search={search as never}
                    data-submission={row.id}
                    className="inline-flex items-center font-semibold tabular-nums outline-none pointer-coarse:-my-3 pointer-coarse:min-h-11 after:absolute after:inset-0 after:rounded-[inherit] after:content-['']"
                  >
                    {reference(row.seq)}
                  </Link>
                  <span className="ms-auto">
                    <SubmissionStatusBadge status={row.status} />
                  </span>
                </div>
                <p className="text-sm text-muted-foreground tabular-nums">
                  {formatDateTime(row.submittedAt)}
                  {step && (
                    <>
                      , step {step.step} of {step.total}
                    </>
                  )}
                </p>
              </CardHeader>
              {schema && shown.length > 0 && (
                <CardContent className="px-4">
                  <dl
                    {...contentProps(language)}
                    className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm"
                  >
                    {shown.map((f) => (
                      <div key={f.id} className="contents">
                        <dt className="truncate text-muted-foreground" title={f.label}>
                          {f.label}
                        </dt>
                        <dd className={cn('min-w-0', f.type === 'long_text' ? 'line-clamp-2' : 'truncate')}>
                          <CardValue field={f} row={row} form={schema} />
                        </dd>
                      </div>
                    ))}
                  </dl>
                </CardContent>
              )}
              {(files > 0 || signed || row.respondentEmail) && (
                <CardFooter className="mt-auto flex-wrap gap-x-4 gap-y-1 border-0 bg-transparent px-4 pt-0 pb-4 text-sm text-muted-foreground">
                  {files > 0 && (
                    <span className="inline-flex items-center gap-1.5 tabular-nums">
                      <PaperclipIcon className="size-3.5" aria-hidden />
                      {files === 1 ? '1 file' : `${files} files`}
                    </span>
                  )}
                  {signed && (
                    <span className="inline-flex items-center gap-1.5">
                      <SignatureIcon className="size-3.5" aria-hidden />
                      Signed
                    </span>
                  )}
                  {row.respondentEmail && (
                    <bdi dir="ltr" className="min-w-0 truncate">
                      {row.respondentEmail}
                    </bdi>
                  )}
                </CardFooter>
              )}
            </Card>
          </li>
        )
      })}
    </ul>
  )
}

/** "Card fields": editors choose the questions every card shows, saved on the form. */
export function CardFieldPicker({
  form,
  fields,
  shown,
  language,
}: {
  form: FormSummary
  fields: FieldElement[]
  shown: FieldElement[]
  language: FormLanguage
}) {
  const queryClient = useQueryClient()
  const save = useMutation({
    mutationFn: (cardFields: string[]) => api.patchForm(form.id, { cardFields }),
    onMutate: (cardFields) => {
      const previous = queryClient.getQueryData<FormSummary>(['form', form.id])
      if (previous) queryClient.setQueryData(['form', form.id], { ...previous, cardFields: cardFields.length ? cardFields : null })
      return { previous }
    },
    onSuccess: (next) => queryClient.setQueryData(['form', form.id], next),
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) queryClient.setQueryData(['form', form.id], ctx.previous)
      toast.error("Couldn't save the card fields. Try again.")
    },
  })
  const ids = shown.map((f) => f.id)
  const full = ids.length >= MAX_CARD_FIELDS
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <LayoutListIcon />
          Card fields
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-96 w-64">
        <DropdownMenuLabel>Show on cards</DropdownMenuLabel>
        {fields
          .filter((f) => f.type !== 'hidden')
          .map((f) => {
            const on = ids.includes(f.id)
            return (
              <DropdownMenuCheckboxItem
                key={f.id}
                checked={on}
                disabled={!on && full}
                onSelect={(e) => e.preventDefault()}
                onCheckedChange={(next) => {
                  // Keep form order.
                  const chosen = new Set(next ? [...ids, f.id] : ids.filter((x) => x !== f.id))
                  save.mutate(fields.filter((x) => chosen.has(x.id)).map((x) => x.id))
                }}
              >
                <bdi lang={language} dir="auto" className="truncate">
                  {f.label}
                </bdi>
              </DropdownMenuCheckboxItem>
            )
          })}
        {full && <p className="px-2 py-1.5 text-xs text-muted-foreground">Up to {MAX_CARD_FIELDS} on a card</p>}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => save.mutate([])} disabled={!form.cardFields?.length}>
          Use automatic choice
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
