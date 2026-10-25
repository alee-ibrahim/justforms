/** Second header row inside a form (PHASE-2-SCREENS 2.3): title, save state, undo, nav, publish. */
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import {
  ChevronDownIcon,
  ChevronLeftIcon,
  CircleCheckIcon,
  CloudOffIcon,
  EllipsisIcon,
  SparklesIcon,
  SplitIcon,
  Redo2Icon,
  TriangleAlertIcon,
  Undo2Icon,
} from 'lucide-react'
import { useThaanaKeyboard } from '@yashau/thaana-react'
import { useRef, useState } from 'react'

import { useAi, useAiController } from '@/components/ai/controller'
import { Badge } from '@/components/ui/badge'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Kbd, KbdGroup } from '@/components/ui/kbd'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useMenuTooltip } from '@/components/layout/use-menu-tooltip'
import type { FormSummary } from '@/lib/api'
import { MOD_KEY } from '@/lib/shortcuts'
import { contentProps, formLanguage } from '@/schema/language'

import { LogicOverview } from './logic-overview'
import { type BuilderStore, useBuilder, useStore } from './store'

const NAV = [
  { to: '/forms/$formId/edit', label: 'Edit' },
  { to: '/forms/$formId/preview', label: 'Preview' },
  { to: '/forms/$formId/share', label: 'Share' },
  { to: '/forms/$formId/submissions', label: 'Submissions' },
  { to: '/forms/$formId/settings', label: 'Settings' },
] as const

function SaveStatus() {
  const store = useStore()
  const status = useBuilder((s) => s.status)
  const error = useBuilder((s) => s.error)
  const content =
    status === 'saved' ? (
      <>
        <CircleCheckIcon data-icon="inline-start" />
        Saved
      </>
    ) : status === 'saving' ? (
      <>
        <Spinner data-icon="inline-start" />
        Saving…
      </>
    ) : status === 'offline' ? (
      <>
        <CloudOffIcon data-icon="inline-start" />
        Offline. Changes will save when you reconnect
      </>
    ) : (
      <>
        <TriangleAlertIcon data-icon="inline-start" />
        Couldn't save
      </>
    )
  return (
    <div className="flex min-w-0 items-center gap-1" aria-live="polite">
      <Badge
        variant={status === 'error' ? 'destructive' : 'outline'}
        className="max-w-full truncate font-normal"
        title={error ?? undefined}
      >
        {content}
      </Badge>
      {status === 'error' && (
        <Button variant="link" size="sm" className="text-destructive" onClick={() => void store.flush()}>
          Retry
        </Button>
      )}
    </div>
  )
}

/** Opens the AI assistant panel (PHASE-5-SCREENS 1); absent when AI is off. */
function AiButton({ formId }: { formId: string }) {
  const ai = useAiController()
  const open = useAi(ai, (s) => s.open)
  const navigate = useNavigate()
  const editing = useRouterState({ select: (s) => s.location.pathname.endsWith('/edit') })
  if (!ai) return null
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-pressed={open && editing}
          aria-label="AI assistant"
          className={open && editing ? 'bg-secondary' : undefined}
          onClick={() => {
            if (!editing) {
              void navigate({ to: '/forms/$formId/edit', params: { formId } })
              ai.setOpen(true)
            } else ai.setOpen(!open)
          }}
        >
          <SparklesIcon />
          <span className="max-sm:hidden">AI assistant</span>
        </Button>
      </TooltipTrigger>
      <TooltipContent className="sm:hidden">AI assistant</TooltipContent>
    </Tooltip>
  )
}

function UndoRedo({ store }: { store: BuilderStore }) {
  const canUndo = useBuilder(() => store.canUndo)
  const canRedo = useBuilder(() => store.canRedo)
  const locked = useBuilder((s) => s.locked)
  if (locked)
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0} className="rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            <ButtonGroup aria-label="History">
              <Button variant="outline" size="icon-sm" aria-label="Undo" disabled>
                <Undo2Icon />
              </Button>
              <Button variant="outline" size="icon-sm" aria-label="Redo" disabled>
                <Redo2Icon />
              </Button>
            </ButtonGroup>
          </span>
        </TooltipTrigger>
        <TooltipContent>Apply or discard the suggestion first</TooltipContent>
      </Tooltip>
    )
  return (
    <ButtonGroup aria-label="History">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="outline" size="icon-sm" aria-label={`Undo (${MOD_KEY}+Z)`} disabled={!canUndo} onClick={() => void store.undo()}>
            <Undo2Icon />
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          Undo{' '}
          <KbdGroup>
            <Kbd>{MOD_KEY}</Kbd>
            <Kbd>Z</Kbd>
          </KbdGroup>
        </TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="outline" size="icon-sm" aria-label={`Redo (${MOD_KEY}+Shift+Z)`} disabled={!canRedo} onClick={() => void store.redo()}>
            <Redo2Icon />
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          Redo{' '}
          <KbdGroup>
            <Kbd>{MOD_KEY}</Kbd>
            <Kbd>Shift</Kbd>
            <Kbd>Z</Kbd>
          </KbdGroup>
        </TooltipContent>
      </Tooltip>
    </ButtonGroup>
  )
}

