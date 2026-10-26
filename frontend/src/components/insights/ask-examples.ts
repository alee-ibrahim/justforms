/**
 * "Try asking" questions for "Ask your submissions" (INSIGHTS-SCREENS 4), built from the
 * published form: its choice questions first ("How many ticked …?", "Who ticked …?",
 * "Breakdown by …"), then a number's average and submissions per month.
 */
import { buildIndex } from '@/logic/form-index'
import type { FieldElement, Form } from '@/schema'

const LONG = 48

function short(text: string): string {
  const t = text.trim().replace(/\s+/g, ' ')
  if (t.length <= LONG) return t
  const cut = t.slice(0, LONG - 1)
  const space = cut.lastIndexOf(' ')
  return `${(space > LONG / 2 ? cut.slice(0, space) : cut).replace(/[\s,.;:]+$/, '')}…`
}

function optionsOf(f: FieldElement): { value: string; label: string }[] {
  const opts = (f as { options?: { value: string; label: string }[] }).options
  return Array.isArray(opts) ? opts.filter((o) => o.label?.trim()) : []
}

/** Top-level questions of the form, in order (not inside repeaters, not hidden). */
export function formFields(schema: Form | undefined): FieldElement[] {
  if (!schema) return []
  return [...buildIndex(schema).elements.values()]
    .filter((i) => i.repeaterId === null && i.kind === 'field')
    .map((i) => i.element as FieldElement)
    .filter((f) => f.type !== 'hidden')
}

export function askExamples(schema: Form | undefined, readAnswers = false, max = 4): string[] {
  const fields = formFields(schema)
  const out: string[] = []
  const multi = fields.find((f) => f.type === 'multi_choice' && optionsOf(f).length)
  const single = fields.find((f) => f.type === 'single_choice' && optionsOf(f).length)
  const choice = multi ?? single
  const named = fields.some((f) => f.type === 'short_text' && /name|organi[sz]ation/i.test(f.label ?? ''))
  if (multi) out.push(`How many ticked “${short(optionsOf(multi)[0].label)}”?`)
  else if (single) out.push(`How many answered “${short(optionsOf(single)[0].label)}”?`)
  if (choice && named) {
    const opts = optionsOf(choice)
    out.push(`Who ${choice.type === 'multi_choice' ? 'ticked' : 'answered'} “${short(opts[Math.min(1, opts.length - 1)].label)}”?`)
  }
  if (choice?.label) out.push(`Breakdown by “${short(choice.label)}”`)
  const num = fields.find((f) => f.type === 'number' || f.type === 'rating')
  if (num?.label) out.push(`What is the average “${short(num.label)}”?`)
  const text = fields.find((f) => f.type === 'long_text')
  if (readAnswers && text?.label) out.push(`Summarise the answers to “${short(text.label)}”`)
  out.push('How many submissions came in each month?')
  return out.slice(0, max)
}

/** Question keys and labels (top level and inside repeaters), for the answers' tables. */
export function fieldLabels(schema: Form | undefined): Map<string, string> {
  const labels = new Map<string, string>()
  if (!schema) return labels
  for (const i of buildIndex(schema).elements.values())
    if (i.kind === 'field') {
      const f = i.element as FieldElement
      labels.set(f.id, f.label ?? f.id)
    }
  return labels
}
