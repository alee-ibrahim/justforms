/** Numbered page chips above the canvas (PHASE-2-SCREENS 2.6). */
import { EllipsisIcon, EyeOffIcon, PlusIcon, SplitIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useMenuTooltip } from '@/components/layout/use-menu-tooltip'
import { cn } from '@/lib/utils'
import { formLanguage } from '@/schema/language'

import { useChipDrop, useDropTarget } from './dnd-state'
import { formProblems } from './problems'
import { useBuilder, useStore } from './store'
import { addPage, duplicatePage, movePage } from './tree'

function Chip({ index }: { index: number }) {
  const menuTip = useMenuTooltip()
  const store = useStore()
  const form = useBuilder((s) => s.schema)
  const current = useBuilder((s) => s.pageId === s.schema.pages[index]?.id)
  const page = form.pages[index]
  const { setNodeRef } = useChipDrop(index)
  const { target } = useDropTarget()
  const over = target?.kind === 'page' && target.pageIndex === index
  const broken = formProblems(form).some((p) => p.pageIndex === index)
  const lang = formLanguage(form)
  return (
    <div ref={setNodeRef} className={cn('flex shrink-0 items-center rounded-md', over && 'bg-accent ring-2 ring-marker-edge')}>
      <Button
        variant={current ? 'secondary' : 'ghost'}
        size="sm"
        aria-current={current ? 'page' : undefined}
        className="max-w-56 gap-1.5 rounded-e-none"
        onClick={() => store.setPage(page.id)}
      >
        <span className="tabular-nums">{index + 1}</span>
        <span className="min-w-0 truncate">
          {page.title ? (
            <bdi dir="auto" lang={lang}>
              {page.title}
            </bdi>
          ) : (
            `Page ${index + 1}`
          )}
        </span>
        {(page.next?.length ?? 0) > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <SplitIcon aria-label="Has jump rules" />
            </TooltipTrigger>
            <TooltipContent>Has jump rules</TooltipContent>
          </Tooltip>
        )}
        {page.visibleIf && (
          <Tooltip>
            <TooltipTrigger asChild>
              <EyeOffIcon aria-label="Shown only when a rule matches" />
            </TooltipTrigger>
            <TooltipContent>Shown only when…</TooltipContent>
          </Tooltip>
        )}
        {broken && <span className="size-1.5 rounded-full bg-destructive" aria-label="Has problems" />}
      </Button>
      <DropdownMenu>
        <Tooltip {...menuTip.tooltip}>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button
                variant={current ? 'secondary' : 'ghost'}
                size="icon-sm"
                className="rounded-s-none"
                aria-label={`Page ${index + 1} actions`}
              >
                <EllipsisIcon />
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>{`Page ${index + 1} actions`}</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="start" {...menuTip.content}>
          <DropdownMenuItem
            onSelect={() => {
              store.setPage(page.id)
              window.setTimeout(() => document.getElementById('page-title')?.focus(), 50)
            }}
          >
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => store.select({ type: 'page', pageId: page.id })}>Page settings</DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => {
              let id = ''
              store.edit((f) => {
                const out = duplicatePage(f, index)
                id = out.id
                return out.form
              })
              store.setPage(id)
            }}
          >
            Duplicate
          </DropdownMenuItem>
          <DropdownMenuItem disabled={index === 0} onSelect={() => store.edit((f) => movePage(f, index, index - 1))}>
            Move left
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={index === form.pages.length - 1}
            onSelect={() => store.edit((f) => movePage(f, index, index + 1))}
          >
            Move right
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant="destructive"
            disabled={form.pages.length <= 1}
            onSelect={() => store.setConfirm({ kind: 'page', pageIndex: index })}
          >
            Delete page
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

/** Whether the chips overflow and are not scrolled to the end yet. */
function useMoreAtEnd(count: number) {
  const ref = useRef<HTMLDivElement>(null)
  const [more, setMore] = useState(false)
  useEffect(() => {
    const viewport = ref.current?.querySelector<HTMLElement>('[data-slot=scroll-area-viewport]')
    if (!viewport) return
    const update = () => setMore(viewport.scrollWidth - Math.abs(viewport.scrollLeft) - viewport.clientWidth > 1)
    update()
    viewport.addEventListener('scroll', update, { passive: true })
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update)
    observer?.observe(viewport)
    if (viewport.firstElementChild) observer?.observe(viewport.firstElementChild)
    return () => {
      viewport.removeEventListener('scroll', update)
      observer?.disconnect()
    }
  }, [count])
  return { ref, more }
}

export function PageStrip() {
  const store = useStore()
  const count = useBuilder((s) => s.schema.pages.length)
  const { ref, more } = useMoreAtEnd(count)
  // "Add page" sits outside the scrolling chips so it never ends up clipped at the sheet edge.
  // When chips overflow (phones), the scrollbar stays visible and the end fades out, so a cut
  // chip reads as "scroll for more" rather than a stray mark (REVIEW P2-10).
  return (
    <div className="flex w-full items-start gap-1">
      <div className="relative min-w-0">
        <ScrollArea ref={ref} type="auto" className="min-w-0 [&>[data-slot=scroll-area-scrollbar][data-orientation=vertical]]:hidden [&>[data-slot=scroll-area-viewport]]:overflow-y-hidden!" data-scroll-x>
          <nav aria-label="Pages" className="flex w-max items-center gap-1 pb-3">
            {Array.from({ length: count }, (_, i) => (
              <Chip key={i} index={i} />
            ))}
          </nav>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
        {more && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-y-0 end-0 mb-3 w-16 bg-linear-to-l from-background from-35% to-transparent rtl:bg-linear-to-r"
          />
        )}
      </div>
      <Button
        variant="ghost"
        size="sm"
        className="shrink-0"
        onClick={() => {
          let id = ''
          store.edit((f) => {
            const out = addPage(f)
            id = out.id
            return out.form
          })
          store.setPage(id)
        }}
      >
        <PlusIcon />
        Add page
      </Button>
    </div>
  )
}
