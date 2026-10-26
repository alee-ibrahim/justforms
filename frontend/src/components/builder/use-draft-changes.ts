import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import type { FormSummary } from '@/lib/api'
import { draftChangesQuery } from '@/lib/queries'

import { useBuilder, useStore } from './store'

/** The changes of the saved draft; saves pending edits first so the list is current. */
export function useDraftChanges(form: FormSummary, enabled: boolean) {
  const store = useStore()
  const revision = useBuilder((s) => s.saved.revision)
  const saved = useBuilder((s) => s.status === 'saved' && s.schema === s.saved.schema)
  useEffect(() => {
    if (enabled) void store.flush()
  }, [enabled, store])
  return useQuery({
    ...draftChangesQuery(form.id, revision, form.currentVersion),
    enabled: enabled && saved && form.currentVersion !== null,
  })
}
