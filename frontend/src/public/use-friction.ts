import { useCallback, useEffect, useRef } from 'react'

import type { LiveForm } from './api'
import type { FrictionEvent, FrictionReporter } from './friction'

/**
 * The live form's friction reporter (undefined when the owner turned it off). The reporter is a
 * lazy chunk, so it stays out of the first load; events before it arrives are kept and sent.
 */
export function useFriction(slug: string, form: LiveForm | null): ((event: FrictionEvent) => void) | undefined {
  const reporter = useRef<FrictionReporter | null>(null)
  const pending = useRef<FrictionEvent[]>([])
  const on = !!form?.friction && !!form.schema
  const formId = form?.formId
  const versionId = form?.versionId
  useEffect(() => {
    if (!on || !formId || !versionId) return
    let stopped = false
    let current: FrictionReporter | null = null
    void import('./friction')
      .then(({ createFrictionReporter }) => {
        if (stopped) return
        current = createFrictionReporter({ slug, formId, versionId })
        reporter.current = current
        for (const event of pending.current.splice(0)) current.report(event)
      })
      .catch(() => undefined)
    return () => {
      stopped = true
      current?.stop()
      reporter.current = null
    }
  }, [on, slug, formId, versionId])
  const report = useCallback((event: FrictionEvent) => {
    if (reporter.current) reporter.current.report(event)
    else if (pending.current.length < 100) pending.current.push(event)
  }, [])
  return on ? report : undefined
}
