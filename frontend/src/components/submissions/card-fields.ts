/** Which answers a submission card shows (SUBMISSIONS-VIEWER-SCREENS 2.3). */
import type { FieldElement } from '@/schema'

export const MAX_CARD_FIELDS = 6
const AUTO_COUNT = 4
const NEVER = new Set(['long_text', 'file', 'signature', 'hidden'])

/**
 * The automatic choice: the first short text (one that says "name" first), the first email,
 * phone, and single choice / yes-no; then the next short questions up to four, in form order.
 */
export function autoCardFields(fields: FieldElement[]): string[] {
  const usable = fields.filter((f) => !NEVER.has(f.type))
  const texts = usable.filter((f) => f.type === 'short_text')
  const candidates: (FieldElement | undefined)[] = [
    texts.find((f) => /name|ނަން/i.test(`${f.label} ${f.id}`)) ?? texts[0],
    usable.find((f) => f.type === 'email'),
    usable.find((f) => f.type === 'phone'),
    usable.find((f) => f.type === 'single_choice' || f.type === 'yes_no'),
  ]
  const picks = candidates.filter((f): f is FieldElement => f !== undefined)
  for (const f of usable) {
    if (picks.length >= AUTO_COUNT) break
    if (!picks.includes(f)) picks.push(f)
  }
  const ids = new Set(picks.map((f) => f.id))
  return usable.filter((f) => ids.has(f.id)).map((f) => f.id)
}

/** The fields a card shows: the saved choice (questions still on the form), else automatic. */
export function cardFields(fields: FieldElement[], saved: string[] | null | undefined): FieldElement[] {
  const byId = new Map(fields.map((f) => [f.id, f]))
  const chosen = (saved ?? []).map((id) => byId.get(id)).filter((f): f is FieldElement => !!f)
  if (chosen.length) return chosen.slice(0, MAX_CARD_FIELDS)
  const auto = new Set(autoCardFields(fields))
  return fields.filter((f) => auto.has(f.id))
}

/** How many files and whether a signature came with the submission (top-level questions). */
export function attachments(fields: FieldElement[], data: Record<string, unknown>) {
  let files = 0
  let signed = false
  for (const f of fields) {
    const v = data[f.id]
    if (f.type === 'file' && Array.isArray(v)) files += v.length
    if (f.type === 'signature' && v !== undefined && v !== null && v !== '') signed = true
  }
  return { files, signed }
}
