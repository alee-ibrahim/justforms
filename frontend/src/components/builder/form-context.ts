import { createContext, useContext } from 'react'

import type { FormSummary } from '@/lib/api'

export const FormContext = createContext<FormSummary | null>(null)

/** The form being edited (summary: slug, status, role, current version). */
export function useFormSummary(): FormSummary {
  const form = useContext(FormContext)
  if (!form) throw new Error('useFormSummary outside FormLayout')
  return form
}
