/** Forms list rows (docs/ux/FORMS-LIST-SCREENS.md): a table on ≥ lg, compact cards below. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import {
  BuildingIcon,
  CircleDashedIcon,
  CircleIcon,
  EllipsisIcon,
  FileInputIcon,
  FilePenLineIcon,
  GlobeIcon,
  MailCheckIcon,
} from 'lucide-react'
import { useEffect, useState, type MouseEvent, type ReactNode } from 'react'
import { toast } from 'sonner'

import { FormStatusBadge } from '@/components/forms/form-status-badge'
import { openPath, type FormsSort } from '@/components/forms/forms-view'
import { restoreForm } from '@/components/forms/restore-form'
import { ConfirmDialog } from '@/components/layout/confirm-dialog'
import { useMenuTooltip } from '@/components/layout/use-menu-tooltip'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api, type AccessMode, type FormListItem, type PersonRef } from '@/lib/api'
import { formatDateTime, formatRelative } from '@/lib/format'
import { metaQuery } from '@/lib/queries'
import { cn } from '@/lib/utils'

const FOCUS = 'rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50'

const ACCESS_LABELS: Record<AccessMode, { label: string; long: string; icon: typeof GlobeIcon }> = {
  public: { label: 'Anyone', long: 'Anyone with the link can fill it in', icon: GlobeIcon },
  otp: { label: 'Email code', long: 'People who confirm their email can fill it in', icon: MailCheckIcon },
  staff: { label: 'Staff only', long: 'Only signed-in staff can fill it in', icon: BuildingIcon },
}

function initials(person: PersonRef): string {
  const parts = (person.name.trim() || person.email).split(/[\s@._-]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?'
}

/** "You" for the viewer, else the name (or the address when there is no name). */
function personName(person: PersonRef, meId: string | undefined) {
  if (person.id === meId) return 'You'
  return person.name ? <bdi dir="auto">{person.name}</bdi> : <bdi dir="ltr">{person.email}</bdi>
}

function Time({ iso, now }: { iso: string; now: number }) {
  return (
    <time dateTime={iso} title={formatDateTime(iso)}>
      {formatRelative(iso, now)}
    </time>
  )
}

function Owner({ form, meId, className }: { form: FormListItem; meId?: string; className?: string }) {
  const { owner, ownerCount } = form
  if (!owner) return <span className="text-muted-foreground">-</span>
  const others = ownerCount - 1
  return (
    <span className={cn('flex min-w-0 items-center gap-2', className)}>
      <Avatar size="sm">
        <AvatarFallback>{initials(owner)}</AvatarFallback>
      </Avatar>
      <span className="truncate">{personName(owner, meId)}</span>
      {others > 0 && (
        <span className="shrink-0 text-muted-foreground tabular-nums">
          <span aria-hidden="true">+{others}</span>
          <span className="sr-only">
            and {others} other {others === 1 ? 'owner' : 'owners'}
          </span>
        </span>
      )}
    </span>
  )
}

/** A click anywhere on a row or card opens the form, unless it hit a link, button or menu.
 * Keyboard users get the same destination from the title link. */
function useOpenOnClick(form: FormListItem) {
  const navigate = useNavigate()
  return (e: MouseEvent<HTMLElement>) => {
    const target = e.target as HTMLElement
    if (target.closest('a, button, [role=menuitem], [role=dialog], [role=alertdialog]')) return
    if (!e.currentTarget.contains(target)) return // clicks inside portals (menus, dialogs)
    if (window.getSelection()?.toString()) return // selecting text is not a click
    void navigate({ to: openPath(form), params: { formId: form.id } })
  }
}

function FormLink({ form }: { form: FormListItem }) {
  return (
    <Link
      to={openPath(form)}
      params={{ formId: form.id }}
      className={cn(
        FOCUS,
        'font-medium underline-offset-4 hover:underline pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center',
      )}
    >
      {/* Titles are form content: the form's language, and the browser picks the direction. */}
      {form.title ? (
        <bdi dir="auto" lang={form.language}>
          {form.title}
        </bdi>
      ) : (
        'Untitled form'
      )}
    </Link>
  )
}

/** Small facts under the title: who can fill it in, language, where it came from. */
function FormFacts({ form }: { form: FormListItem }) {
  const access = ACCESS_LABELS[form.accessMode]
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1" title={access.long}>
        <access.icon className="size-3.5" aria-hidden="true" />
        <span className="sr-only">Who can fill it in: </span>
        {access.label}
      </span>
      {form.language === 'dv' && <Badge variant="outline">Dhivehi</Badge>}
      {form.importedFrom === 'jotform' && (
        <span className="inline-flex items-center gap-1">
          <FileInputIcon className="size-3.5" aria-hidden="true" />
          Imported from Jotform
        </span>
      )}
    </div>
  )
}

function UnpublishedNote() {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <FilePenLineIcon className="size-3.5" aria-hidden="true" />
      Unpublished changes
    </span>
  )
}

function NewBadge({ count }: { count: number }) {
  return (
    <Badge>
      <CircleIcon data-icon="inline-start" className="fill-current" />
      {count} new
    </Badge>
  )
}

