/**
 * The builder canvas: the real renderer in edit mode on a sheet at the respondent's width
 * (WYSIWYG), with selectable, draggable blocks and a page strip (PHASE-2-SCREENS 2.5, 2.6).
 */
import {
  ChevronDownIcon,
  EllipsisIcon,
  EyeOffIcon,
  GripVerticalIcon,
  LockIcon,
  PlusIcon,
  RepeatIcon,
  Settings2Icon,
  SparklesIcon,
  TriangleAlertIcon,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { type KeyboardEvent, type MouseEvent, type ReactNode, useContext, useMemo, useState } from 'react'

import { useAiController } from '@/components/ai/controller'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { DirectionProvider } from '@/components/ui/direction'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
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
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { Kbd } from '@/components/ui/kbd'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useMenuTooltip } from '@/components/layout/use-menu-tooltip'
import { MOD_KEY } from '@/lib/shortcuts'
import { formThemeQuery } from '@/lib/queries'
import { canvasMode, themeScope, useFontLinks } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { RendererContext, type RendererContextValue } from '@/renderer/context'
import { FieldControl } from '@/renderer/fields'
import {
  ContentView,
  QuestionGrid,
  QuestionView,
  SectionFrame,
} from '@/renderer/elements'
import { RepeaterFrame } from '@/renderer/repeater'
import { DESCRIPTION } from '@/renderer/elements'
import { FormHeader } from '@/renderer/form-view'
import { MSG } from '@/renderer/messages'
import { Markdown } from '@/renderer/markdown'
import { widthClass } from '@/renderer/util'
import type { Element, Form } from '@/schema'
import { contentProps, formLanguage } from '@/schema/language'

import {
  currentPageIndex,
  duplicate,
  focusBlock,
  moveToPage,
  nudge,
  requestDelete,
  wrap,
} from './actions'
import { blockInfo } from './block-types'
import { NavPreview, OptionList, PlaceholderControl, SuccessPreview } from './canvas-text'
import { type ElementText, PLACEHOLDER_TYPES, setElementText, setPageText, setSettingsText, textKey } from './inline-edit'
import { InlineText } from './inline-text'
import { ConditionSentence } from './condition-sentence'
import { DropLine } from './dnd'
import { useBlockDrag, useBlockDrop, useEndDrop } from './dnd-state'
import { InspectorDrawerContext } from './drawer-context'
import { FormContext } from './form-context'
import { useBuilder, useStore } from './store'
import { allElements, type Container, type Location } from './tree'
import { elementProblems } from './problems'

/** Ids of blocks in document order on one page (for ↑/↓ selection). */
function pageOrder(form: Form, pageIndex: number): string[] {
  return allElements(form)
    .filter((e) => e.loc.pageIndex === pageIndex)
    .map((e) => e.el.id)
}

