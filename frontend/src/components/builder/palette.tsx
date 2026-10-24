/** Question types (Add) and the form outline (PHASE-2-SCREENS 2.4). */
import { ChevronRightIcon, EyeOffIcon, SearchIcon, SplitIcon } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Item, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Kbd } from '@/components/ui/kbd'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { Element } from '@/schema'
import { formLanguage } from '@/schema/language'

import { addBlock, focusBlock } from './actions'
import { BLOCK_GROUPS, BLOCK_TYPES, type BlockTypeInfo, blockInfo, blockLabel } from './block-types'
import { usePaletteDrag } from './dnd-state'
import { useBuilder, useStore } from './store'

function matchesQuery(b: BlockTypeInfo, q: string): boolean {
  const query = q.trim().toLowerCase()
  if (!query) return true
  const hay = `${b.label} ${b.keywords} ${b.type}`.toLowerCase()
  return query.split(/\s+/).every((word) => hay.includes(word))
}

function PaletteItem({ info, onAdded }: { info: BlockTypeInfo; onAdded?: () => void }) {
  const store = useStore()
  const { setNodeRef, listeners, attributes } = usePaletteDrag(info.type, !!info.disabled)
  const Icon = info.icon
  const item = (
    <Item
      asChild
      size="sm"
      className={cn(
        'w-full cursor-grab rounded-md py-1.5 text-start hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 active:cursor-grabbing',
        info.disabled && 'cursor-not-allowed opacity-60',
      )}
    >
      <button
        type="button"
        ref={setNodeRef}
        {...listeners}
        {...attributes}
        aria-disabled={info.disabled ? true : undefined}
        onClick={() => {
          if (info.disabled) return
          addBlock(store, info.type)
          onAdded?.()
        }}
      >
        <ItemMedia variant="icon">
          <Icon />
        </ItemMedia>
        <ItemTitle className="font-normal">{info.label}</ItemTitle>
        {info.disabled && (
          <Badge variant="secondary" className="ms-auto">
            {info.disabled}
          </Badge>
        )}
      </button>
    </Item>
  )
  if (info.type === 'repeater')
    return (
      <Tooltip>
        <TooltipTrigger asChild>{item}</TooltipTrigger>
        <TooltipContent side="right">Repeaters can't contain repeaters</TooltipContent>
      </Tooltip>
    )
  return item
}

export function TypeList({ onAdded }: { onAdded?: () => void }) {
  const [query, setQuery] = useState('')
  const shown = BLOCK_TYPES.filter((b) => matchesQuery(b, query))
  return (
    <div className="flex flex-col gap-3">
      <InputGroup>
        <InputGroupAddon>
          <SearchIcon />
        </InputGroupAddon>
        <InputGroupInput
          placeholder="Search question types"
          aria-label="Search question types"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <InputGroupAddon align="inline-end">
          <Kbd>/</Kbd>
        </InputGroupAddon>
      </InputGroup>
      {BLOCK_GROUPS.map((group) => {
        const items = shown.filter((b) => b.group === group)
        if (!items.length) return null
        return (
          // A labelled group, not a heading: the palette comes before the form's h1 (REVIEW P3-6).
          <section key={group} aria-label={group} className="flex flex-col gap-0.5">
            <p aria-hidden className="px-1 pb-1 text-xs font-medium text-muted-foreground">{group}</p>
            {items.map((info) => (
              <PaletteItem key={info.type} info={info} onAdded={onAdded} />
            ))}
          </section>
        )
      })}
      {!shown.length && <p className="px-1 text-sm text-muted-foreground">No question type matches “{query}”.</p>}
    </div>
  )
}

