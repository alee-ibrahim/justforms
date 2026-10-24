/** Addresses for the invite dialog (PEOPLE-SCREENS 3.1). */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
export const MAX_INVITES = 20

/** Addresses typed or pasted, split on commas, semicolons, spaces and new lines. */
export function parseEmails(text: string): { valid: string[]; invalid: string[] } {
  const seen = new Set<string>()
  const valid: string[] = []
  const invalid: string[] = []
  for (const raw of text.split(/[\s,;]+/)) {
    const value = raw.trim().replace(/^<|>$/g, '').toLowerCase()
    if (!value || seen.has(value)) continue
    seen.add(value)
    ;(EMAIL.test(value) ? valid : invalid).push(value)
  }
  return { valid, invalid }
}