function BlockMenuItems({
  id,
  Item,
  Separator,
  Shortcut,
  Sub,
  SubTrigger,
  SubContent,
}: {
  id: string
  Item: typeof DropdownMenuItem | typeof ContextMenuItem
  Separator: typeof DropdownMenuSeparator | typeof ContextMenuSeparator
  Shortcut: typeof DropdownMenuShortcut | typeof ContextMenuShortcut
  Sub: typeof DropdownMenuSub | typeof ContextMenuSub
  SubTrigger: typeof DropdownMenuSubTrigger | typeof ContextMenuSubTrigger
  SubContent: typeof DropdownMenuSubContent | typeof ContextMenuSubContent
}) {
  const store = useStore()
  const pages = useBuilder((s) => s.schema.pages)
  const pageIndex = currentPageIndex(store)
  return (
    <>
      <Item onSelect={() => duplicate(store, id)}>
        Duplicate<Shortcut>{MOD_KEY}+D</Shortcut>
      </Item>
      <Item onSelect={() => nudge(store, id, -1)}>
        Move up<Shortcut>Alt+↑</Shortcut>
      </Item>
      <Item onSelect={() => nudge(store, id, 1)}>
        Move down<Shortcut>Alt+↓</Shortcut>
      </Item>
      {pages.length > 1 && (
        <Sub>
          <SubTrigger>Move to page</SubTrigger>
          <SubContent>
            {pages.map((p, i) =>
              i === pageIndex ? null : (
                <Item key={p.id} onSelect={() => moveToPage(store, id, i)}>
                  {i + 1}.{' '}
                  {p.title ? (
                    <bdi dir="auto" lang={formLanguage(store.get().schema)}>
                      {p.title}
                    </bdi>
                  ) : (
                    `Page ${i + 1}`
                  )}
                </Item>
              ),
            )}
          </SubContent>
        </Sub>
      )}
      <Item onSelect={() => wrap(store, id)}>Wrap in section</Item>
      <Item
        onSelect={() => {
          store.select({ type: 'element', id })
          window.setTimeout(() => document.getElementById('inspector-logic')?.click(), 0)
        }}
      >
        Add logic
      </Item>
      <Separator />
      <Item variant="destructive" onSelect={() => requestDelete(store, id)}>
        Delete<Shortcut>Del</Shortcut>
      </Item>
    </>
  )
}

function Indicators({ el, form }: { el: Element; form: Form }) {
  const problems = elementProblems(form, el)
  return (
    <span className="ms-2 inline-flex flex-wrap items-center gap-1 align-middle" lang="en" dir="ltr">
      {problems.length > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="destructive" tabIndex={0}>
              <TriangleAlertIcon data-icon="inline-start" />
              Fix
            </Badge>
          </TooltipTrigger>
          <TooltipContent>{problems[0]}</TooltipContent>
        </Tooltip>
      )}
      {el.visibleIf && (
        <HoverCard openDelay={200}>
          <HoverCardTrigger asChild>
            <Badge variant="outline" tabIndex={0} className="font-normal">
              <EyeOffIcon data-icon="inline-start" />
              Conditional
            </Badge>
          </HoverCardTrigger>
          <HoverCardContent className="w-80 text-sm font-normal">
            <ConditionSentence cond={el.visibleIf} form={form} prefix="Shown when" />.
          </HoverCardContent>
        </HoverCard>
      )}
      {el.kind === 'field' && el.sensitive && (
        <Badge variant="outline" className="font-normal">
          <LockIcon data-icon="inline-start" />
          Sensitive
        </Badge>
      )}
      {el.kind === 'repeater' && (
        <Badge variant="outline" className="font-normal">
          <RepeatIcon data-icon="inline-start" />
          Repeats
        </Badge>
      )}
    </span>
  )
}

/** Which text of an element is its heading (label, title or the text block itself). */
function headingPart(el: Element): ElementText | null {
  if (el.kind === 'field' || el.kind === 'repeater') return 'label'
  if (el.kind === 'section') return 'title'
  if (el.kind === 'content' && (el.contentType === 'heading' || el.contentType === 'paragraph')) return 'text'
  return null
}

interface TextOpts {
  name: string
  multiline?: boolean
  empty?: ReactNode
  prompt?: string
  display?: ReactNode
  className?: string
  block?: boolean
}

