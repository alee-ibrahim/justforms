/**
 * Wires saved progress (the lazy `./autosave` chunk) into a public form page: the answers and
 * page to start from, the save callback, the restored notice and Start over.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'

import type { LiveForm } from './api'
import type { Progress } from './autosave'
import { prefill } from './helpers'

export type AutosaveLib = typeof import('./autosave')

export function useAutosave(lib: AutosaveLib | null, live: LiveForm | null) {
  const [run, setRun] = useState(0)
  const [cleared, setCleared] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const schema = live?.schema ?? null
  // Opened once per form and respondent; a republish while open only updates the version.
  const id = lib && live && schema ? `${live.formId}:${live.respondentEmail ?? ''}` : null
  const [opened, setOpened] = useState<{ id: string | null; progress: Progress | null }>({ id: null, progress: null })
  if (opened.id !== id) setOpened({ id, progress: lib && live ? lib.openProgress(live) : null })
  const progress = opened.id === id ? opened.progress : null
  useEffect(() => {
    if (live?.schema) progress?.update(live)
  }, [progress, live])

  const initial = useMemo(() => {
    if (!schema) return {}
    // Start over begins from the link's prefilled answers only.
    const restored = run === 0 ? progress?.restored?.answers : undefined
    return { ...restored, ...prefill(schema) }
  }, [schema, progress, run])

  const restored = run === 0 && !dismissed ? (progress?.restored ?? null) : null
  const notice: ReactNode =
    lib && (restored || (cleared && !dismissed)) ? (
      <lib.ProgressNotice
        restored={restored}
        cleared={cleared}
        onDismiss={() => setDismissed(true)}
        onStartOver={() => {
          progress?.clear()
          setCleared(true)
          setDismissed(false)
          setRun((n) => n + 1)
        }}
      />
    ) : null

  return {
    /** Remounts the form on Start over. */
    key: run,
    initialAnswers: initial,
    initialPage: run === 0 ? progress?.restored?.page : undefined,
    onProgress: progress ? progress.save : undefined,
    onSubmitted: () => progress?.clear(),
    notice,
  }
}
