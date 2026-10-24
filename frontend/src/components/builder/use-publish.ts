import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { toast } from 'sonner'

import { api, ApiError, type FormSummary, type PublishIssue } from '@/lib/api'

import { approvalChecks, useApprovalConfig } from './approval-problems'
import { formProblems } from './problems'
import { useStore } from './store'

export function usePublish(form: FormSummary) {
  const store = useStore()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const approvals = useApprovalConfig(form.id)
  const mutation = useMutation({
    mutationFn: async () => {
      await store.flush()
      if (store.get().status !== 'saved') throw new Error('Unsaved changes')
      return api.publish(form.id)
    },
    onSuccess: async (version) => {
      store.setPublishing(false)
      await queryClient.invalidateQueries({ queryKey: ['form', form.id] })
      void queryClient.invalidateQueries({ queryKey: ['versions', form.id] })
      void queryClient.invalidateQueries({ queryKey: ['forms'] })
      toast.success(`Published version ${version.version}`, {
        action: { label: 'Share', onClick: () => void navigate({ to: '/forms/$formId/share', params: { formId: form.id } }) },
      })
      if (version.version === 1) await navigate({ to: '/forms/$formId/share', params: { formId: form.id } })
    },
    onError: (err) => {
      const issues = err instanceof ApiError ? (err.body as { issues?: PublishIssue[] } | null)?.issues : undefined
      const message = issues?.length ? issues.map((i) => i.message).join('; ') : err.message
      toast.error(`Couldn't publish. ${message}`, { action: { label: 'Retry', onClick: () => mutation.mutate() } })
    },
  })
  /** Start publishing: problems first, a confirmation on the first publish, else publish now. */
  const start = () => {
    const schema = store.get().schema
    const checks = approvalChecks(approvals, schema)
    const attention = formProblems(schema).length + checks.errors.length + checks.warnings.length
    if (attention || form.currentVersion === null) store.setPublishing(true)
    else mutation.mutate()
  }
  return { start, mutation }
}

export type PublishMutation = ReturnType<typeof usePublish>['mutation']
