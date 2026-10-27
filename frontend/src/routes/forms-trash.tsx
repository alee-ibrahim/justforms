/**
 * Forms › Trash (SUBMISSIONS-SORT-AND-TRASH 4): deleted forms the person may restore (their
 * own; every form of the organisation for admins). Restoring brings back the form, its link
 * and its submissions; "Delete permanently" erases them now.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { ArchiveRestoreIcon, ChevronLeftIcon, EllipsisIcon, TrashIcon } from 'lucide-react'
import { useId, useState } from 'react'
import { toast } from 'sonner'

import { restoreForm } from '@/components/forms/restore-form'
import { hostPrefix, normalizeSlug, useSlugCheck } from '@/components/forms/slug'
import { PageContainer } from '@/components/layout/page'
import { EraseDialog } from '@/components/trash/erase-dialog'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@/components/ui/input-group'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { PersonRef, TrashedForm } from '@/lib/api'
import { api } from '@/lib/api'
import { formatDate, formatDateTime } from '@/lib/format'
import { meQuery, metaQuery } from '@/lib/queries'
import { useDelayed } from '@/lib/use-delayed'

function who(person: PersonRef | null, meId?: string): string {
  if (!person) return 'someone no longer here'
  if (person.id === meId) return 'you'
  return person.name || person.email
}

const count = (n: number) => `${n} ${n === 1 ? 'submission' : 'submissions'}`

function Title({ form }: { form: TrashedForm }) {
  return (
    <bdi dir="auto" lang={form.language}>
      {form.title || 'Untitled form'}
    </bdi>
  )
}

/** Another form took the address: restore at a new one (the suggestion, or typed). */
function NewAddressDialog({
  form,
  suggestion,
  onClose,
  onRestored,
}: {
  form: TrashedForm | null
  suggestion: string
  onClose: () => void
  onRestored: (form: TrashedForm) => void
}) {
  const id = useId()
  const [slug, setSlug] = useState(suggestion)
  const [error, setError] = useState<string | null>(null)
  const { result, checking } = useSlugCheck(slug, form?.id, form !== null)
  const problem =
    result && !result.available
      ? result.problem === 'taken'
        ? 'Another form uses this address'
        : result.problem === 'reserved'
          ? 'This word is reserved. Choose another'
          : 'Use lowercase letters, numbers and hyphens'
      : null
  const run = useMutation({
    mutationFn: () => restoreForm(form!.id, slug),
    onSuccess: (res) => {
      if (res.ok) onRestored(form!)
      else setError('Another form took this address. Choose another')
    },
    onError: () => setError("Couldn't restore the form. Try again."),
  })
  return (
    <Dialog open={form !== null} onOpenChange={(o) => !o && !run.isPending && onClose()}>
      <DialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (!problem && slug) run.mutate()
          }}
        >
          <DialogHeader>
            <DialogTitle>Restore at a new address</DialogTitle>
            <DialogDescription>
              Another form now uses <bdi dir="ltr">/{form?.slug}</bdi>. Choose a new address for{' '}
              {form && <Title form={form} />}. Links to the old address will open the other form.
            </DialogDescription>
          </DialogHeader>
          <Field data-invalid={problem || error ? true : undefined}>
            <FieldLabel htmlFor={id}>Form address</FieldLabel>
            <InputGroup>
              <InputGroupAddon>
                <InputGroupText>{hostPrefix()}</InputGroupText>
              </InputGroupAddon>
              <InputGroupInput
                id={id}
                dir="ltr"
                value={slug}
                autoComplete="off"
                spellCheck={false}
                aria-invalid={problem || error ? true : undefined}
                onChange={(e) => {
                  setError(null)
                  setSlug(normalizeSlug(e.target.value))
                }}
              />
              {checking && (
                <InputGroupAddon align="inline-end">
                  <Spinner />
                </InputGroupAddon>
              )}
            </InputGroup>
            {problem || error ? (
              <FieldError>{problem ?? error}</FieldError>
            ) : (
              <FieldDescription>Lowercase letters, numbers and hyphens.</FieldDescription>
            )}
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={run.isPending} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={run.isPending || !!problem || !slug || checking}>
              {run.isPending && <Spinner />}
              Restore
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RowActions({
  form,
  onRestore,
  onErase,
  pending,
}: {
  form: TrashedForm
  onRestore: () => void
  onErase: () => void
  pending: boolean
}) {
  return (
    <div className="flex items-center justify-end gap-1">
      <Button size="sm" variant="outline" disabled={pending} onClick={onRestore}>
        {pending ? <Spinner /> : <ArchiveRestoreIcon />}
        Restore
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={`More actions for ${form.title || 'Untitled form'}`}>
            <EllipsisIcon />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem variant="destructive" onSelect={onErase}>
            <TrashIcon />
            Delete permanently…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export function FormsTrashPage() {
  const me = useQuery(meQuery).data
  const org = me?.orgs[0]
  const trashDays = useQuery(metaQuery).data?.trashDays ?? 30
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const trash = useQuery({
    queryKey: ['forms', org?.id, 'trash'],
    queryFn: () => api.formsTrash(org!.id),
    enabled: !!org,
  })
  const showSkeleton = useDelayed(trash.isPending)
  const [renaming, setRenaming] = useState<{ form: TrashedForm; suggestion: string } | null>(null)
  const [erasing, setErasing] = useState<TrashedForm | null>(null)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['forms'] })
    void queryClient.invalidateQueries({ queryKey: ['form'] })
  }
  const restored = (form: TrashedForm) => {
    setRenaming(null)
    refresh()
    toast(<span>Restored <Title form={form} /></span>, {
      action: {
        label: 'Open',
        onClick: () => void navigate({ to: '/forms/$formId/submissions', params: { formId: form.id } }),
      },
    })
  }
  const restore = useMutation({
    mutationFn: (form: TrashedForm) => restoreForm(form.id),
    onSuccess: (res, form) => {
      if (res.ok) restored(form)
      else setRenaming({ form, suggestion: res.suggestion || form.slugSuggestion || '' })
    },
    onError: () => toast.error("Couldn't restore the form. Try again."),
  })
  const erase = useMutation({
    mutationFn: (form: TrashedForm) => api.eraseForm(form.id),
    onSuccess: (_r, form) => {
      setErasing(null)
      refresh()
      toast(<span>Permanently deleted <Title form={form} /></span>)
    },
    onError: () => toast.error("Couldn't delete the form. Try again."),
  })
  const rows = trash.data ?? []

  return (
    <PageContainer>
      <div className="flex flex-col gap-1">
        <Button asChild variant="link" size="sm" className="-ms-2.5 h-auto self-start px-2.5 text-muted-foreground">
          <Link to="/forms">
            <ChevronLeftIcon />
            Forms
          </Link>
        </Button>
        <h1 className="text-xl font-semibold tracking-tight">Trash</h1>
        <p className="text-sm text-muted-foreground">
          Deleted forms stay here for {trashDays} days with their submissions, then they are erased for good.
        </p>
      </div>
      {trash.isPending ? (
        showSkeleton && (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        )
      ) : trash.isError ? (
        <Alert variant="destructive">
          <AlertDescription>Couldn't load the trash. Check your connection and reload the page.</AlertDescription>
        </Alert>
      ) : rows.length === 0 ? (
        <Empty className="border bg-card">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <TrashIcon />
            </EmptyMedia>
            <EmptyTitle>The trash is empty</EmptyTitle>
            <EmptyDescription>Forms you delete stay here for {trashDays} days, so you can restore them.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button asChild variant="outline">
              <Link to="/forms">Back to forms</Link>
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <>
          <div className="rounded-md border bg-card max-lg:hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="ps-4">Form</TableHead>
                  <TableHead>Deleted</TableHead>
                  <TableHead>Submissions</TableHead>
                  <TableHead>Permanently deleted on</TableHead>
                  <TableHead className="w-40">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell className="max-w-80 ps-4">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="truncate font-medium">
                          <Title form={f} />
                        </span>
                      </div>
                      <span className="block truncate text-xs text-muted-foreground">
                        <bdi dir="ltr">/{f.slug}</bdi>
                        {f.slugTaken && ' (now used by another form)'}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="tabular-nums">{formatDateTime(f.deletedAt)}</span>
                      <span className="block text-xs text-muted-foreground">by {who(f.deletedBy, me?.id)}</span>
                    </TableCell>
                    <TableCell className="tabular-nums">{f.submissionCount}</TableCell>
                    <TableCell className="tabular-nums">{formatDate(f.purgeAt)}</TableCell>
                    <TableCell className="pe-4">
                      <RowActions
                        form={f}
                        pending={restore.isPending && restore.variables?.id === f.id}
                        onRestore={() => restore.mutate(f)}
                        onErase={() => setErasing(f)}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ItemGroup className="gap-2 lg:hidden" aria-label="Deleted forms">
            {rows.map((f) => (
              <Item key={f.id} variant="outline" className="items-start bg-card">
                <ItemContent className="min-w-0">
                  <ItemTitle className="w-full min-w-0">
                    <span className="truncate">
                      <Title form={f} />
                    </span>
                  </ItemTitle>
                  <ItemDescription className="line-clamp-none tabular-nums">
                    Deleted <span className="whitespace-nowrap">{formatDateTime(f.deletedAt)}</span> by{' '}
                    {who(f.deletedBy, me?.id)}
                  </ItemDescription>
                  <ItemDescription className="line-clamp-none tabular-nums">{count(f.submissionCount)}</ItemDescription>
                  <ItemDescription className="line-clamp-none tabular-nums">
                    Permanently deleted on <span className="whitespace-nowrap">{formatDate(f.purgeAt)}</span>
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <RowActions
                    form={f}
                    pending={restore.isPending && restore.variables?.id === f.id}
                    onRestore={() => restore.mutate(f)}
                    onErase={() => setErasing(f)}
                  />
                </ItemActions>
              </Item>
            ))}
          </ItemGroup>
        </>
      )}
      <NewAddressDialog
        key={renaming?.form.id ?? 'none'}
        form={renaming?.form ?? null}
        suggestion={renaming?.suggestion ?? ''}
        onClose={() => setRenaming(null)}
        onRestored={restored}
      />
      <EraseDialog
        open={erasing !== null}
        onOpenChange={(o) => !o && setErasing(null)}
        title="Permanently delete this form?"
        description={
          erasing && (
            <>
              <Title form={erasing} />, its versions, settings and {count(erasing.submissionCount)} (with their files,
              signatures and signed PDFs) are erased now and can't be restored.
            </>
          )
        }
        action="Delete permanently"
        pending={erase.isPending}
        onConfirm={() => erasing && erase.mutate(erasing)}
      />
    </PageContainer>
  )
}
