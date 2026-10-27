/**
 * Submissions › Deleted (SUBMISSIONS-SORT-AND-TRASH 3): the form's trash, for owners. Each
 * row says who deleted it, when, and when it is erased for good; Restore brings it back with
 * its reference number, one at a time or in bulk. "Delete permanently" erases now.
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArchiveRestoreIcon, TrashIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { EraseDialog } from '@/components/trash/erase-dialog'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, type DeletedSubmission, type FormSummary, type PersonRef } from '@/lib/api'
import { formatDate, formatDateTime } from '@/lib/format'
import { metaQuery } from '@/lib/queries'
import { useDelayed } from '@/lib/use-delayed'
import type { FieldElement, Form } from '@/schema'
import { formLanguage } from '@/schema/language'
import { hasThaana } from '@yashau/thaana-react'

import { answerText } from './format'

const reference = (seq: number) => `#${String(seq).padStart(4, '0')}`
const plural = (n: number) => `${n} ${n === 1 ? 'submission' : 'submissions'}`

/** Same look as the list's "some selected" checkbox (REVIEW P2-13). */
const INDETERMINATE =
  "data-[state=indeterminate]:border-primary data-[state=indeterminate]:bg-primary data-[state=indeterminate]:[&_svg]:hidden data-[state=indeterminate]:before:h-0.5 data-[state=indeterminate]:before:w-2 data-[state=indeterminate]:before:rounded-full data-[state=indeterminate]:before:bg-primary-foreground data-[state=indeterminate]:before:content-['']"

function who(person: PersonRef | null, meId?: string): string {
  if (!person) return 'someone no longer here'
  if (person.id === meId) return 'you'
  return person.name || person.email
}

/** The answer that identifies a row best: the first card field with an answer. */
function summary(row: DeletedSubmission, fields: FieldElement[], schema: Form | undefined): string {
  if (!schema) return ''
  for (const f of fields) {
    const text = answerText(f, row.data[f.id], formLanguage(schema))
    if (text) return text
  }
  return ''
}

function Summary({ text }: { text: string }) {
  if (!text) return <span className="text-muted-foreground">-</span>
  return (
    <bdi dir="auto" lang={hasThaana(text) ? 'dv' : 'en'} className="inline-block max-w-56 truncate align-middle">
      {text}
    </bdi>
  )
}

