import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { FileInputIcon, FilePlusIcon, FileTextIcon, SearchIcon, TrashIcon } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { CreateFormDialog } from '@/components/forms/create-form-dialog'
import { FormsList } from '@/components/forms/forms-list'
import {
  applyFormsView,
  isFiltered,
  SORT_LABELS,
  type FormsSearch,
  type FormsSort,
} from '@/components/forms/forms-view'
import { PageContainer } from '@/components/layout/page'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import type { FormListItem, FormStatus } from '@/lib/api'
import { FORM_STATUS_LABELS } from '@/lib/labels'
import { formsQuery, meQuery } from '@/lib/queries'
import { canCreateForms } from '@/lib/roles'
import { useDelayed } from '@/lib/use-delayed'
import { cn } from '@/lib/utils'

function ToolbarSelect({
  id,
  label,
  value,
  onChange,
  children,
  className,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-2', className)}>
      <Label htmlFor={id} className="text-muted-foreground">
        {label}
      </Label>
      <NativeSelect id={id} className="w-full sm:w-auto" value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </NativeSelect>
    </div>
  )
}

function useFormsSearch() {
  const search = useSearch({ strict: false }) as FormsSearch
  const navigate = useNavigate()
  const setSearch = (patch: Partial<FormsSearch>) =>
    void navigate({
      to: '.',
      search: (prev: FormsSearch) => {
        const next: Record<string, unknown> = { ...prev, ...patch }
        for (const k of Object.keys(next)) if (next[k] === undefined || next[k] === '') delete next[k]
        return next
      },
      replace: true,
    } as never)
  return [search, setSearch] as const
}

function FormsView({
  forms,
  orgId,
  meId,
  canCreate,
}: {
  forms: FormListItem[]
  orgId: string
  meId?: string
  canCreate: boolean
}) {
  const [search, setSearch] = useFormsSearch()
  const [query, setQuery] = useState(search.q ?? '')
  // The list follows the typing at once; the URL catches up after a pause.
  const typing = useRef<number | undefined>(undefined)
  const onType = (value: string) => {
    setQuery(value)
    window.clearTimeout(typing.current)
    typing.current = window.setTimeout(() => setSearch({ q: value.trim() || undefined }), 300)
  }
  useEffect(() => () => window.clearTimeout(typing.current), [])
  const view = useMemo(() => ({ ...search, q: query }), [search, query])
  const rows = useMemo(() => applyFormsView(forms, view), [forms, view])
  const sort: FormsSort = search.sort ?? 'edited'
  const clear = () => {
    setQuery('')
    setSearch({ q: undefined, owner: undefined, status: undefined })
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <InputGroup className="lg:max-w-xs">
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput
            type="search"
            placeholder="Search forms"
            aria-label="Search forms"
            value={query}
            onChange={(e) => onType(e.target.value)}
          />
        </InputGroup>
        <div className="grid grid-cols-2 gap-2 min-[400px]:grid-cols-3 sm:flex sm:flex-wrap sm:items-center sm:gap-4">
          <ToolbarSelect
            id="forms-owner"
            label="Owner"
            value={search.owner ?? 'all'}
            onChange={(v) => setSearch({ owner: v === 'mine' ? 'mine' : undefined })}
          >
            <NativeSelectOption value="all">Everyone</NativeSelectOption>
            <NativeSelectOption value="mine">Owned by me</NativeSelectOption>
          </ToolbarSelect>
          <ToolbarSelect
            id="forms-status"
            label="Status"
            value={search.status ?? 'all'}
            onChange={(v) => setSearch({ status: v === 'all' ? undefined : (v as FormStatus) })}
          >
            <NativeSelectOption value="all">All statuses</NativeSelectOption>
            {(Object.keys(FORM_STATUS_LABELS) as FormStatus[]).map((s) => (
              <NativeSelectOption key={s} value={s}>
                {FORM_STATUS_LABELS[s]}
              </NativeSelectOption>
            ))}
          </ToolbarSelect>
          <ToolbarSelect
            id="forms-sort"
            label="Sort by"
            className="max-[399px]:col-span-2"
            value={sort}
            onChange={(v) => setSearch({ sort: v === 'edited' ? undefined : (v as FormsSearch['sort']) })}
          >
            {(Object.keys(SORT_LABELS) as FormsSort[]).map((s) => (
              <NativeSelectOption key={s} value={s}>
                {SORT_LABELS[s]}
              </NativeSelectOption>
            ))}
          </ToolbarSelect>
        </div>
      </div>
      {rows.length > 0 ? (
        <FormsList forms={rows} orgId={orgId} meId={meId} canCreate={canCreate} sort={sort} />
      ) : (
        <div className="flex flex-wrap items-center gap-2 rounded-md border bg-card px-4 py-6 text-sm text-muted-foreground">
          No forms match these filters.
          {isFiltered(view) && (
            <Button variant="link" className="h-auto p-0" onClick={clear}>
              Clear filters
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

function FormsSection({ orgId, meId, canCreate }: { orgId: string; meId?: string; canCreate: boolean }) {
  const forms = useQuery(formsQuery(orgId))
  const showSkeleton = useDelayed(forms.isPending)

  if (forms.isPending)
    return showSkeleton ? (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    ) : null
  if (forms.isError)
    return (
      <Alert variant="destructive">
        <AlertDescription>Couldn't load your forms. Check your connection and reload the page.</AlertDescription>
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

  return <FormsView forms={forms.data} orgId={orgId} meId={meId} canCreate={canCreate} />
}

export function FormsPage() {
  const { data: me } = useQuery(meQuery)
  const org = me?.orgs[0]
  const canCreate = canCreateForms(me, org?.id)

  return (
    <PageContainer>
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold tracking-tight">Forms</h1>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {/* Deleted forms, restorable for the trash period (SUBMISSIONS-SORT-AND-TRASH 4). */}
          <Button variant="ghost" asChild>
            <Link to="/forms/trash" aria-label="Trash">
              <TrashIcon />
              <span className="max-sm:hidden">Trash</span>
            </Link>
          </Button>
          {org && canCreate && (
            <>
            <Button variant="outline" asChild>
              <Link to="/forms/import/jotform">
                <FileInputIcon />
                Import from Jotform
              </Link>
            </Button>
            <CreateFormDialog orgId={org.id} />
            </>
          )}
        </div>
      </div>
      {org ? (
        <FormsSection orgId={org.id} meId={me?.id} canCreate={canCreate} />
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
