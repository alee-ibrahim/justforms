/**
 * The phonetic Thaana keyboard as a React ref (@yashau/thaana's `attachKeyboard`), for boxes
 * that edit form text in the studio. Unlike the package's own hook it leaves `dir` alone:
 * form text follows its first strong character ("Name / ނަން" is left to right), which the
 * components set themselves (`textDirection`), while the package would turn any text holding
 * Thaana right to left.
 */
import { attachKeyboard } from '@yashau/thaana-react'
import { useCallback, useEffect, useRef } from 'react'

export { mergeRefs } from '@yashau/thaana-react'

export function useThaanaKeyboard<T extends HTMLInputElement | HTMLTextAreaElement>({
  enabled,
}: {
  enabled: boolean
}): (el: T | null) => void {
  const on = useRef(enabled)
  useEffect(() => {
    on.current = enabled
  }, [enabled])
  const detach = useRef<(() => void) | null>(null)
  return useCallback((el: T | null) => {
    detach.current?.()
    detach.current = el ? attachKeyboard(el, { enabled: () => on.current, autoDirection: false }) : null
  }, [])
}
