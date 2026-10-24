/** Which questions the submissions table shows (PHASE-3-SCREENS 5), saved per user per form. */
import { useCallback, useState } from 'react'

import type { FieldElement } from '@/schema'

/** Column id of the confirmed respondent address (not a question). */
export const RESPONDENT_COLUMN = '@respondent'

/** The first three questions that read well in a table. */
export function defaultColumns(fields: FieldElement[]): string[] {
  return fields
    .filter((f) => !['file', 'signature', 'long_text'].includes(f.type))
    .slice(0, 3)
    .map((f) => f.id)
}

function read(key: string): string[] | null {
  try {
    const raw = window.localStorage.getItem(key)
    const parsed: unknown = raw ? JSON.parse(raw) : null
    return Array.isArray(parsed) && parsed.every((x) => typeof x === 'string') ? parsed : null
  } catch {
    return null
  }
}

export function useColumns(
  userId: string | undefined,
  formId: string,
  fields: FieldElement[],
  /** Show the respondent email by default (email-code and staff-only forms). */
  respondentByDefault = false,
) {
  const key = `justforms:columns:${userId ?? 'me'}:${formId}`
  const [chosen, setChosen] = useState<string[] | null>(() => read(key))
  const save = useCallback(
    (next: string[] | null) => {
      setChosen(next)
      try {
        if (next) window.localStorage.setItem(key, JSON.stringify(next))
        else window.localStorage.removeItem(key)
      } catch {
        // storage full or blocked: the choice lasts for this page only
      }
    },
    [key],
  )
  const ids = chosen ?? [...(respondentByDefault ? [RESPONDENT_COLUMN] : []), ...defaultColumns(fields)]
  // Keep form order; drop questions that no longer exist.
  const columns = fields.filter((f) => ids.includes(f.id))
  return { columns, ids, respondent: ids.includes(RESPONDENT_COLUMN), save }
}