/** Approval waiting wears the marker, like "In review". */
function AwaitingBadge({ count }: { count: number }) {
  return (
    <Badge variant="outline" className="border-transparent bg-accent text-accent-foreground">
      <CircleDashedIcon data-icon="inline-start" />
      {count} awaiting approval
    </Badge>
  )
}

function Submissions({ form }: { form: FormListItem }) {
  if (form.currentVersion === null && form.submissionCount === 0)
    return <span className="text-muted-foreground">-</span>
  const label = [
    `${form.submissionCount} ${form.submissionCount === 1 ? 'submission' : 'submissions'}`,
    `${form.newCount} new`,
    `${form.recentCount} in the last 7 days`,
    form.approvalsOn && form.pendingApprovalCount > 0 ? `${form.pendingApprovalCount} awaiting approval` : '',
  ]
    .filter(Boolean)
    .join(', ')
  return (
    <Link
      to="/forms/$formId/submissions"
      params={{ formId: form.id }}
      className={cn(FOCUS, 'inline-flex flex-col items-start gap-1 pointer-coarse:min-h-11 pointer-coarse:min-w-11')}
      aria-label={label}
    >
      <span className="inline-flex items-center gap-2">
        <span className="font-medium tabular-nums">{form.submissionCount}</span>
        {form.newCount > 0 && <NewBadge count={form.newCount} />}
      </span>
      {form.recentCount > 0 && (
        <span className="text-xs text-muted-foreground tabular-nums">{form.recentCount} in last 7 days</span>
      )}
      {form.approvalsOn && form.pendingApprovalCount > 0 && <AwaitingBadge count={form.pendingApprovalCount} />}
    </Link>
  )
}

export function RowMenu({ form, orgId, canCreate }: { form: FormListItem; orgId: string; canCreate: boolean }) {
  const menuTip = useMenuTooltip()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const trashDays = useQuery(metaQuery).data?.trashDays ?? 30
  const [confirming, setConfirming] = useState(false)
  // Undo puts it back at once (its address was free a moment ago; if not, the trash asks).
  const undo = async () => {
    try {
      const res = await restoreForm(form.id)
      await queryClient.invalidateQueries({ queryKey: ['forms', orgId] })
      if (res.ok) toast('Restored the form')
      else
        toast.warning('Its address was taken meanwhile', {
          action: { label: 'Open Trash', onClick: () => void navigate({ to: '/forms/trash' }) },
        })
    } catch {
      toast.error("Couldn't restore the form. Find it in Trash.")
    }
  }
  const remove = useMutation({
    mutationFn: () => api.deleteForm(form.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['forms', orgId] })
      toast('Moved the form to Trash', {
        description: `Restorable for ${trashDays} days, with its submissions.`,
        action: { label: 'Undo', onClick: () => void undo() },
        duration: 10_000,
      })
    },
    onError: () => toast.error("Couldn't delete the form. Try again."),
  })
  const duplicate = useMutation({
    mutationFn: () => api.duplicateForm(form.id),
    onSuccess: async (copy) => {
      await queryClient.invalidateQueries({ queryKey: ['forms', orgId] })
      toast.success('Duplicated the form')
      await navigate({ to: '/forms/$formId/edit', params: { formId: copy.id } })
    },
    onError: () => toast.error("Couldn't duplicate the form. Try again."),
  })
  const canEdit = form.role !== 'viewer'
  return (
    <>
      <DropdownMenu>
        <Tooltip {...menuTip.tooltip}>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Form actions">
                <EllipsisIcon />
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>Form actions</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="end" {...menuTip.content}>
          {canEdit && (
            <DropdownMenuItem asChild>
              <Link to="/forms/$formId/edit" params={{ formId: form.id }}>
                Edit
              </Link>
            </DropdownMenuItem>
          )}
          {canEdit && canCreate && <DropdownMenuItem onSelect={() => duplicate.mutate()}>Duplicate</DropdownMenuItem>}
          <DropdownMenuItem asChild>
            <Link to="/forms/$formId/submissions" params={{ formId: form.id }}>
              Submissions
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <Link to="/forms/$formId/share" params={{ formId: form.id }}>
              Share
            </Link>
          </DropdownMenuItem>
          {form.role === 'owner' && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" disabled={remove.isPending} onSelect={() => setConfirming(true)}>
                Delete…
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {/* Even though Trash can bring it back, a form takes its link and submissions with it. */}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={
          <>
            Delete <bdi dir="auto">{form.title || 'Untitled form'}</bdi>?
          </>
        }
        description={`It moves to Trash for ${trashDays} days${
          form.submissionCount > 0
            ? `, with its ${form.submissionCount} ${form.submissionCount === 1 ? 'submission' : 'submissions'}`
            : ''
        }. You can restore it from Trash.`}
        action="Delete form"
        onConfirm={() => remove.mutate()}
      />
    </>
  )
}

interface ListProps {
  forms: FormListItem[]
  orgId: string
  meId?: string
  canCreate: boolean
  sort: FormsSort
  /** For tests: the time relative dates count from. */
  now?: number
}