function Block({ el, loc, form }: { el: Element; loc: Location; form: Form }) {
  const menuTip = useMenuTooltip()
  const store = useStore()
  const selected = useBuilder((s) => s.selection.type === 'element' && s.selection.id === el.id)
  const part = headingPart(el)
  const editing = useBuilder((s) => part !== null && s.editing === textKey.element(el.id, part))
  const highlighted = useBuilder((s) => s.highlight.has(el.id))
  // While one of its texts is typed in, the block's menu button steps aside (it would cover the
  // end of the box on phones).
  const typingHere = useBuilder((s) => !!s.editing && s.editing.includes(`:${el.id}:`))
  const [sectionOpen, setSectionOpen] = useState(true)
  const drawerInspector = useContext(InspectorDrawerContext)
  const { setNodeRef: setDragHandle, setActivatorNodeRef, listeners, attributes, isDragging } = useBlockDrag(el.id)
  const { setNodeRef: setDropRef } = useBlockDrop(el.id, loc)
  const info = blockInfo(el)
  const language = formLanguage(form)
  const activate = (edit?: string) => store.select({ type: 'element', id: el.id }, { edit })
  const labelText =
    el.kind === 'field' || el.kind === 'repeater' ? el.label : el.kind === 'section' ? (el.title ?? '') : ''
  const commit = (p: ElementText) => (value: string) => {
    let renamed = el.id
    store.edit((f) => {
      const out = setElementText(f, el.id, p, value)
      renamed = out.id
      return out.form
    })
    if (renamed !== el.id) store.select({ type: 'element', id: renamed })
  }
  const text = (p: ElementText, value: string, opts: TextOpts) => (
    <InlineText
      editKey={textKey.element(el.id, p)}
      value={value}
      language={language}
      active={selected}
      activate={activate}
      onCommit={commit(p)}
      {...opts}
    />
  )
  const description = (value: string | null | undefined, prompt: string) =>
    text('description', value ?? '', {
      name: 'description',
      multiline: true,
      prompt,
      block: true,
      className: DESCRIPTION,
      display: value ? <Markdown text={value} rtl={language === 'dv'} /> : undefined,
    })
  const indicators = editing ? null : <Indicators el={el} form={form} />
  const label =
    el.kind === 'section'
      ? text('title', labelText, { name: 'section title', empty: 'Untitled section' })
      : text('label', labelText, {
          name: el.kind === 'repeater' ? 'repeater label' : 'question label',
          empty: 'Untitled question',
        })

  let content: ReactNode
  switch (el.kind) {
    case 'field':
      content =
        el.type === 'hidden' ? (
          <div className="flex items-center gap-2 rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
            <EyeOffIcon className="size-4" />
            <span lang="en" dir="ltr">
              Hidden value
            </span>
            {label}
            <Indicators el={el} form={form} />
          </div>
        ) : (
          <QuestionView
            field={el}
            path={{ id: el.id }}
            required={!!el.required}
            label={label}
            extra={indicators}
            description={el.description || selected ? description(el.description, 'Add help text…') : null}
            control={
              el.type === 'single_choice' || el.type === 'multi_choice' ? (
                <OptionList field={el} active={selected} />
              ) : PLACEHOLDER_TYPES.has(el.type) ? (
                <PlaceholderControl field={el} active={selected} />
              ) : (
                // Only a picture of the control: kept out of the tab order and the
                // accessibility tree, so the block's own buttons are what you reach.
                <div inert aria-hidden className="pointer-events-none">
                  <FieldControl field={el} path={{ id: el.id }} invalid={false} />
                </div>
              )
            }
          />
        )
      break
    case 'content':
      content = (
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            {el.contentType === 'heading' ? (
              <h3 className="text-xl font-semibold tracking-tight">
                {text('text', el.text ?? '', { name: 'heading', empty: 'Add text…' })}
              </h3>
            ) : el.contentType === 'paragraph' ? (
              text('text', el.text ?? '', {
                name: 'paragraph',
                multiline: true,
                block: true,
                empty: 'Add text…',
                className: 'max-w-[36em] text-base',
                display: el.text ? <Markdown text={el.text} rtl={language === 'dv'} /> : undefined,
              })
            ) : (
              <ContentView el={el} placeholder={<span className="text-muted-foreground">Empty text block</span>} />
            )}
          </div>
          <Indicators el={el} form={form} />
        </div>
      )
      break
    case 'section': {
      const count = (el.elements ?? []).length
      content = (
        <Collapsible open={sectionOpen} onOpenChange={setSectionOpen}>
          <SectionFrame
            el={el}
            description={el.description || selected ? description(el.description, 'Add a description…') : null}
            title={
              <span className="flex items-center gap-1">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <CollapsibleTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        lang="en"
                        aria-label={sectionOpen ? 'Collapse section' : 'Expand section'}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <ChevronDownIcon
                          className={cn(
                            'transition-transform motion-reduce:transition-none',
                            !sectionOpen && '-rotate-90 rtl:rotate-90',
                          )}
                        />
                      </Button>
                    </CollapsibleTrigger>
                  </TooltipTrigger>
                  <TooltipContent>{sectionOpen ? 'Collapse section' : 'Expand section'}</TooltipContent>
                </Tooltip>
                {label}
                {indicators}
              </span>
            }
          >
            <CollapsibleContent>
              <CanvasList form={form} container={{ pageIndex: loc.pageIndex, parentId: el.id }} elements={el.elements ?? []} />
            </CollapsibleContent>
            {!sectionOpen && (
              <p className="text-sm text-muted-foreground" lang="en" dir="ltr">
                {count === 1 ? '1 question' : `${count} questions`} hidden while collapsed
              </p>
            )}
          </SectionFrame>
        </Collapsible>
      )
      break
    }
    case 'repeater':
      content = (
        <div className="rounded-md border border-dashed p-4">
          <RepeaterFrame
            el={el}
            description={el.description || selected ? description(el.description, 'Add a description…') : null}
            addText={text('addLabel', el.addLabel ?? '', {
              name: 'add button text',
              empty: <bdi lang="en" dir="ltr">{MSG.addEntry}</bdi>,
            })}
            label={
              <>
                {label}
                {indicators}
              </>
            }
            sample={
              <CanvasList form={form} container={{ pageIndex: loc.pageIndex, parentId: el.id }} elements={el.elements ?? []} />
            }
          />
        </div>
      )
      break
  }

  const onClick = (e: MouseEvent) => {
    e.stopPropagation()
    store.select({ type: 'element', id: el.id }, { inspect: true })
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return
    const order = pageOrder(store.get().schema, loc.pageIndex)
    const i = order.indexOf(el.id)
    const mod = e.ctrlKey || e.metaKey
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (e.altKey) return nudge(store, el.id, e.key === 'ArrowUp' ? -1 : 1)
      const next = order[i + (e.key === 'ArrowUp' ? -1 : 1)]
      if (next) {
        store.select({ type: 'element', id: next })
        focusBlock(next)
      }
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (!selected) store.select({ type: 'element', id: el.id })
      else if (part) store.setEditing(textKey.element(el.id, part))
    } else if (e.key === 'Escape') {
      store.select({ type: 'page', pageId: store.get().pageId })
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault()
      requestDelete(store, el.id)
    } else if (mod && e.key.toLowerCase() === 'd') {
      e.preventDefault()
      duplicate(store, el.id)
    }
  }

  const dragging = isDragging
  const half = el.kind === 'field' && el.width === 'half'
  return (
    <div
      ref={setDropRef}
      data-block={el.id}
      className={cn('group/block relative min-w-0', widthClass(el), dragging && 'opacity-40')}
    >
      <DropLine loc={loc} />
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <div
            role="group"
            aria-label={`${info.label}: ${labelText || 'Untitled question'}`}
            data-block-focus
            tabIndex={selected ? 0 : -1}
            onClick={onClick}
            onKeyDown={onKeyDown}
            onFocus={(e) => {
              if (e.target === e.currentTarget && !selected) store.select({ type: 'element', id: el.id })
            }}
            className={cn(
              'relative -mx-3 rounded-sm border-s-[3px] border-transparent px-3 py-3 outline-none transition-colors motion-reduce:transition-none',
              'hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50',
              (selected || highlighted) && 'bg-accent hover:bg-accent',
              (selected || (store.readOnly && highlighted)) && 'border-marker-edge',
            )}
          >
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  ref={(node) => {
                    setActivatorNodeRef(node)
                    setDragHandle(node)
                  }}
                  {...listeners}
                  {...attributes}
                  aria-label={`Drag ${labelText || info.label}`}
                  className={cn(
                    'absolute flex size-7 cursor-grab touch-none items-center justify-center rounded-md text-muted-foreground opacity-0 outline-none transition-opacity hover:bg-muted focus-visible:opacity-100 focus-visible:ring-3 focus-visible:ring-ring/50 group-hover/block:opacity-100 motion-reduce:transition-none',
                    // A half-width block's start edge is its neighbour's end edge, so the handle sits
                    // on the top edge (mirroring the actions button) instead of in the gutter.
                    half ? '-top-3.5 start-2 z-10 border bg-card hover:bg-muted' : '-start-9 top-3',
                    selected && 'opacity-100',
                  )}
                  onClick={(e) => e.stopPropagation()}
                >
                  <GripVerticalIcon className="size-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="left">Drag to move, or press Space</TooltipContent>
            </Tooltip>
            {selected && !typingHere && (
              <div className="absolute -top-3.5 end-2 z-10" lang="en">
                <div dir="ltr" className="flex items-center gap-1">
                {drawerInspector && !store.readOnly && (
                  <Button
                    variant="outline"
                    size="xs"
                    className="bg-card"
                    onClick={(e) => {
                      e.stopPropagation()
                      store.select({ type: 'element', id: el.id }, { inspect: true })
                    }}
                  >
                    <Settings2Icon data-icon="inline-start" />
                    Settings
                  </Button>
                )}
                <DropdownMenu>
                  <Tooltip {...menuTip.tooltip}>
                    <TooltipTrigger asChild>
                      <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="icon-xs" aria-label="Question actions" className="bg-card">
                          <EllipsisIcon />
                        </Button>
                      </DropdownMenuTrigger>
                    </TooltipTrigger>
                    <TooltipContent>Question actions</TooltipContent>
                  </Tooltip>
                  <DropdownMenuContent align="end" className="w-52" {...menuTip.content}>
                    <BlockMenuItems
                      id={el.id}
                      Item={DropdownMenuItem}
                      Separator={DropdownMenuSeparator}
                      Shortcut={DropdownMenuShortcut}
                      Sub={DropdownMenuSub}
                      SubTrigger={DropdownMenuSubTrigger}
                      SubContent={DropdownMenuSubContent}
                    />
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              </div>
            )}
            <div {...contentProps(language)}>{content}</div>
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent className="w-52">
          <BlockMenuItems
            id={el.id}
            Item={ContextMenuItem}
            Separator={ContextMenuSeparator}
            Shortcut={ContextMenuShortcut}
            Sub={ContextMenuSub}
            SubTrigger={ContextMenuSubTrigger}
            SubContent={ContextMenuSubContent}
          />
        </ContextMenuContent>
      </ContextMenu>
    </div>
  )
}

