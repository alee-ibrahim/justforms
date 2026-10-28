/**
 * Anonymous "where people get stuck" reports (docs/features.md): which pages a visit reached,
 * when it started answering and which validation problem it was shown (question key and
 * problem code, never the value). A random visit id kept in this tab's sessionStorage (memory
 * when storage is blocked) lets the server count each thing once per visit; it is not a cookie
 * and identifies nobody. Reports are batched and sent without credentials; failures are ignored.
 */
export type FrictionEvent =
  | { type: 'start' }
  | { type: 'page'; page: string }
  | { type: 'error'; field: string; code: string }

const FLUSH_MS = 3000
const MAX_BATCH = 50

function newVisitId(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function visitId(formId: string): string {
  const key = `justforms:visit:${formId}`
  try {
    const stored = sessionStorage.getItem(key)
    if (stored && /^[A-Za-z0-9_-]{16,64}$/.test(stored)) return stored
    const id = newVisitId()
    sessionStorage.setItem(key, id)
    return id
  } catch {
    return newVisitId()
  }
}

export interface FrictionReporter {
  report: (event: FrictionEvent) => void
  /** Sends what is queued (also on page hide). */
  flush: () => void
  stop: () => void
}

export function createFrictionReporter(opts: {
  slug: string
  formId: string
  versionId: string
  send?: (url: string, body: string) => void
}): FrictionReporter {
  const url = `/api/v1/public/forms/${encodeURIComponent(opts.slug)}/friction`
  const visit = visitId(opts.formId)
  const seen = new Set<string>()
  let queue: FrictionEvent[] = []
  let timer: ReturnType<typeof setTimeout> | null = null
  const send =
    opts.send ??
    ((target: string, body: string) =>
      void fetch(target, {
        method: 'POST',
        body,
        keepalive: true,
        credentials: 'omit',
        headers: { 'Content-Type': 'application/json' },
      }).catch(() => undefined))

  const flush = () => {
    if (timer) clearTimeout(timer)
    timer = null
    while (queue.length) {
      const events = queue.slice(0, MAX_BATCH)
      queue = queue.slice(MAX_BATCH)
      send(url, JSON.stringify({ versionId: opts.versionId, visit, events }))
    }
  }
  const onHide = () => {
    if (document.visibilityState === 'hidden') flush()
  }
  document.addEventListener('visibilitychange', onHide)
  window.addEventListener('pagehide', flush)

  return {
    report(event) {
      const key = JSON.stringify(event)
      if (seen.has(key)) return
      seen.add(key)
      queue.push(event)
      if (!timer) timer = setTimeout(flush, FLUSH_MS)
    },
    flush,
    stop() {
      flush()
      document.removeEventListener('visibilitychange', onHide)
      window.removeEventListener('pagehide', flush)
    },
  }
}
