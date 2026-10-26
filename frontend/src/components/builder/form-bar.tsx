/**
 * The bar inside a form (PHASE-2-SCREENS 2.3, STUDIO-HEADER-MOBILE): title, save state, undo,
 * the form's pages, publish. Sticky under the app header. Below 1024px it is one compact row
 * (back, title, save icon, Publish when there is something to publish, one menu); on phones it
 * is the only bar (the app header steps aside).
 */
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import {
  ChevronLeftIcon,
  CircleCheckIcon,
  CloudOffIcon,
  EllipsisIcon,
  EllipsisVerticalIcon,
  FileDiffIcon,
  MessageSquareTextIcon,
  Redo2Icon,
  SendIcon,
  SparklesIcon,
  SplitIcon,
  TriangleAlertIcon,
  Undo2Icon,
} from 'lucide-react'
import { useThaanaKeyboard } from '@yashau/thaana-react'
import { type RefObject, useRef, useState } from 'react'

import { useAi, useAiController } from '@/components/ai/controller'
import { isSubmissionsPath, useAsk } from '@/components/insights/ask-state'
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
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Kbd, KbdGroup } from '@/components/ui/kbd'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useHeightVar } from '@/components/layout/sticky'
import { useMenuTooltip } from '@/components/layout/use-menu-tooltip'
import type { FormSummary } from '@/lib/api'
import { MOD_KEY } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'
import { contentProps, formLanguage } from '@/schema/language'

import { activeNav, FORM_NAV as NAV, type NavItem } from './form-nav'
import { LogicOverview } from './logic-overview'
import { type BuilderStore, useBuilder, useStore } from './store'

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

/** Opens or closes the AI assistant panel (PHASE-5-SCREENS 1), going to Edit first; null when AI is off. */
function useAiToggle(formId: string) {
  const ai = useAiController()
  const open = useAi(ai, (s) => s.open)
  const navigate = useNavigate()
  const editing = useRouterState({ select: (s) => s.location.pathname.endsWith('/edit') })
  if (!ai) return null
  return {
    shown: open && editing,
    toggle: () => {
      if (!editing) {
        void navigate({ to: '/forms/$formId/edit', params: { formId } })
        ai.setOpen(true)
      } else ai.setOpen(!open)
    },
  }
}

/** The form bar's AI entry, by page: on Submissions (Responses, Insights, a submission) it
 * opens "Ask your submissions"; elsewhere the builder's assistant ("Edit with AI", going to
 * Edit first). Null when neither is available. */
function useAiEntry(formId: string) {
  const edit = useAiToggle(formId)
  const ask = useAsk()
  const onSubmissions = useRouterState({ select: (s) => isSubmissionsPath(s.location.pathname) })
  if (ask?.available && onSubmissions)
    return {
      label: 'Ask about submissions',
      tip: 'Ask questions about these submissions',
      close: 'Close Ask your submissions',
      icon: MessageSquareTextIcon,
      shown: ask.open,
      toggle: () => ask.setOpen(!ask.open),
    }
  if (edit)
    return {
      label: 'Edit with AI',
      tip: 'Change this form with the AI assistant',
      close: 'Close AI assistant',
      icon: SparklesIcon,
      shown: edit.shown,
      toggle: edit.toggle,
    }
  return null
}

