/** The lazy half of telemetry.ts: reads the install's settings and starts the Sentry SDK. */
import {
  browserApiErrorsIntegration,
  captureException,
  dedupeIntegration,
  eventFiltersIntegration,
  globalHandlersIntegration,
  httpContextIntegration,
  init,
  linkedErrorsIntegration,
} from '@sentry/browser'

import type { TelemetryApp } from './telemetry'
import { errorOf } from './telemetry-error'
import { scrubEvent } from './telemetry-scrub'

interface TelemetryConfig {
  dsn: string
  /** Same-origin tunnel, or null when browsers send straight to the DSN. */
  tunnel: string | null
  environment: string
  release: string
  tracesSampleRate?: number
}

/** Starts reporting when the install has a DSN; sends the errors caught before. */
export async function initTelemetry(app: TelemetryApp, early: Event[], stopEarly: () => void): Promise<void> {
  const res = await fetch('/api/v1/meta', { credentials: 'omit', headers: { Accept: 'application/json' } })
  const config = res.ok ? ((await res.json()) as { telemetry?: TelemetryConfig | null }).telemetry : null
  if (!config) return stopEarly()
  init({
    dsn: config.dsn,
    tunnel: config.tunnel ?? undefined,
    release: config.release,
    environment: config.environment,
    // Nothing about the person: no user, cookies, headers, bodies or query strings.
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: false,
      httpBodies: [],
      urlQueryParams: false,
      graphQL: { document: false, variables: false },
      genAI: { inputs: false, outputs: false },
      databaseQueryData: false,
      queues: false,
    },
    tracesSampleRate: config.tracesSampleRate ?? 0,
    maxBreadcrumbs: 0,
    // Only what reports errors: no breadcrumbs, no replay, no tracing, no feedback.
    defaultIntegrations: false,
    integrations: [
      globalHandlersIntegration(),
      browserApiErrorsIntegration(),
      linkedErrorsIntegration(),
      dedupeIntegration(),
      // Browser notices, not bugs: a ResizeObserver that ran past one frame, and errors from
      // cross-origin scripts the browser hides ("Script error.").
      eventFiltersIntegration({ ignoreErrors: [/ResizeObserver loop/, /^Script error\.?$/] }),
      httpContextIntegration(),
    ],
    initialScope: { tags: { app } },
    beforeBreadcrumb: () => null,
    beforeSend: (event) => scrubEvent(event),
  })
  stopEarly()
  for (const e of early.splice(0)) captureException(errorOf(e))
}
