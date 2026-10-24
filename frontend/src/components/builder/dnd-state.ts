/** Drag-and-drop state shared by the canvas, page strip and palette. */
import { useDraggable, useDroppable } from '@dnd-kit/core'
import { createContext, useContext } from 'react'

import type { BlockType, Container, Location } from './tree'

export type DragSource = { source: 'palette'; type: BlockType } | { source: 'block'; id: string }
export type DropData =
  | { kind: 'block'; id: string; loc: Location }
  | { kind: 'end'; container: Container }
  | { kind: 'chip'; pageIndex: number }

export type DropTarget =
  | { kind: 'slot'; loc: Location; problem: string | null }
  | { kind: 'page'; pageIndex: number }
  | null

interface DndState {
  target: DropTarget
  dragging: DragSource | null
  setTarget: (t: DropTarget) => void
}

export const DndStateContext = createContext<DndState>({ target: null, dragging: null, setTarget: () => {} })

export function useDropTarget(): DndState {
  return useContext(DndStateContext)
}

export function useBlockDrag(id: string) {
  return useDraggable({ id: `block:${id}`, data: { source: 'block', id } satisfies DragSource })
}

export function usePaletteDrag(type: BlockType, disabled = false) {
  return useDraggable({ id: `palette:${type}`, data: { source: 'palette', type } satisfies DragSource, disabled })
}

export function useBlockDrop(id: string, loc: Location) {
  return useDroppable({ id: `block:${id}`, data: { kind: 'block', id, loc } satisfies DropData })
}

export function useEndDrop(container: Container) {
  return useDroppable({
    id: `end:${container.pageIndex}:${container.parentId ?? ''}`,
    data: { kind: 'end', container } satisfies DropData,
  })
}

export function useChipDrop(pageIndex: number) {
  return useDroppable({ id: `chip:${pageIndex}`, data: { kind: 'chip', pageIndex } satisfies DropData })
}
