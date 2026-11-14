/**
 * The error worth reporting for a window `error` / `unhandledrejection` event. Some error events
 * carry no error object (a ResizeObserver loop notice, a cross-origin "Script error."), and a
 * promise may be rejected with anything: those become an Error with a readable message, so a
 * report is never titled "undefined".
 */
export function errorOf(e: Event): Error {
  if (e.type === 'unhandledrejection') {
    const reason = (e as PromiseRejectionEvent).reason
    return reason instanceof Error ? reason : new Error(`Unhandled rejection: ${String(reason)}`)
  }
  const ev = e as ErrorEvent
  if (ev.error instanceof Error) return ev.error
  if (ev.error !== undefined && ev.error !== null) return new Error(String(ev.error))
  return new Error(ev.message || 'Error event without error object')
}
