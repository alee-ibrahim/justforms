/** Helpers for Insights › Where people get stuck (friction-card.tsx). */
import type { Form } from '@/schema'

import type { Friction } from './api'

/** Plain names for problem codes (renderer/validation.ts and the server's). */
export function problemKind(code: string): string {
  switch (code) {
    case 'required':
    case 'choose_at_least':
      return 'Left empty'
    case 'pattern':
      return 'Wrong format'
    case 'too_long':
      return 'Too long'
    case 'email':
      return 'Email not valid'
    case 'phone':
    case 'phone_mv':
      return 'Phone not valid'
    case 'number':
    case 'integer':
      return 'Not a number'
    case 'between':
    case 'at_least':
    case 'at_most':
      return 'Out of range'
    case 'date':
    case 'time':
      return 'Date or time not valid'
    case 'date_from':
    case 'date_to':
      return 'Date out of range'
    case 'choose_at_most':
      return 'Too many chosen'
    case 'too_many_files':
    case 'file_type':
    case 'file_too_large':
    case 'file_missing':
    case 'file_invalid':
      return 'File problem'
    case 'signature_invalid':
    case 'signature_small':
      return 'Signature problem'
    default:
      return 'Not accepted'
  }
}

/** Codes merged under their plain names, most first. */
export function kinds(codes: Record<string, number>): { kind: string; count: number }[] {
  const out = new Map<string, number>()
  for (const [code, n] of Object.entries(codes)) out.set(problemKind(code), (out.get(problemKind(code)) ?? 0) + n)
  return [...out].map(([kind, count]) => ({ kind, count })).sort((a, b) => b.count - a.count || a.kind.localeCompare(b.kind))
}

export interface Step {
  key: string
  label: string
  count: number
}

/** Opened, started, each later page in form order, submitted. */
export function funnel(data: Friction, schema: Form | undefined): Step[] {
  const visits = new Map(data.pages.map((p) => [p.page, p.visits]))
  const pages = schema?.pages ?? []
  const first = pages[0]?.id
  const opened = first ? (visits.get(first) ?? 0) : Math.max(0, ...data.pages.map((p) => p.visits))
  const steps: Step[] = [
    { key: 'opened', label: 'Opened the form', count: opened },
    { key: 'started', label: 'Started answering', count: data.started },
  ]
  pages.slice(1).forEach((p, i) => {
    steps.push({ key: `page-${p.id}`, label: p.title?.trim() || `Page ${i + 2}`, count: visits.get(p.id) ?? 0 })
  })
  steps.push({ key: 'submitted', label: 'Submitted', count: data.submitted })
  return steps
}
