/** Helpers for the member suggestions (PEOPLE-SCREENS 6.2). Kept free of React for tests. */
import type { FormRole, MemberMatch } from '@/lib/api'
import { FORM_ROLE_LABELS } from '@/lib/labels'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** Suggestions start at two characters (the server's minimum). */
export const MIN_QUERY = 2

export function isEmail(text: string): boolean {
  return EMAIL.test(text.trim())
}

/** The address as the server stores it: trimmed, lower case, without <angle brackets>. */
export function cleanEmail(text: string): string {
  return text.trim().replace(/^<|>$/g, '').toLowerCase()
}

/** "Already has access (Editor)" for someone with a role on the form; organisation admins
 * are owners of every form. */
export function accessNote(m: Pick<MemberMatch, 'role' | 'formRole'>): string | null {
  if (!m.formRole) return null
  if (m.role === 'admin' && m.formRole === 'owner') return 'Already has access (Owner, organisation admin)'
  return `Already has access (${FORM_ROLE_LABELS[m.formRole as FormRole]})`
}

/** Typed or pasted text in a chips field: complete addresses (followed by a comma, semicolon,
 * space or new line) become chips; the unfinished rest stays in the input. */
export function splitTyped(text: string): { done: string[]; rest: string } {
  const parts = text.split(/[\s,;]+/)
  const rest = /[\s,;]$/.test(text) ? '' : (parts.pop() ?? '')
  return { done: parts.map(cleanEmail).filter(Boolean), rest }
}

/** Adds addresses to a chip list, once each, in order. */
export function addChips(chips: string[], more: string[]): string[] {
  const out = [...chips]
  for (const e of more) if (e && !out.includes(e)) out.push(e)
  return out
}