function EndZone({ container, empty }: { container: Container; empty: boolean }) {
  const { setNodeRef } = useEndDrop(container)
  return (
    <div
      ref={setNodeRef}
      className={cn('relative @min-[32rem]:col-span-2', empty ? 'min-h-14' : 'min-h-6')}
      data-end-zone
    >
      <EndLine container={container} />
      {empty && container.parentId !== null && (
        <div className="flex min-h-14 items-center rounded-md border border-dashed px-3 text-sm text-muted-foreground" lang="en" dir="ltr">
          Drop questions here
        </div>
      )}
    </div>
  )
}

function EndLine({ container }: { container: Container }) {
  const len = useBuilder((s) => {
    const page = s.schema.pages[container.pageIndex]
    if (!page) return 0
    if (container.parentId === null) return (page.elements ?? []).length
    const found = allElements(s.schema).find((e) => e.el.id === container.parentId)?.el
    return found && (found.kind === 'section' || found.kind === 'repeater') ? (found.elements ?? []).length : 0
  })
  return <DropLine loc={{ ...container, index: len }} />
}

export function CanvasList({
  form,
  container,
  elements,
}: {
  form: Form
  container: Container
  elements: Element[]
}) {
  return (
    <QuestionGrid className="gap-5">
      {elements.map((el, index) => (
        <Block key={el.id} el={el} form={form} loc={{ ...container, index }} />
      ))}
      <EndZone container={container} empty={elements.length === 0} />
    </QuestionGrid>
  )
}

