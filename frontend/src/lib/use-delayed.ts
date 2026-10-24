import { useEffect, useState } from 'react'

/** True once `active` has stayed true for `ms` (skeletons appear only after 300ms). */
export function useDelayed(active: boolean, ms = 300): boolean {
  const [shown, setShown] = useState(false)
  useEffect(() => {
    if (!active) return
    const t = window.setTimeout(() => setShown(true), ms)
    return () => {
      window.clearTimeout(t)
      setShown(false)
    }
  }, [active, ms])
  return active && shown
}
