/**
 * Where "Ask your submissions" lives (INSIGHTS-SCREENS 4): one panel for the whole Submissions
 * area (Responses, Insights, a submission), opened from the form bar's "Ask about submissions"
 * or from the Insights page. From 1024px it is docked at the end of the page, under the form
 * bar, like the builder's assistant; below that it is a full-height sheet. The panel itself is
 * loaded lazily (it carries the charts).
 */
import { useQuery } from '@tanstack/react-query'
import { useRouterState } from '@tanstack/react-router'
import { lazy, type ReactNode, Suspense, useMemo, useState } from 'react'

import type { FormSummary } from '@/lib/api'
import { metaQuery } from '@/lib/queries'

import { AskContext, type AskControl, isSubmissionsPath, useAsk, useMedia } from './ask-state'

const AskDock = lazy(() => import('./ask-dock'))

export function AskProvider({ form, children }: { form: FormSummary; children: ReactNode }) {
  const aiOn = !!useQuery(metaQuery).data?.features.ai
  const [open, setOpen] = useState(false)
  const [queued, setQueued] = useState<string | null>(null)
  const available = aiOn && form.currentVersion !== null
  const value = useMemo<AskControl>(
    () => ({
      available,
      open,
      setOpen,
      ask: (question) => {
        setQueued(question)
        setOpen(true)
      },
      queued,
      clearQueued: () => setQueued(null),
    }),
    [available, open, queued],
  )
  return <AskContext.Provider value={value}>{children}</AskContext.Provider>
}

/** The page with the panel beside it (wide screens) or over it (phones). The wrappers stay
 * `display: contents` while the panel is closed, so the page never remounts. */
export function AskArea({ children }: { children: ReactNode }) {
  const ask = useAsk()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const wide = useMedia('(min-width: 1024px)')
  const shown = !!ask?.available && ask.open && isSubmissionsPath(pathname)
  const docked = shown && wide
  return (
    <div className={docked ? 'flex min-w-0 flex-1 items-start' : 'contents'}>
      <div className={docked ? 'flex min-w-0 flex-1 flex-col' : 'contents'}>{children}</div>
      {shown && ask && (
        <Suspense fallback={null}>
          <AskDock docked={wide} onClose={() => ask.setOpen(false)} />
        </Suspense>
      )}
    </div>
  )
}