/** Click-to-rename title in the breadcrumb (Enter saves, Esc cancels). */
function TitleCrumb({ store }: { store: BuilderStore }) {
  const schema = useBuilder((s) => s.schema)
  const [editing, setEditing] = useState<string | null>(null)
  const keyboard = useThaanaKeyboard<HTMLInputElement>({ enabled: formLanguage(schema) === 'dv' })
  const title = schema.settings.title
  if (editing !== null)
    return (
      <Input
        ref={keyboard}
        autoFocus
        aria-label="Form title"
        {...contentProps(formLanguage(schema))}
        value={editing}
        className="h-7 w-64"
        onChange={(e) => setEditing(e.target.value)}
        onBlur={() => setEditing(null)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setEditing(null)
          if (e.key === 'Enter') {
            const next = editing.trim()
            if (next) store.edit((f) => ({ ...f, settings: { ...f.settings, title: next } }))
            setEditing(null)
          }
        }}
      />
    )
  return (
    <BreadcrumbPage>
      <button
        type="button"
        className="max-w-64 truncate rounded-sm text-start outline-none pointer-coarse:min-h-11 hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
        onClick={() => setEditing(title)}
        title="Rename"
      >
        {title ? (
          <bdi dir="auto" lang={formLanguage(schema)}>
            {title}
          </bdi>
        ) : (
          'Untitled form'
        )}
      </button>
    </BreadcrumbPage>
  )
}

function FormMenu({ formId }: { formId: string }) {
  const menuTip = useMenuTooltip()
  const [logic, setLogic] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  return (
    <>
      <DropdownMenu>
        <Tooltip {...menuTip.tooltip}>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button ref={trigger} variant="ghost" size="icon-sm" aria-label="More form actions">
                <EllipsisIcon />
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>More form actions</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="end" {...menuTip.content}>
          <DropdownMenuItem onSelect={() => setLogic(true)}>
            <SplitIcon />
            View all logic
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <LogicOverview open={logic} onOpenChange={setLogic} formId={formId} returnFocus={trigger} />
    </>
  )
}

export function FormBar({
  form,
  store,
  unpublished,
  onPublish,
}: {
  form: FormSummary
  store: BuilderStore | null
  unpublished: boolean
  onPublish?: () => void
}) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const active = NAV.find((n) => pathname.endsWith(n.to.split('/').pop()!)) ?? NAV[0]
  const nav = store ? NAV : NAV.filter((n) => n.label !== 'Edit' && n.label !== 'Preview')
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b bg-card px-4 py-2 print:hidden">
      <Breadcrumb className="min-w-0 max-md:hidden">
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to="/forms">Forms</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            {store ? (
              <TitleCrumb store={store} />
            ) : (
              <BreadcrumbPage>
                <bdi dir="auto">{form.title || 'Untitled form'}</bdi>
              </BreadcrumbPage>
            )}
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <Button asChild variant="ghost" size="sm" className="md:hidden">
        <Link to="/forms" aria-label="Back to forms">
          <ChevronLeftIcon />
          <bdi dir="auto" className="max-w-40 truncate">
            {form.title || 'Untitled form'}
          </bdi>
        </Link>
      </Button>
      {store && <SaveStatus />}
      <div className="ms-auto flex flex-wrap items-center gap-2">
        {store && <AiButton formId={form.id} />}
        {store && <UndoRedo store={store} />}
        <nav aria-label="Form" className="flex items-center max-md:hidden">
          {nav.map((n) => (
            <Button key={n.to} asChild variant="ghost" size="sm">
              <Link to={n.to} params={{ formId: form.id }} activeProps={{ 'aria-current': 'page', className: 'bg-secondary' }}>
                {n.label}
              </Link>
            </Button>
          ))}
        </nav>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="md:hidden">
              {active.label}
              <ChevronDownIcon />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {nav.map((n) => (
              <DropdownMenuItem key={n.to} asChild>
                <Link to={n.to} params={{ formId: form.id }}>
                  {n.label}
                </Link>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        {store && <FormMenu formId={form.id} />}
        {unpublished && form.currentVersion !== null && (
          <Badge variant="secondary" className="max-sm:hidden">
            Unpublished changes
          </Badge>
        )}
        {store && onPublish && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span tabIndex={!unpublished && form.currentVersion !== null ? 0 : -1} className="rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                <Button size="sm" onClick={onPublish} disabled={!unpublished && form.currentVersion !== null}>
                  Publish
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>
              {!unpublished && form.currentVersion !== null ? `No changes since version ${form.currentVersion}` : 'Publish'}{' '}
              <KbdGroup>
                <Kbd>{MOD_KEY}</Kbd>
                <Kbd>Enter</Kbd>
              </KbdGroup>
            </TooltipContent>
          </Tooltip>
        )}
      </div>
    </div>
  )
}
