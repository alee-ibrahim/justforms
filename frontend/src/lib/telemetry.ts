/**
 * Optional browser error reporting (Sentry protocol, e.g. GlitchTip). Off unless the install
 * sets a DSN: `/api/v1/meta` then returns `telemetry`. The SDK is a lazy chunk loaded after the
 * page is idle, so it never counts towards a page's first-load budget; errors thrown before it
 * loads are kept (a few) and sent once it is ready.
 *
 * Privacy: reports go through the same-origin tunnel (`/api/v1/telemetry/envelope`), with no
 * default PII, no breadcrumbs (they would carry typed text and clicked labels), no session
 * replay, no tracing unless the install asks for it, and every event is scrubbed here
 * (`telemetry-scrub.ts`) and again on the server.
 */

export type TelemetryApp = 'studio' | 'form' | 'doc'

/** Call once per page entry, after the first render was scheduled. */
export function startTelemetry(app: TelemetryApp): void {
  const early: unknown[] = []
  const keep = (e: Event) => {
    if (early.length < 5) early.push((e as ErrorEvent).error ?? (e as PromiseRejectionEvent).reason)
  }
  const stop = () => {
    removeEventListener('error', keep)
    removeEventListener('unhandledrejection', keep)
  }
  addEventListener('error', keep)
  addEventListener('unhandledrejection', keep)
  // After load and a pause, so it never competes with the first paint; never breaks the page.
  const later = () =>
    setTimeout(() => import('./telemetry-init').then((m) => m.initTelemetry(app, early, stop)).catch(stop), 2000)
  if (document.readyState === 'complete') later()
  else addEventListener('load', later, { once: true })
}
