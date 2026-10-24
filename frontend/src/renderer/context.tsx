import { createContext, useContext } from 'react'

import type { Form, FormLanguage } from '@/schema'

import type { FileRef } from './validation'

/** Where an answer lives: a top-level field, or a field inside one repeater row. */
export interface AnswerPath {
  id: string
  repeater?: string
  row?: number
}

export function pathKey(p: AnswerPath): string {
  return p.repeater !== undefined ? `${p.repeater}.${p.row}.${p.id}` : p.id
}

/** Sends one file somewhere and reports progress. Preview mode keeps files in the browser. */
export type Uploader = (
  file: File,
  fieldId: string,
  onProgress: (fraction: number) => void,
  signal: AbortSignal,
) => Promise<FileRef>

export interface RendererContextValue {
  form: Form
  language: FormLanguage
  /** `canvas`: the builder's inert WYSIWYG view; `fill`: a respondent (or preview) fills it in. */
  mode: 'fill' | 'canvas'
  /** Which questions get a marker: "(optional)" on optional ones, or "(required)". */
  convention: 'optional' | 'required'
  getValue: (p: AnswerPath) => unknown
  setValue: (p: AnswerPath, value: unknown) => void
  blur: (p: AnswerPath) => void
  errorFor: (p: AnswerPath) => string | null
  isVisible: (id: string, row?: { repeater: string; row: number }) => boolean
  isRequired: (id: string, row?: { repeater: string; row: number }) => boolean
  /** Questions to wash with the marker (changed after a version update). */
  highlighted: ReadonlySet<string>
  uploader: Uploader
  setUploading: (key: string, busy: boolean) => void
  rowCount: (repeaterId: string) => number
  addRow: (repeaterId: string) => void
  removeRow: (repeaterId: string, row: number) => void
}

export const RendererContext = createContext<RendererContextValue | null>(null)

export function useRenderer(): RendererContextValue {
  const ctx = useContext(RendererContext)
  if (!ctx) throw new Error('useRenderer outside RendererContext')
  return ctx
}

/** DOM id of the control for an answer (error summary links jump here). */
export function controlId(p: AnswerPath): string {
  return `q-${pathKey(p).replace(/\./g, '-')}`
}
