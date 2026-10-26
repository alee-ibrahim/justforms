/** Shared state of the "Ask your submissions" panel (see ask-context.tsx). */
import { createContext, useContext, useSyncExternalStore } from 'react'

export interface AskControl {
  /** The install has an AI provider and the form has been published. */
  available: boolean
  open: boolean
  setOpen: (open: boolean) => void
  /** Opens the panel and asks `question` (the examples on the Insights page). */
  ask: (question: string) => void
  /** A question waiting for the panel to send it. */
  queued: string | null
  clearQueued: () => void
}

export const AskContext = createContext<AskControl | null>(null)

export function useAsk(): AskControl | null {
  return useContext(AskContext)
}

/** Responses, Insights or one submission (not the import page). */
export function isSubmissionsPath(pathname: string): boolean {
  return /^\/forms\/[^/]+\/submissions(\/(?!import(\/|$))[^/]+)*\/?$/.test(pathname)
}

export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query)
      m.addEventListener('change', cb)
      return () => m.removeEventListener('change', cb)
    },
    () => window.matchMedia(query).matches,
  )
}
