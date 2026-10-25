import { type RefObject, useLayoutEffect } from 'react'

/**
 * Publishes an element's rendered height as a CSS variable on <html> (STUDIO-HEADER 3).
 * The studio's sticky bars use it: the form bar sticks under the app header
 * (`--app-bar-h`), side panels stick under both (`--studio-top`), and the page's
 * scroll-padding-top keeps focused controls out from under them. A hidden element
 * (display: none) reports 0. The variable is removed when the element unmounts.
 */
export function useHeightVar(ref: RefObject<HTMLElement | null>, name: `--${string}`) {
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const root = document.documentElement.style
    const set = () => root.setProperty(name, `${el.getBoundingClientRect().height}px`)
    set()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(set)
    observer?.observe(el)
    return () => {
      observer?.disconnect()
      root.removeProperty(name)
    }
  }, [ref, name])
}