export function DeletedSubmissions({
  form,
  schema,
  fields,
  meId,
}: {
  form: FormSummary
  schema: Form | undefined
  /** The questions that identify a submission (the card fields). */
  fields: FieldElement[]
  meId?: string
}) {
  const queryClient = useQueryClient()
  const trashDays = useQuery(metaQuery).data?.trashDays ?? 30
  const list = useInfiniteQuery({
    queryKey: ['submissions', form.id, 'deleted'],
    queryFn: ({ pageParam }) => api.deletedSubmissions(form.id, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
  })
  const showSkeleton = useDelayed(list.isPending)
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data])
  const total = list.data?.pages[0]?.total ?? 0
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const chosen = rows.filter((r) => selected.has(r.id))
  const allSelected = rows.length > 0 && chosen.length === rows.length
  const [erasing, setErasing] = useState<string[] | null>(null)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['submissions', form.id] })
    void queryClient.invalidateQueries({ queryKey: ['forms'] })
  }
  const restore = useMutation({
    mutationFn: (ids: string[]) => api.bulk(form.id, { ids, action: 'restore' }),
    onSuccess: (res, ids) => {
      refresh()
      const one = ids.length === 1 ? rows.find((r) => r.id === ids[0]) : undefined
      toast(one ? `Restored ${reference(one.seq)}` : `Restored ${plural(res.changed)}`)
      setSelected((prev) => new Set([...prev].filter((id) => !ids.includes(id))))
    },
    onError: () => toast.error("Couldn't restore. Try again."),
  })
  const erase = useMutation({
    mutationFn: (ids: string[]) => api.bulk(form.id, { ids, action: 'purge' }),
    onSuccess: (res, ids) => {
      refresh()
      toast(`Permanently deleted ${plural(res.changed)}`)
      setSelected((prev) => new Set([...prev].filter((id) => !ids.includes(id))))
      setErasing(null)
    },
    onError: () => toast.error("Couldn't delete them. Try again."),
  })
  const toggle = (id: string, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })

  const retention = form.retentionDays
  const note = (
    <p className="text-sm text-muted-foreground">
      Deleted submissions are kept for {trashDays} days, then erased for good with their files.
      {retention != null && (
        <> This form keeps submissions for {retention} days, so some may go sooner.</>
      )}
    </p>
  )

  if (list.isPending)
    return showSkeleton ? (
      <div className="flex flex-col gap-1">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    ) : null
  if (list.isError)
    return (
      <Alert variant="destructive">
        <AlertDescription className="flex items-center gap-3">
          Couldn't load deleted submissions. Check your connection.
          <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    )
  if (!rows.length)
    return (
      <Empty className="border bg-card">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <TrashIcon />
          </EmptyMedia>
          <EmptyTitle>Nothing deleted</EmptyTitle>
          <EmptyDescription>
            Deleted submissions stay here for {trashDays} days, so you can restore them.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )

  return (
    <div className="flex flex-col gap-3">
      {chosen.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border bg-card px-3 py-2" role="region" aria-label="Selected submissions">
          <span className="text-sm font-medium tabular-nums">{chosen.length} selected</span>
          <Button size="sm" variant="outline" disabled={restore.isPending} onClick={() => restore.mutate(chosen.map((r) => r.id))}>
            <ArchiveRestoreIcon />
            Restore
          </Button>
          <Button size="sm" variant="destructive" onClick={() => setErasing(chosen.map((r) => r.id))}>
            <TrashIcon />
            Delete permanently…
          </Button>
          <Button variant="ghost" size="sm" className="ms-auto" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
        </div>
      ) : (
        note
      )}

      <div className="rounded-md border bg-card max-lg:hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10 ps-4">
                <Checkbox
                  aria-label="Select all shown"
                  className={INDETERMINATE}
                  checked={allSelected ? true : chosen.length ? 'indeterminate' : false}
                  onCheckedChange={(on) => setSelected(on ? new Set(rows.map((r) => r.id)) : new Set())}
                />
              </TableHead>
              <TableHead className="w-20">#</TableHead>
              <TableHead>Answer</TableHead>
              <TableHead>Submitted</TableHead>
              <TableHead>Deleted</TableHead>
              <TableHead>Permanently deleted on</TableHead>
              <TableHead className="w-28">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id} data-state={selected.has(row.id) ? 'selected' : undefined}>
                <TableCell className="ps-4">
                  <Checkbox
                    aria-label={`Select ${reference(row.seq)}`}
                    checked={selected.has(row.id)}
                    onCheckedChange={(on) => toggle(row.id, on === true)}
                  />
                </TableCell>
                <TableCell className="tabular-nums">{row.seq}</TableCell>
                <TableCell>
                  <Summary text={summary(row, fields, schema)} />
                </TableCell>
                <TableCell className="tabular-nums text-muted-foreground">{formatDateTime(row.submittedAt)}</TableCell>
                <TableCell>
                  <span className="tabular-nums">{formatDateTime(row.deletedAt)}</span>
                  <span className="block text-xs text-muted-foreground">by {who(row.deletedBy, meId)}</span>
                </TableCell>
                <TableCell className="tabular-nums">{row.purgeAt ? formatDate(row.purgeAt) : '-'}</TableCell>
                <TableCell className="pe-4 text-end">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={restore.isPending}
                    onClick={() => restore.mutate([row.id])}
                    aria-label={`Restore ${reference(row.seq)}`}
                  >
                    <ArchiveRestoreIcon />
                    Restore
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ItemGroup className="gap-2 lg:hidden" aria-label="Deleted submissions">
        {rows.map((row) => (
          <Item key={row.id} variant="outline" className="items-start bg-card" data-state={selected.has(row.id) ? 'selected' : undefined}>
            <Checkbox
              className="mt-1"
              aria-label={`Select ${reference(row.seq)}`}
              checked={selected.has(row.id)}
              onCheckedChange={(on) => toggle(row.id, on === true)}
            />
            <ItemContent className="min-w-0">
              <ItemTitle className="w-full min-w-0">
                <span className="tabular-nums">{reference(row.seq)}</span>
                <span className="min-w-0 truncate font-normal">
                  <Summary text={summary(row, fields, schema)} />
                </span>
              </ItemTitle>
              <ItemDescription className="line-clamp-none tabular-nums">
                Deleted <span className="whitespace-nowrap">{formatDateTime(row.deletedAt)}</span> by{' '}
                {who(row.deletedBy, meId)}
              </ItemDescription>
              {row.purgeAt && (
                <ItemDescription className="line-clamp-none tabular-nums">
                  Permanently deleted on <span className="whitespace-nowrap">{formatDate(row.purgeAt)}</span>
                </ItemDescription>
              )}
            </ItemContent>
            <ItemActions>
              <Button
                size="sm"
                variant="outline"
                disabled={restore.isPending}
                onClick={() => restore.mutate([row.id])}
                aria-label={`Restore ${reference(row.seq)}`}
              >
                <ArchiveRestoreIcon />
                Restore
              </Button>
            </ItemActions>
          </Item>
        ))}
      </ItemGroup>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span className="tabular-nums">
          Showing {rows.length} of {total}
        </span>
        {list.hasNextPage && (
          <Button variant="outline" size="sm" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
            Load more
          </Button>
        )}
      </div>

      <EraseDialog
        open={erasing !== null}
        onOpenChange={(o) => !o && setErasing(null)}
        title={`Permanently delete ${plural(erasing?.length ?? 0)}?`}
        description="Their answers, files, signatures and signed PDFs are erased now and can't be restored. A record that they existed stays in the audit log."
        action={`Delete ${erasing?.length ?? 0} permanently`}
        pending={erase.isPending}
        onConfirm={() => erasing && erase.mutate(erasing)}
      />
    </div>
  )
}
