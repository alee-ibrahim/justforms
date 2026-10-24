import { useRef, useState } from 'react'

/**
 * A Tooltip on a menu or popover trigger. When the menu closes, focus returns to the trigger
 * and a plain Tooltip would open again and cover the header (REVIEW P3-4). This keeps the
 * tooltip closed for that one focus return; hovering or tabbing to the trigger later still
 * shows it. Spread `tooltip` on `<Tooltip>` and `content` on the menu's or popover's content.
 */
export function useMenuTooltip() {
  const [open, setOpen] = useState(false)
  const suppress = useRef(false)
  return {
    tooltip: {
      open,
      onOpenChange: (next: boolean) => {
        if (next && suppress.current) return
        setOpen(next)
      },
    },
    content: {
      onCloseAutoFocus: () => {
        // Radix focuses the trigger right after this event, in the same task.
        suppress.current = true
        setOpen(false)
        window.setTimeout(() => {
          suppress.current = false
        }, 0)
      },
    },
  }
}