const SORTED_COLUMN: Partial<Record<FormsSort, string>> = {
  name: 'form',
  submissions: 'submissions',
  submission: 'last-submission',
  edited: 'last-edited',
}

function FormRow({ form, children }: { form: FormListItem; children: ReactNode }) {
  const open = useOpenOnClick(form)
  return (
    <TableRow className="cursor-pointer" data-form={form.id} onClick={open}>
      {children}
    </TableRow>
  )
}

function FormCard({ form, children }: { form: FormListItem; children: ReactNode }) {
  const open = useOpenOnClick(form)
  return (
    <Item variant="outline" className="cursor-pointer items-start bg-card" data-form={form.id} onClick={open}>
      {children}
    </Item>
  )
}

function FormsTable({ forms, orgId, meId, canCreate, sort, now }: ListProps & { now: number }) {
  const ariaSort = (column: string) =>
    SORTED_COLUMN[sort] === column ? (sort === 'name' ? 'ascending' : 'descending') : undefined
  return (
    <div className="rounded-md border bg-card max-lg:hidden" data-testid="forms-table">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="ps-4" aria-sort={ariaSort('form')}>
              Form
            </TableHead>
            <TableHead>Owner</TableHead>
            <TableHead>Status</TableHead>
            <TableHead aria-sort={ariaSort('submissions')}>Submissions</TableHead>
            <TableHead className="max-xl:hidden" aria-sort={ariaSort('last-submission')}>
              Last submission
            </TableHead>
            <TableHead aria-sort={ariaSort('last-edited')}>
              Last edited
            </TableHead>
            <TableHead className="w-12">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {forms.map((form) => (
            <FormRow key={form.id} form={form}>
              <TableCell className="max-w-80 min-w-56 ps-4 whitespace-normal">
                <FormLink form={form} />
                <FormFacts form={form} />
              </TableCell>
              <TableCell className="max-w-48">
                <Owner form={form} meId={meId} />
              </TableCell>
              <TableCell>
                <div className="flex flex-col items-start gap-1">
                  <FormStatusBadge status={form.status} />
                  {form.hasUnpublishedChanges && <UnpublishedNote />}
                </div>
              </TableCell>
              <TableCell>
                <Submissions form={form} />
              </TableCell>
              <TableCell className="text-muted-foreground max-xl:hidden">
                {form.lastSubmissionAt ? <Time iso={form.lastSubmissionAt} now={now} /> : '-'}
              </TableCell>
              <TableCell className="max-w-44">
                <div className="flex flex-col">
                  <Time iso={form.lastEditedAt} now={now} />
                  {form.lastEditedBy && (
                    <span className="truncate text-xs text-muted-foreground">
                      by {form.lastEditedBy.id === meId ? 'you' : personName(form.lastEditedBy, meId)}
                    </span>
                  )}
                </div>
              </TableCell>
              <TableCell className="text-end">
                <RowMenu form={form} orgId={orgId} canCreate={canCreate} />
              </TableCell>
            </FormRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

/** Phones and tablets: title, status with counts, owner with the last submission. */
function FormCards({ forms, orgId, meId, canCreate, now }: ListProps & { now: number }) {
  return (
    <ItemGroup className="gap-2 lg:hidden" data-testid="forms-cards">
      {forms.map((form) => (
        <FormCard key={form.id} form={form}>
          <ItemContent className="min-w-0 gap-2">
            <ItemTitle className="w-full min-w-0 text-base">
              <FormLink form={form} />
            </ItemTitle>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <FormStatusBadge status={form.status} />
              {form.newCount > 0 && <NewBadge count={form.newCount} />}
              {form.approvalsOn && form.pendingApprovalCount > 0 && <AwaitingBadge count={form.pendingApprovalCount} />}
              {form.currentVersion !== null && (
                <Link
                  to="/forms/$formId/submissions"
                  params={{ formId: form.id }}
                  className={cn(FOCUS, 'text-muted-foreground tabular-nums underline-offset-4 hover:underline pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center')}
                >
                  {form.submissionCount} {form.submissionCount === 1 ? 'submission' : 'submissions'}
                </Link>
              )}
            </div>
            <ItemDescription className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
              <Owner form={form} meId={meId} className="max-w-full" />
              {form.lastSubmissionAt && (
                <span>
                  Last submission <Time iso={form.lastSubmissionAt} now={now} />
                </span>
              )}
            </ItemDescription>
          </ItemContent>
          <ItemActions>
            <RowMenu form={form} orgId={orgId} canCreate={canCreate} />
          </ItemActions>
        </FormCard>
      ))}
    </ItemGroup>
  )
}

/** The current time, refreshed every minute so "5 minutes ago" stays true. */
function useNow(fixed?: number): number {
  const [now, setNow] = useState(() => fixed ?? Date.now())
  useEffect(() => {
    if (fixed !== undefined) return
    const timer = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => window.clearInterval(timer)
  }, [fixed])
  return now
}

export function FormsList(props: ListProps) {
  const now = useNow(props.now)
  return (
    <>
      <FormsTable {...props} now={now} />
      <FormCards {...props} now={now} />
    </>
  )
}
