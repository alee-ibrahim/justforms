/**
 * Approval checks at publish (APPROVALS-SCREENS 2), twin of check_config in
 * backend/app/approvals/config.py: a step whose approver comes from a question that is gone or
 * isn't an email question blocks publishing; an optional or conditionally shown question is a
 * warning. The server repeats the blocking checks.
 */
import { useQuery } from '@tanstack/react-query'

import { api, type ApprovalConfig } from '@/lib/api'
import { buildIndex, type FormIndex } from '@/logic/form-index'
import type { Form } from '@/schema'

export interface ApprovalChecks {
  errors: string[]
  warnings: string[]
}

/** Shown to every respondent: no show-if on it, its sections or page, and no jump past its page. */
function alwaysOnPath(form: Form, index: FormIndex, id: string): boolean {
  let node: string | null = id
  while (node !== null) {
    const info = index.elements.get(node)
    if (!info) return false
    if ('visibleIf' in info.element && info.element.visibleIf) return false
    node = info.parentId
  }
  const pageI = index.elements.get(id)!.pageIndex
  if (form.pages[pageI].visibleIf) return false
  for (let i = 0; i < pageI; i++)
    for (const rule of form.pages[i].next ?? []) {
      const target = rule.goto === 'submit' ? form.pages.length : (index.pageIndex.get(rule.goto) ?? -1)
      if (target > pageI) return false
    }
  return true
}

export function approvalChecks(config: ApprovalConfig | undefined, form: Form): ApprovalChecks {
  const out: ApprovalChecks = { errors: [], warnings: [] }
  if (!config?.enabled) return out
  const index = buildIndex(form)
  config.steps.forEach((step, i) => {
    const n = i + 1
    if (step.source !== 'field' || !step.fieldId) return
    const info = index.elements.get(step.fieldId)
    if (!info) return out.errors.push(`Approval step ${n} uses a question that isn't in the form`)
    if (info.element.kind !== 'field' || info.element.type !== 'email' || info.repeaterId !== null)
      return out.errors.push(`Approval step ${n} uses a question that isn't an email question`)
    if (!info.element.required) out.warnings.push(`Approval step ${n} uses an optional question`)
    else if (!alwaysOnPath(form, index, step.fieldId))
      out.warnings.push(`Approval step ${n} uses a question only some respondents see`)
  })
  return out
}

/** The form's saved approval settings (for the publish checks). */
export function useApprovalConfig(formId: string): ApprovalConfig | undefined {
  const q = useQuery({ queryKey: ['approvals', formId], queryFn: () => api.getApprovals(formId), staleTime: 30_000 })
  return q.data?.config
}
