/** Which questions and pages a submission's respondent saw, from the form's logic. */
import { useMemo } from 'react'

import { evaluate, type Evaluation } from '@/logic/engine'
import type { Element, Form } from '@/schema'

type Data = Record<string, unknown>
type Scope = { repeater: string; row: number }

export const isEmptyAnswer = (value: unknown) =>
  value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length)

function safeEvaluate(form: Form, data: Data): Evaluation | null {
  try {
    return evaluate(form, data)
  } catch {
    return null // a rule loop in an old version: show every question
  }
}

/** True when any field in the elements (nested in sections) has an answer. */
export function hasAnswers(elements: Element[], data: Data): boolean {
  return elements.some((el) =>
    el.kind === 'section' ? hasAnswers(el.elements ?? [], data) : el.kind !== 'content' && !isEmptyAnswer(data[el.id]),
  )
}

/** Questions on reached pages that logic hid (what "Show skipped questions" adds). */
function countSkipped(form: Form, ev: Evaluation): number {
  let n = 0
  const walk = (els: Element[]) => {
    for (const el of els) {
      if (ev.hidden.includes(el.id)) {
        if (el.kind === 'repeater' || (el.kind === 'field' && el.type !== 'hidden')) n++
      } else if (el.kind === 'section') walk(el.elements ?? [])
    }
  }
  for (const page of form.pages) if (ev.path.includes(page.id)) walk(page.elements ?? [])
  return n
}

/** What the form's logic hid for these answers: questions (also per repeater row) and pages. */
export function useLogic(form: Form, data: Data) {
  return useMemo(() => {
    const ev = safeEvaluate(form, data)
    const hidden = new Set(ev?.hidden ?? [])
    const isVisible = (id: string, scope?: Scope) => {
      if (!ev) return true
      if (scope) return !(ev.rows[scope.repeater]?.[scope.row]?.hidden.includes(id) ?? false)
      return !hidden.has(id)
    }
    const skippedPages = new Set(ev ? form.pages.map((p) => p.id).filter((id) => !ev.path.includes(id)) : [])
    return { isVisible, skippedPages, skippedCount: ev ? countSkipped(form, ev) : 0 }
  }, [form, data])
}
