/** Table or cards (SUBMISSIONS-VIEWER-SCREENS 2.1), remembered per user per form. */
import { useCallback, useState } from 'react'

export type SubmissionsView = 'table' | 'cards'

function read(key: string): SubmissionsView {
  try {
    return window.localStorage.getItem(key) === 'cards' ? 'cards' : 'table'
  } catch {
    return 'table'
  }
}

export function useSubmissionsView(userId: string | undefined, formId: string) {
  const key = `justforms:submissions-view:${userId ?? 'me'}:${formId}`
  const [state, setState] = useState(() => ({ key, view: read(key) }))
  // The key changes once the signed-in person loads: read their choice then.
  const view = state.key === key ? state.view : read(key)
  const save = useCallback(
    (next: SubmissionsView) => {
      setState({ key, view: next })
      try {
        if (next === 'cards') window.localStorage.setItem(key, next)
        else window.localStorage.removeItem(key)
      } catch {
        // storage blocked: the choice lasts for this page only
      }
    },
    [key],
  )
  return [view, save] as const
}
