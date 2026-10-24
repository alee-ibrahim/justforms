/**
 * Drag and drop for the builder (dnd-kit core): palette -> canvas, moving blocks between
 * pages, sections and repeaters, and dropping on a page chip. The drop position is shown as a
 * 2px carbon line; invalid targets show nothing and refuse the drop (PHASE-2-SCREENS 2.5).
 */
import {
  type Announcements,
  closestCenter,
  type CollisionDetection,
  DndContext,
  type DragEndEvent,
  type DragMoveEvent,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  pointerWithin,
  TouchSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { type ReactNode, useMemo, useRef, useState } from 'react'

import { Item, ItemMedia, ItemTitle } from '@/components/ui/item'
import { cn } from '@/lib/utils'
import type { Element } from '@/schema'

import { addBlock, quoted } from './actions'
import { blockInfo, blockLabel } from './block-types'
import { type DragSource, type DropData, DndStateContext, type DropTarget, useDropTarget } from './dnd-state'
import { useStore } from './store'
import {
  childrenOf,
  findElement,
  type Location,
  moveElement,
  newElement,
  placementProblem,
} from './tree'

/** Smallest droppable under the pointer (so a question inside a section wins over it). */
const collision: CollisionDetection = (args) => {
  // Keyboard dragging has no pointer: use the nearest droppable to the moved block.
  if (!args.pointerCoordinates) return closestCenter(args).slice(0, 1)
  const hits = pointerWithin(args)
  const chip = hits.find((h) => String(h.id).startsWith('chip:'))
  if (chip) return [chip]
  const area = (id: string | number) => {
    const r = args.droppableRects.get(id)
    return r ? r.width * r.height : Infinity
  }
  return [...hits].sort((a, b) => area(a.id) - area(b.id)).slice(0, 1)
}

/** The dragged block's label, or "Untitled question (Email)" when it has none (never its key). */
function overlayText(el: Element): ReactNode {
  const label = blockLabel(el)
  if (label) return <bdi dir="auto">{label}</bdi>
  const type = blockInfo(el).label
  return el.kind === 'field' || el.kind === 'repeater' ? `Untitled question (${type})` : type
}

function pointerY(event: DragMoveEvent): number | null {
  const e = event.activatorEvent as (MouseEvent & TouchEvent) | null
  const start = e?.touches?.[0]?.clientY ?? (e as MouseEvent | null)?.clientY
  if (typeof start === 'number') return start + event.delta.y
  const r = event.active.rect.current.translated
  return r ? r.top + r.height / 2 : null
}

function sameSlot(a: DropTarget, b: DropTarget): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function BuilderDnd({ children }: { children: ReactNode }) {
  const store = useStore()
  const [target, setTargetState] = useState<DropTarget>(null)
  const [dragging, setDragging] = useState<DragSource | null>(null)
  const chipTimer = useRef<number | undefined>(undefined)
  // Announcements run outside React's render cycle; read the latest target from a ref so the
  // "will move to" message describes the current slot, not the previous one.
  const targetRef = useRef<DropTarget>(null)
  const setTarget = (t: DropTarget) => {
    targetRef.current = t
    setTargetState((prev) => (sameSlot(prev, t) ? prev : t))
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
    useSensor(KeyboardSensor),
  )

  const draggedElement = (src: DragSource | null): Element | null => {
    if (!src) return null
    const form = store.get().schema
    return src.source === 'palette' ? newElement(form, src.type) : (findElement(form, src.id)?.el ?? null)
  }

  /** The slot a drag over `over` would land in; null when it would land where it started. */
  const slotFor = (src: DragSource, over: DropData, overRect: { top: number; height: number }, y: number | null): DropTarget => {
    const form = store.get().schema
    const el = draggedElement(src)
    if (!el) return null
    if (over.kind === 'chip') return { kind: 'page', pageIndex: over.pageIndex }
    let loc: Location
    if (over.kind === 'end') loc = { ...over.container, index: childrenOf(form, over.container).length }
    else {
      const before = y === null || y < overRect.top + overRect.height / 2
      loc = { ...over.loc, index: over.loc.index + (before ? 0 : 1) }
    }
    if (src.source === 'block' && src.id === (over.kind === 'block' ? over.id : null)) return null
    return { kind: 'slot', loc, problem: placementProblem(form, el, loc) }
  }

  const onMove = (event: DragMoveEvent) => {
    const over = event.over?.data.current as DropData | undefined
    const src = event.active.data.current as DragSource
    window.clearTimeout(chipTimer.current)
    if (!over || !event.over) return setTarget(null)
    const t = slotFor(src, over, event.over.rect, pointerY(event))
    setTarget(t)
    if (t?.kind === 'page') {
      // Hold over a chip to switch to that page.
      const id = store.get().schema.pages[t.pageIndex].id
      chipTimer.current = window.setTimeout(() => store.setPage(id), 600)
    }
  }

  const onEnd = (event: DragEndEvent) => {
    window.clearTimeout(chipTimer.current)
    const src = event.active.data.current as DragSource
    const t = target
    setTargetState(null)
    setDragging(null)
    if (!t) return
    const form = store.get().schema
    if (t.kind === 'page') {
      const loc = { pageIndex: t.pageIndex, parentId: null, index: (form.pages[t.pageIndex].elements ?? []).length }
      if (src.source === 'palette') addBlock(store, src.type, loc)
      else store.edit((f) => moveElement(f, src.id, loc), { pageId: form.pages[t.pageIndex].id })
      return
    }
    if (t.problem) return
    if (src.source === 'palette') addBlock(store, src.type, t.loc)
    else
      store.edit((f) => moveElement(f, src.id, t.loc), {
        pageId: form.pages[t.loc.pageIndex].id,
        selection: { type: 'element', id: src.id },
      })
  }

  const labelOf = (src: DragSource | undefined) => {
    if (!src) return 'item'
    if (src.source === 'palette') return blockInfo(src.type).label
    const found = findElement(store.get().schema, src.id)
    return found ? quoted(found.el) : 'item'
  }
  const pageName = (i: number) => {
    const p = store.get().schema.pages[i]
    return p?.title ? `page ${i + 1}, ${p.title}` : `page ${i + 1}`
  }
  /** Where the dragged block ends up: 1-based position and the container's size after the move. */
  const landing = (src: DragSource | undefined, loc: Location) => {
    const form = store.get().schema
    const siblings = childrenOf(form, loc)
    const from = src?.source === 'block' ? findElement(form, src.id)?.loc : undefined
    const same = !!from && from.pageIndex === loc.pageIndex && from.parentId === loc.parentId
    // Moving down within the same list: the block leaves its old slot first.
    const index = same && from.index < loc.index ? loc.index - 1 : loc.index
    return { position: index + 1, total: same ? siblings.length : siblings.length + 1 }
  }
  const announcements: Announcements = {
    onDragStart: ({ active }) =>
      `Picked up ${labelOf(active.data.current as DragSource)}. Use arrow keys to move, Space to drop, Escape to cancel.`,
    onDragOver: ({ active, over }) => {
      // Called before onDragMove has seen the new droppable, so work the slot out here.
      const data = over?.data.current as DropData | undefined
      const r = active.rect.current.translated
      const target =
        over && data ? slotFor(active.data.current as DragSource, data, over.rect, r ? r.top + r.height / 2 : null) : null
      if (!target || target.kind !== 'slot') return undefined
      const src = active.data.current as DragSource
      const { position, total } = landing(src, target.loc)
      return `${labelOf(src)} will move to position ${position} of ${total} on ${pageName(target.loc.pageIndex)}.`
    },
    onDragEnd: ({ active }) => {
      const src = active.data.current as DragSource
      const target = targetRef.current
      if (target?.kind === 'page') return `${labelOf(src)} moved to the end of ${pageName(target.pageIndex)}.`
      if (target?.kind !== 'slot') return `${labelOf(src)} dropped. Nothing moved.`
      if (target.problem) return `${labelOf(src)} can't go there. Nothing moved.`
      return `${labelOf(src)} moved to position ${landing(src, target.loc).position} on ${pageName(target.loc.pageIndex)}.`
    },
    onDragCancel: ({ active }) => {
      const src = active.data.current as DragSource
      const found = src.source === 'block' ? findElement(store.get().schema, src.id) : null
      return `Move cancelled. ${labelOf(src)} is back${found ? ` at position ${found.loc.index + 1}` : ''}.`
    },
  }

  const value = useMemo(() => ({ target, dragging, setTarget }), [target, dragging])
  const overlayEl = dragging ? draggedElement(dragging) : null
  const reduced =
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

  return (
    <DndStateContext.Provider value={value}>
      <DndContext
        sensors={sensors}
        collisionDetection={collision}
        accessibility={{ announcements }}
        onDragStart={(e) => {
          targetRef.current = null
          setDragging(e.active.data.current as DragSource)
        }}
        onDragMove={onMove}
        onDragEnd={onEnd}
        onDragCancel={() => {
          setTargetState(null)
          setDragging(null)
        }}
      >
        {children}
        <DragOverlay dropAnimation={reduced ? null : undefined}>
          {overlayEl && (
            <Item
              variant="outline"
              size="sm"
              className={cn(
                'w-60 bg-popover shadow-float',
                target?.kind === 'slot' && target.problem && 'cursor-not-allowed opacity-70',
              )}
            >
              <ItemMedia variant="icon">
                {(() => {
                  const Icon = blockInfo(overlayEl).icon
                  return <Icon />
                })()}
              </ItemMedia>
              <ItemTitle className="min-w-0">
                <span className="truncate">
                  {dragging?.source === 'palette' ? blockInfo(overlayEl).label : overlayText(overlayEl)}
                </span>
              </ItemTitle>
            </Item>
          )}
        </DragOverlay>
      </DndContext>
    </DndStateContext.Provider>
  )
}

/** The 2px carbon line with end circles, shown where the dragged block will land. */
export function DropLine({ loc }: { loc: Location }) {
  const { target } = useDropTarget()
  const on =
    target?.kind === 'slot' &&
    !target.problem &&
    target.loc.pageIndex === loc.pageIndex &&
    target.loc.parentId === loc.parentId &&
    target.loc.index === loc.index
  if (!on) return null
  return (
    <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-[17px] z-10 flex items-center">
      <span className="size-2 rounded-full border-2 border-primary bg-card" />
      <span className="h-0.5 flex-1 bg-primary" />
      <span className="size-2 rounded-full border-2 border-primary bg-card" />
    </div>
  )
}