const NO_ANSWERS = () => undefined

export function Canvas() {
  const store = useStore()
  const ai = useAiController()
  const form = useBuilder((s) => s.schema)
  const pageId = useBuilder((s) => s.pageId)
  const formSelected = useBuilder((s) => s.selection.type === 'form')
  const pageSelected = useBuilder((s) => s.selection.type === 'page' && s.selection.pageId === s.pageId)
  const language = formLanguage(form)
  const pageIndex = Math.max(0, form.pages.findIndex((p) => p.id === pageId))
  const page = form.pages[pageIndex]
  const elements = page.elements ?? []
  // The form's theme on the sheet (FORM-THEME-SCREENS 3.5): saved values, the form's colour mode.
  const summary = useContext(FormContext)
  const theme = useQuery({ ...formThemeQuery(summary?.id ?? ''), enabled: !!summary }).data?.preview
  useFontLinks(theme?.fonts)
  const scope = themeScope(theme, canvasMode(theme))
  const activateForm = (edit?: string) => store.select({ type: 'form' }, { edit })
  const activatePage = (edit?: string) => store.select({ type: 'page', pageId }, { edit })

  const ctx = useMemo<RendererContextValue>(
    () => ({
      form,
      language,
      mode: 'canvas',
      convention: 'optional',
      getValue: NO_ANSWERS,
      setValue: () => {},
      blur: () => {},
      errorFor: () => null,
      isVisible: () => true,
      isRequired: (id) => {
        const el = allElements(form).find((e) => e.el.id === id)?.el
        return el?.kind === 'field' && !!el.required
      },
      highlighted: new Set(),
      uploader: () => Promise.reject(new Error('canvas')),
      setUploading: () => {},
      rowCount: () => 1,
      addRow: () => {},
      removeRow: () => {},
    }),
    [form, language],
  )

  return (
    <RendererContext.Provider value={ctx}>
      <DirectionProvider dir={contentProps(language).dir}>
        <div
          {...scope}
          className={cn(
            scope.className,
            '@container mx-auto flex w-full max-w-[var(--df-sheet,40rem)] flex-col gap-6 rounded-md border bg-card p-5 text-foreground sm:p-10 sm:ps-12',
          )}
          {...contentProps(language)}
          onClick={() => store.select({ type: 'page', pageId })}
        >
          <div
            role="group"
            aria-label="Form title and description"
            className={cn(
              '-m-2 rounded-sm p-2 text-start transition-colors hover:bg-muted/60 motion-reduce:transition-none',
              formSelected && 'bg-accent hover:bg-accent',
            )}
            onClick={(e) => {
              e.stopPropagation()
              store.select({ type: 'form' }, { inspect: true })
            }}
          >
            <FormHeader
              form={form}
              theme={theme ? { ...theme.options, headerImageUrl: null } : undefined}
              title={
                <InlineText
                  editKey={textKey.settings('title')}
                  value={form.settings.title}
                  name="form title"
                  language={language}
                  active={formSelected}
                  activate={activateForm}
                  empty="Untitled form"
                  onCommit={(text) => store.edit((f) => setSettingsText(f, 'title', text))}
                />
              }
              description={
                form.settings.description || formSelected ? (
                  <InlineText
                    editKey={textKey.settings('description')}
                    value={form.settings.description ?? ''}
                    name="form description"
                    language={language}
                    multiline
                    block
                    active={formSelected}
                    activate={activateForm}
                    prompt="Add a description…"
                    className="max-w-[36em] text-base text-muted-foreground"
                    display={form.settings.description ? <Markdown text={form.settings.description} rtl={language === 'dv'} /> : undefined}
                    onCommit={(text) => store.edit((f) => setSettingsText(f, 'description', text))}
                  />
                ) : null
              }
            />
          </div>
          <div
            role="group"
            aria-label={`Page ${pageIndex + 1}`}
            className={cn(
              '-m-2 flex flex-col gap-1 rounded-sm border-t p-2 pt-6 text-start transition-colors hover:bg-muted/60 motion-reduce:transition-none',
              pageSelected && 'bg-accent hover:bg-accent',
            )}
            onClick={(e) => {
              e.stopPropagation()
              store.select({ type: 'page', pageId }, { inspect: true })
            }}
          >
            <h2 className={cn('text-xl', language === 'dv' ? 'font-bold' : 'font-[650] tracking-tight')}>
              <InlineText
                editKey={textKey.page(pageId, 'title')}
                value={page.title ?? ''}
                name="page title"
                language={language}
                active={pageSelected}
                activate={activatePage}
                empty={`Page ${pageIndex + 1}`}
                placeholder={`Page ${pageIndex + 1}`}
                onCommit={(text) => store.edit((f) => setPageText(f, pageId, 'title', text))}
              />
            </h2>
            {(page.description || pageSelected) && (
              <InlineText
                editKey={textKey.page(pageId, 'description')}
                value={page.description ?? ''}
                name="page description"
                language={language}
                multiline
                block
                active={pageSelected}
                activate={activatePage}
                prompt="Add a description…"
                className="max-w-[36em] text-base text-muted-foreground"
                display={page.description ? <Markdown text={page.description} rtl={language === 'dv'} /> : undefined}
                onCommit={(text) => store.edit((f) => setPageText(f, pageId, 'description', text))}
              />
            )}
          </div>
          {elements.length === 0 ? (
            <div className="relative" lang="en" dir="ltr">
              <EndZone container={{ pageIndex, parentId: null }} empty />
              <Empty className="border">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <PlusIcon />
                  </EmptyMedia>
                  <EmptyTitle>No questions on this page yet</EmptyTitle>
                  <EmptyDescription>
                    Drag a question here from the left, or press <Kbd>/</Kbd> to search.
                  </EmptyDescription>
                </EmptyHeader>
                <EmptyContent className="flex-row flex-wrap justify-center">
                  <Button
                    onClick={(e) => {
                      e.stopPropagation()
                      store.setInserting(true)
                    }}
                  >
                    <PlusIcon />
                    Add question
                  </Button>
                  {ai && !store.readOnly && pageIndex === 0 && (
                    <Button
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation()
                        ai.setOpen(true)
                      }}
                    >
                      <SparklesIcon />
                      Describe your form
                    </Button>
                  )}
                </EmptyContent>
              </Empty>
            </div>
          ) : (
            <CanvasList form={form} container={{ pageIndex, parentId: null }} elements={elements} />
          )}
          {elements.length > 0 && (
            <Button
              variant="outline"
              className="self-start"
              lang="en"
              dir="ltr"
              onClick={(e) => {
                e.stopPropagation()
                store.select({ type: 'page', pageId })
                store.setInserting(true)
              }}
            >
              <PlusIcon />
              Add question
            </Button>
          )}
          <NavPreview form={form} pageIndex={pageIndex} language={language} />
          {pageIndex === form.pages.length - 1 && <SuccessPreview form={form} language={language} />}
        </div>
      </DirectionProvider>
    </RendererContext.Provider>
  )
}

