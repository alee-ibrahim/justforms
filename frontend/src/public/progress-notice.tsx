/** The restored-progress notice (docs/ux/SAVED-PROGRESS-SCREENS.md 2), part of the `autosave` chunk. */
import { InfoIcon, XIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Alert, AlertAction, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { En } from '@/renderer/msg'

import { restoredText, type Restored } from './autosave'

/**
 * The notice under the form title. A polite live region filled one frame after the form renders,
 * so it is announced without taking focus. Start over confirms inline: a modal could open out of
 * view in an embedded form whose frame is as tall as the form.
 */
export function ProgressNotice({
  restored,
  cleared,
  onStartOver,
  onDismiss,
}: {
  restored: Restored | null
  cleared: boolean
  onStartOver: () => void
  onDismiss: () => void
}) {
  const [shown, setShown] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const keepRef = useRef<HTMLButtonElement>(null)
  const clearedRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const id = window.requestAnimationFrame(() => setShown(true))
    return () => window.cancelAnimationFrame(id)
  }, [])
  useEffect(() => {
    if (confirm) keepRef.current?.focus()
  }, [confirm])
  useEffect(() => {
    if (cleared && shown) clearedRef.current?.focus()
  }, [cleared, shown])

  const dismiss = (
    <AlertAction className="top-1 end-1">
      <Button type="button" variant="ghost" size="icon" className="size-11" aria-label="Dismiss" onClick={onDismiss}>
        <XIcon />
      </Button>
    </AlertAction>
  )
  let content = null
  if (cleared)
    content = (
      <Alert ref={clearedRef} tabIndex={-1} role={undefined} className="min-h-13 items-center pe-14 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
        <InfoIcon />
        <AlertDescription className="text-base text-foreground">
          <En>Your saved answers were cleared.</En>
        </AlertDescription>
        {dismiss}
      </Alert>
    )
  else if (restored)
    content = (
      <Alert role={undefined}>
        <InfoIcon />
        <AlertDescription className="flex flex-col gap-3 text-base text-foreground">
          {confirm ? (
            <>
              <div>
                <En>Clear your saved answers and start from the beginning?</En>
              </div>
              <div className="flex flex-wrap gap-2" lang="en">
                <Button type="button" variant="destructive" className="h-11 px-4 text-base" onClick={onStartOver}>
                  Clear answers
                </Button>
                <Button ref={keepRef} type="button" variant="outline" className="h-11 px-4 text-base" onClick={() => setConfirm(false)}>
                  Keep my answers
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-col gap-1">
                {restoredText(restored).map((t) => (
                  <span key={t}>
                    <En>{t}</En>
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap gap-2" lang="en">
                <Button type="button" variant="outline" className="h-11 px-4 text-base" onClick={() => setConfirm(true)}>
                  Start over
                </Button>
                <Button type="button" variant="ghost" className="h-11 px-4 text-base" onClick={onDismiss}>
                  Dismiss
                </Button>
              </div>
            </>
          )}
        </AlertDescription>
      </Alert>
    )
  return <div aria-live="polite">{shown && content}</div>
}
