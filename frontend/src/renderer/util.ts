/** Pure helpers shared by the renderer components. */
import type { CSSProperties } from 'react'

import type { Element, FieldElement, FileField, RepeaterElement } from '@/schema'
import { resolveAlign, textDirection, textLang, type TextAlign, type TextDirection } from '@/schema/direction'

import { MSG } from './messages'

const TYPE_NAMES: [test: (a: string) => boolean, name: string][] = [
  [(a) => a === 'application/pdf' || a === '.pdf', 'PDF'],
  [(a) => a === 'image/jpeg' || a === '.jpg' || a === '.jpeg', 'JPG'],
  [(a) => a === 'image/png' || a === '.png', 'PNG'],
  [(a) => a === 'image/*', 'images'],
  [(a) => /word|\.docx?$/.test(a), 'Word'],
  [(a) => /excel|spreadsheet|\.xlsx?$|\.csv$/.test(a), 'Excel'],
]

function typeName(accept: string): string {
  return TYPE_NAMES.find(([t]) => t(accept.toLowerCase()))?.[1] ?? accept.replace(/^\./, '').toUpperCase()
}

/** "PDF, JPG or PNG". */
export function acceptedTypes(field: FileField): string {
  const names = [...new Set((field.accept ?? []).map(typeName))]
  if (!names.length) return MSG.anyFile
  try {
    return new Intl.ListFormat('en-GB', { type: 'disjunction' }).format(names)
  } catch {
    return names.join(', ')
  }
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function widthClass(el: Element): string {
  return el.kind === 'field' && el.width === 'half' ? '@min-[32rem]:col-span-1' : '@min-[32rem]:col-span-2'
}

/**
 * Row title from the builder's English add button text ("Add dependent" -> "Dependent 2"), or
 * null when there is none to derive from (the caller shows the system "Entry 2").
 */
export function rowTitle(el: RepeaterElement, n: number): string | null {
  const add = el.addLabel?.trim()
  if (add) {
    const noun = add.replace(/^add (an? |another )?/i, '')
    if (noun && noun !== add) return `${noun.charAt(0).toUpperCase()}${noun.slice(1)} ${n}`
  }
  return null
}

/** Types whose control is a group of options (labelled by a legend, not a <label for>). */
export function isGroupControl(field: FieldElement): boolean {
  return (
    (field.type === 'single_choice' && field.display !== 'dropdown') ||
    field.type === 'multi_choice' ||
    field.type === 'yes_no' ||
    field.type === 'rating'
  )
}

/**
 * A group (radio cards, checkboxes) is checked when focus leaves the group, not when focus enters
 * it or moves between its options: no error before the respondent has had a chance to answer.
 */
export function leaveGroup(blur: () => void) {
  return (e: { currentTarget: HTMLElement; relatedTarget: EventTarget | null }) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) blur()
  }
}

/** Starts loading the lazy controls a form uses, so they are ready when their page shows. */
export function prefetchControls(types: Set<string>): void {
  if (types.has('rating')) void import('./rating')
  if (types.has('phone')) void import('./phone')
  if (types.has('multi_choice')) void import('./multi-choice')
  if (types.has('file')) void import('./file-upload')
  if (types.has('signature')) void import('./signature-pad')
}

/**
 * Answers with every top-level repeater padded to `minRows` empty rows: the rows the renderer
 * shows before anything is typed. The rule engine then marks their required questions, so Next
 * checks them the way the server does (`pad_repeaters` in backend/app/validation/answers.py).
 */
export function padToMinRows<A extends Record<string, unknown>>(
  elements: Iterable<{ element: Element; repeaterId: string | null }>,
  answers: A,
): A {
  let out: Record<string, unknown> | null = null
  for (const { element: el, repeaterId } of elements) {
    if (el.kind !== 'repeater' || repeaterId !== null || !el.minRows) continue
    const rows = answers[el.id]
    if (rows !== undefined && rows !== null && !Array.isArray(rows)) continue
    const have = Array.isArray(rows) ? rows : []
    if (have.length >= el.minRows) continue
    out ??= { ...answers }
    out[el.id] = [...have, ...Array.from({ length: el.minRows - have.length }, () => ({}))]
  }
  return (out ?? answers) as A
}

/** The text an element is read by: its label, title or text (its direction is the block's). */
export function elementText(el: Element): string {
  switch (el.kind) {
    case 'field':
    case 'repeater':
      return el.label ?? ''
    case 'section':
      return el.title || el.description || ''
    case 'content':
      return el.text ?? ''
  }
}

export interface Placement {
  /** The block's own direction and language (from its text). */
  dir: TextDirection
  lang: 'dv' | 'en'
  /** Text alignment. Physical for left/right so nested runs in the other direction keep it;
   * `start` for auto, so each nested paragraph starts at its own edge. */
  text: CSSProperties
  /** For width-capped blocks (help text, paragraphs): also moves the box to that side. */
  block: CSSProperties
}

/**
 * Where a block of form text sits: its direction from its own text (falling back to the
 * sheet's), aligned by the element's `align`, else the form default (`settings.align`).
 */
export function placement(
  text: string | null | undefined,
  align: TextAlign | null | undefined,
  formAlign: TextAlign | null | undefined,
  fallback: TextDirection = 'ltr',
): Placement {
  const dir = textDirection(text, fallback)
  const explicit = [align, formAlign].find((a) => a !== undefined && a !== null)
  const side = resolveAlign(align, formAlign, dir)
  const auto = explicit === undefined || explicit === 'auto'
  const text_: CSSProperties = { textAlign: auto ? 'start' : side }
  const block: CSSProperties =
    side === 'center'
      ? { ...text_, marginInline: 'auto' }
      : auto
        ? text_
        : { ...text_, [side === 'left' ? 'marginRight' : 'marginLeft']: 'auto' }
  return { dir, lang: textLang(text), text: text_, block }
}
