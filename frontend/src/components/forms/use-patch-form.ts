import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, type FormPatch, type FormSummary } from '@/lib/api'

/** PATCH /forms/{id} and keep the cached summary (and the forms list) in step. */
export function usePatchForm(form: FormSummary) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: FormPatch) => api.patchForm(form.id, body),
    onSuccess: (next) => {
      queryClient.setQueryData(['form', form.id], next)
      void queryClient.invalidateQueries({ queryKey: ['forms'] })
    },
  })
}
