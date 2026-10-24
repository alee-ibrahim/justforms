import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { CircleIcon, EllipsisIcon, FileInputIcon, FilePlusIcon, FileTextIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { FormStatusBadge } from '@/components/forms/form-status-badge'
import { CreateFormDialog } from '@/components/forms/create-form-dialog'
import { PageContainer } from '@/components/layout/page'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useMenuTooltip } from '@/components/layout/use-menu-tooltip'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api, type FormSummary } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { formsQuery, meQuery } from '@/lib/queries'
import { canCreateForms } from '@/lib/roles'
import { useDelayed } from '@/lib/use-delayed'

function RowMenu({ form, orgId, canCreate }: { form: FormSummary; orgId: string; canCreate: boolean }) {
  const menuTip = useMenuTooltip()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [confirm, setConfirm] = useState(false)
  const remove = useMutation({
    mutationFn: () => api.deleteForm(form.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['forms', orgId] })
      toast.success('Deleted the form')
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
                Open
              </Link>
            </DropdownMenuItem>
          )}
          {canEdit && canCreate && (
            <DropdownMenuItem onSelect={() => duplicate.mutate()}>Duplicate</DropdownMenuItem>
          )}
          <DropdownMenuItem asChild>
            <Link to="/forms/$formId/share" params={{ formId: form.id }}>
              Share
            </Link>
          </DropdownMenuItem>
          {form.role === 'owner' && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={() => setConfirm(true)}>
                Delete
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this form?</AlertDialogTitle>
            <AlertDialogDescription>
              <bdi dir="auto">{form.title || 'Untitled form'}</bdi> and its link stop working
              for everyone. Submissions are kept for the retention period.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => remove.mutate()}>
              Delete form
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function FormsTable({ orgId, canCreate }: { orgId: string; canCreate: boolean }) {
  const forms = useQuery(formsQuery(orgId))
  const showSkeleton = useDelayed(forms.isPending)

  if (forms.isPending)
    return showSkeleton ? (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    ) : null
  if (forms.isError)
    return (
      <Alert variant="destructive">
        <AlertDescription>
          Couldn't load your forms. Check your connection and reload the page.
        </AlertDescription>
      </Alert>
    )
  if (forms.data.length === 0 && !canCreate)
    return (
      <Empty className="border bg-card">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon />
          </EmptyMedia>
          <EmptyTitle>No forms shared with you yet</EmptyTitle>
          <EmptyDescription>When someone shares a form with you, it shows up here.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  if (forms.data.length === 0)
    return (
      <Empty className="border bg-card">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FilePlusIcon />
          </EmptyMedia>
          <EmptyTitle>Create your first form</EmptyTitle>
          <EmptyDescription>
            Start from a blank form. You can add pages, questions and logic in the builder.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <CreateFormDialog orgId={orgId} />
          <p className="text-sm text-muted-foreground">
            Moving from Jotform?{' '}
            <Button variant="link" className="h-auto p-0" asChild>
              <Link to="/forms/import/jotform">Import a form</Link>
            </Button>
            .
          </p>
        </EmptyContent>
      </Empty>
    )

  return (
    <div className="rounded-md border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="ps-4">Title</TableHead>
            <TableHead className="max-sm:hidden">Status</TableHead>
            <TableHead>Submissions</TableHead>
            <TableHead className="max-md:hidden">Updated</TableHead>
            <TableHead className="w-12">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {forms.data.map((form) => (
            <TableRow key={form.id} className="h-10">
              <TableCell className="ps-4 font-medium whitespace-normal">
                {/* Titles are form content (any language): let the browser pick the direction. */}
                <Link
                  to={form.role === 'viewer' ? '/forms/$formId/submissions' : '/forms/$formId/edit'}
                  params={{ formId: form.id }}
                  className="rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:min-w-11 pointer-coarse:items-center"
                >
                  {form.title ? <bdi dir="auto">{form.title}</bdi> : 'Untitled form'}
                </Link>
                {/* Phones drop the Status column; the badge sits under the title instead. */}
                <div className="mt-1 sm:hidden">
                  <FormStatusBadge status={form.status} />
                </div>
              </TableCell>
              <TableCell className="max-sm:hidden">
                <FormStatusBadge status={form.status} />
              </TableCell>
              <TableCell className="tabular-nums">
                {form.currentVersion === null ? (
                  <span className="text-muted-foreground">-</span>
                ) : (
                  <Link
                    to="/forms/$formId/submissions"
                    params={{ formId: form.id }}
                    className="inline-flex items-center gap-2 rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-11 pointer-coarse:min-w-11"
                    aria-label={`${form.submissionCount} submissions, ${form.newCount} new`}
                  >
                    {form.newCount > 0 && (
                      <Badge>
                        <CircleIcon data-icon="inline-start" className="fill-current" />
                        {form.newCount} new
                      </Badge>
                    )}
                    <span className="text-muted-foreground">{form.submissionCount}</span>
                  </Link>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground tabular-nums max-md:hidden">
                {formatDateTime(form.updatedAt)}
              </TableCell>
              <TableCell className="text-end">
                <RowMenu form={form} orgId={orgId} canCreate={canCreate} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export function FormsPage() {
  const { data: me } = useQuery(meQuery)
  const org = me?.orgs[0]
  const canCreate = canCreateForms(me, org?.id)

  return (
    <PageContainer>
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold tracking-tight">Forms</h1>
        {org && canCreate && (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="outline" asChild>
              <Link to="/forms/import/jotform">
                <FileInputIcon />
                Import from Jotform
              </Link>
            </Button>
            <CreateFormDialog orgId={org.id} />
          </div>
        )}
      </div>
      {org ? (
        <FormsTable orgId={org.id} canCreate={canCreate} />
      ) : (
        <Alert>
          <AlertDescription>
            You aren't a member of any organisation yet. Ask an administrator to add you.
          </AlertDescription>
        </Alert>
      )}
    </PageContainer>
  )
}