/** Opens the page's AI panel (PHASE-5-SCREENS 1, INSIGHTS-SCREENS 4); absent when AI is off. */
function AiButton({ formId }: { formId: string }) {
  const ai = useAiEntry(formId)
  if (!ai) return null
  const Icon = ai.icon
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-pressed={ai.shown}
          aria-label={ai.label}
          className={ai.shown ? 'bg-secondary' : undefined}
          onClick={ai.toggle}
        >
          <Icon />
          <span className="max-xl:hidden">{ai.label}</span>
        </Button>
      </TooltipTrigger>
      <TooltipContent>{ai.tip}</TooltipContent>
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
    <BreadcrumbPage className="min-w-0">
      <button
        type="button"
        className="block max-w-64 truncate rounded-sm text-start outline-none pointer-coarse:min-h-11 hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
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


/** Desktop "…" menu. */
function FormMenu({ onLogic, trigger }: { onLogic: () => void; trigger: RefObject<HTMLButtonElement | null> }) {
  const menuTip = useMenuTooltip()
  return (
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
        <DropdownMenuItem onSelect={onLogic}>
          <SplitIcon />
          View all logic
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** The form's title as the draft has it (renames show at once), in the form's language. */
function DraftTitle() {
  const schema = useBuilder((s) => s.schema)
  const title = schema.settings.title
  return title ? (
    <bdi dir="auto" lang={formLanguage(schema)}>
      {title}
    </bdi>
  ) : (
    'Untitled form'
  )
}

const SAVE_WORDS = {
  saved: 'Saved',
  saving: 'Saving…',
  offline: 'Offline. Changes will save when you reconnect',
} as const

/** Save state as one icon, its words for screen readers and as a hover title (compact bar). */
function SaveIcon() {
  const store = useStore()
  const status = useBuilder((s) => s.status)
  const error = useBuilder((s) => s.error)
  return (
    <div role="status" className="flex shrink-0 items-center">
      {status === 'error' ? (
        <Button
          variant="ghost"
          size="icon"
          className="text-destructive hover:text-destructive"
          title={error ?? undefined}
          aria-label="Couldn't save. Retry"
          onClick={() => void store.flush()}
        >
          <TriangleAlertIcon />
        </Button>
      ) : (
        <span
          className={cn(
            'flex size-8 items-center justify-center pointer-coarse:size-11 [&_svg]:size-4',
            status === 'offline' ? 'text-foreground' : 'text-muted-foreground',
          )}
          title={SAVE_WORDS[status]}
        >
          {status === 'saved' ? (
            <CircleCheckIcon aria-hidden />
          ) : status === 'saving' ? (
            <Spinner aria-hidden />
          ) : (
            <CloudOffIcon aria-hidden />
          )}
          <span className="sr-only">{SAVE_WORDS[status]}</span>
        </span>
      )}
    </div>
  )
}

/** Undo and redo as menu items; choosing one keeps the menu open so it can be repeated. */
function UndoRedoItems({ store }: { store: BuilderStore }) {
  const canUndo = useBuilder(() => store.canUndo)
  const canRedo = useBuilder(() => store.canRedo)
  const locked = useBuilder((s) => s.locked)
  return (
    <>
      <DropdownMenuItem
        disabled={locked || !canUndo}
        onSelect={(e) => {
          e.preventDefault()
          void store.undo()
        }}
      >
        <Undo2Icon />
        Undo
      </DropdownMenuItem>
      <DropdownMenuItem
        disabled={locked || !canRedo}
        onSelect={(e) => {
          e.preventDefault()
          void store.redo()
        }}
      >
        <Redo2Icon />
        Redo
      </DropdownMenuItem>
      {locked && (
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Apply or discard the suggestion first
        </DropdownMenuLabel>
      )}
    </>
  )
}

type CompactProps = {
  form: FormSummary
  store: BuilderStore | null
  nav: readonly NavItem[]
  active: NavItem
  canPublish: boolean
  onPublish?: () => void
  onLogic: () => void
  trigger: RefObject<HTMLButtonElement | null>
}

/** The compact bar's one menu: the form's pages, history, assistant, logic, and Publish with
 * the reason when there is nothing to publish. */
function CompactMenu({ form, store, nav, active, canPublish, onPublish, onLogic, trigger }: CompactProps) {
  const navigate = useNavigate()
  const ai = useAiEntry(form.id)
  const AiIcon = ai?.icon
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button ref={trigger} variant="ghost" size="icon" className="shrink-0" aria-label="Form menu">
          <EllipsisVerticalIcon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-56">
        <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">Go to</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={active.to}
          onValueChange={(to) => void navigate({ to: to as NavItem['to'], params: { formId: form.id } })}
        >
          {nav.map(({ to, label, icon: Icon }) => (
            <DropdownMenuRadioItem key={to} value={to}>
              <Icon />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {ai && AiIcon && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={ai.toggle}>
              <AiIcon />
              {ai.shown ? ai.close : ai.label}
            </DropdownMenuItem>
          </>
        )}
        {store && (
          <>
            <DropdownMenuSeparator />
            <UndoRedoItems store={store} />
            <DropdownMenuItem onSelect={onLogic}>
              <SplitIcon />
              View all logic
            </DropdownMenuItem>
          </>
        )}
        {store && onPublish && canPublish && form.currentVersion !== null && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => store.setReviewing(true)}>
              <FileDiffIcon />
              Review changes
            </DropdownMenuItem>
          </>
        )}
        {store && onPublish && !canPublish && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled className="flex-col items-start gap-0.5">
              <span className="flex items-center gap-2">
                <SendIcon />
                Publish
              </span>
              <span className="text-xs">No changes since version {form.currentVersion}</span>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Below 1024px: one row. Back, the title over the current page's name, save icon, Publish
 * while there is something to publish, and one menu for the rest. */
function CompactBar(props: CompactProps) {
  const { form, store, active, canPublish, onPublish } = props
  return (
    <nav aria-label="Form" className="flex h-14 items-center gap-1 ps-1 pe-2 sm:px-3 lg:hidden">
      <Button asChild variant="ghost" size="icon" className="shrink-0">
        <Link to="/forms" aria-label="Back to forms">
          <ChevronLeftIcon />
        </Link>
      </Button>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-sm leading-5 font-medium">
          {store ? <DraftTitle /> : <bdi dir="auto">{form.title || 'Untitled form'}</bdi>}
        </span>
        <span className="truncate text-xs leading-4 text-muted-foreground">{active.label}</span>
      </div>
      {store && <SaveIcon />}
      {store && onPublish && canPublish && (
        <Button size="sm" className="shrink-0" onClick={() => onPublish()}>
          Publish
        </Button>
      )}
      <CompactMenu {...props} />
    </nav>
  )
}

export function FormBar({
  form,
  store,
  unpublished,
  onPublish,
  sticky = true,
}: {
  form: FormSummary
  store: BuilderStore | null
  unpublished: boolean
  onPublish?: () => void
  /** Off where the bar heads a full-height layout that scrolls inside (the builder). */
  sticky?: boolean
}) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const active = activeNav(pathname)
  const nav = store ? NAV : NAV.filter((n) => n.label !== 'Edit' && n.label !== 'Preview')
  const canPublish = unpublished || form.currentVersion === null
  const bar = useRef<HTMLDivElement>(null)
  useHeightVar(bar, '--form-bar-h')
  const [logic, setLogic] = useState(false)
  const desktopTrigger = useRef<HTMLButtonElement>(null)
  const compactTrigger = useRef<HTMLButtonElement>(null)
  // Focus goes back to whichever menu opened the logic sheet (only one bar is shown).
  const logicReturn = useRef<HTMLElement | null>(null)
  const openLogic = () => {
    logicReturn.current = desktopTrigger.current?.offsetParent ? desktopTrigger.current : compactTrigger.current
    setLogic(true)
  }
  return (
    <div
      ref={bar}
      data-form-bar
      className={cn('z-20 shrink-0 border-b bg-card print:hidden', sticky && 'sticky top-(--app-bar-h,0px)')}
    >
      <CompactBar
        form={form}
        store={store}
        nav={nav}
        active={active}
        canPublish={canPublish}
        onPublish={onPublish}
        onLogic={openLogic}
        trigger={compactTrigger}
      />
      <div className="flex items-center gap-3 px-4 py-2 max-lg:hidden">
        <Breadcrumb className="min-w-0">
          <BreadcrumbList className="flex-nowrap">
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/forms">Forms</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem className="min-w-0">
              {store ? (
                <TitleCrumb store={store} />
              ) : (
                <BreadcrumbPage className="truncate">
                  <bdi dir="auto">{form.title || 'Untitled form'}</bdi>
                </BreadcrumbPage>
              )}
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        {store && <SaveStatus />}
        <div className="ms-auto flex shrink-0 items-center gap-2">
          <AiButton formId={form.id} />
          {store && <UndoRedo store={store} />}
          <nav aria-label="Form" className="flex items-center">
            {nav.map((n) => (
              <Button key={n.to} asChild variant="ghost" size="sm">
                <Link
                  to={n.to}
                  params={{ formId: form.id }}
                  aria-current={n === active ? 'page' : undefined}
                  className={n === active ? 'bg-secondary' : undefined}
                >
                  {n.label}
                </Link>
              </Button>
            ))}
          </nav>
          {store && <FormMenu onLogic={openLogic} trigger={desktopTrigger} />}
          {unpublished && form.currentVersion !== null && (
            <Badge variant="secondary" className="max-xl:hidden">
              Unpublished changes
            </Badge>
          )}
          {store && onPublish && unpublished && form.currentVersion !== null && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" onClick={() => store.setReviewing(true)}>
                  <FileDiffIcon />
                  <span className="max-xl:sr-only">Review changes</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>What publishing would change</TooltipContent>
            </Tooltip>
          )}
          {store && onPublish && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  tabIndex={!canPublish ? 0 : -1}
                  className="rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <Button size="sm" onClick={() => onPublish()} disabled={!canPublish}>
                    Publish
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                {!canPublish ? `No changes since version ${form.currentVersion}` : 'Publish'}{' '}
                <KbdGroup>
                  <Kbd>{MOD_KEY}</Kbd>
                  <Kbd>Enter</Kbd>
                </KbdGroup>
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      </div>
      {store && <LogicOverview open={logic} onOpenChange={setLogic} formId={form.id} returnFocus={logicReturn} />}
    </div>
  )
}