function OutlineRow({ el, depth }: { el: Element; depth: number }) {
  const store = useStore()
  const selected = useBuilder((s) => s.selection.type === 'element' && s.selection.id === el.id)
  const language = useBuilder((s) => formLanguage(s.schema))
  const info = blockInfo(el)
  const Icon = info.icon
  const label = blockLabel(el)
  const children = el.kind === 'section' || el.kind === 'repeater' ? (el.elements ?? []) : null
  const row = (
    <Button
      variant="ghost"
      size="sm"
      aria-current={selected || undefined}
      className={cn('h-8 w-full justify-start gap-2 font-normal', selected && 'bg-accent hover:bg-accent')}
      style={{ paddingInlineStart: `${0.5 + depth * 0.75}rem` }}
      onClick={() => {
        store.select({ type: 'element', id: el.id })
        window.setTimeout(() => {
          document.querySelector(`[data-block="${el.id}"]`)?.scrollIntoView({ block: 'nearest' })
          focusBlock(el.id)
        }, 0)
      }}
    >
      <Icon className="text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate text-start">
        {label ? (
          <bdi dir="auto" lang={language}>
            {label}
          </bdi>
        ) : (
          <span className="text-muted-foreground">{info.label}</span>
        )}
      </span>
      {el.visibleIf && (
        <Tooltip>
          <TooltipTrigger asChild>
            <EyeOffIcon aria-label="Conditional" className="text-muted-foreground" />
          </TooltipTrigger>
          <TooltipContent>Shown only when a rule matches</TooltipContent>
        </Tooltip>
      )}
    </Button>
  )
  if (!children) return row
  return (
    <Collapsible defaultOpen>
      <div className="flex items-center">
        <Tooltip>
          <TooltipTrigger asChild>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="icon-xs" aria-label={`Show or hide ${label || info.label}`} className="group/c">
                <ChevronRightIcon className="transition-transform group-data-[state=open]/c:rotate-90 motion-reduce:transition-none" />
              </Button>
            </CollapsibleTrigger>
          </TooltipTrigger>
          <TooltipContent>{`Show or hide ${label || info.label}`}</TooltipContent>
        </Tooltip>
        <div className="min-w-0 flex-1">{row}</div>
      </div>
      <CollapsibleContent>
        {children.map((c) => (
          <OutlineRow key={c.id} el={c} depth={depth + 1} />
        ))}
      </CollapsibleContent>
    </Collapsible>
  )
}

function Outline() {
  const store = useStore()
  const pages = useBuilder((s) => s.schema.pages)
  const pageId = useBuilder((s) => s.pageId)
  const language = useBuilder((s) => formLanguage(s.schema))
  return (
    <nav aria-label="Form outline" className="flex flex-col gap-2">
      {pages.map((page, i) => (
        <Collapsible key={page.id} defaultOpen>
          <div className="flex items-center">
            <Tooltip>
              <TooltipTrigger asChild>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="icon-xs" aria-label={`Show or hide page ${i + 1}`} className="group/c">
                    <ChevronRightIcon className="transition-transform group-data-[state=open]/c:rotate-90 motion-reduce:transition-none" />
                  </Button>
                </CollapsibleTrigger>
              </TooltipTrigger>
              <TooltipContent>{`Show or hide page ${i + 1}`}</TooltipContent>
            </Tooltip>
            <Button
              variant="ghost"
              size="sm"
              className={cn('h-8 min-w-0 flex-1 justify-start font-medium', page.id === pageId && 'bg-secondary')}
              onClick={() => store.setPage(page.id)}
            >
              <span className="tabular-nums">{i + 1}.</span>
              <span className="min-w-0 truncate">
                {page.title ? (
                  <bdi dir="auto" lang={language}>
                    {page.title}
                  </bdi>
                ) : (
                  `Page ${i + 1}`
                )}
              </span>
              {(page.next?.length ?? 0) > 0 && <SplitIcon aria-label="Has jump rules" className="ms-auto text-muted-foreground" />}
            </Button>
          </div>
          <CollapsibleContent className="ps-3">
            {(page.elements ?? []).map((el) => (
              <OutlineRow key={el.id} el={el} depth={0} />
            ))}
            {!(page.elements ?? []).length && <p className="px-3 py-1 text-sm text-muted-foreground">No questions yet</p>}
          </CollapsibleContent>
        </Collapsible>
      ))}
    </nav>
  )
}

export function Palette() {
  return (
    <section aria-label="Question types" className="flex h-full min-h-0 flex-col bg-card">
      <Tabs defaultValue="add" className="flex min-h-0 flex-1 flex-col gap-0">
        <div className="border-b p-3">
          <TabsList className="w-full">
            <TabsTrigger value="add">Add</TabsTrigger>
            <TabsTrigger value="outline">Outline</TabsTrigger>
          </TabsList>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <TabsContent value="add" className="p-3">
            <TypeList />
          </TabsContent>
          <TabsContent value="outline" className="p-2">
            <Outline />
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </section>
  )
}
