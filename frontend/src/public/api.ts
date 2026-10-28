/**
 * Public (respondent) API. Public-link forms use no cookies at all. Email-code forms send the
 * respondent token as a bearer token; staff-only forms use the staff session cookie plus the
 * CSRF header (DESIGN 8.2-8.4).
 */
import type { Brand } from '@/lib/branding'
import type { ServerError } from '@/renderer/form-view'
import type { Form, FormLanguage } from '@/schema'

export type AccessMode = 'public' | 'otp' | 'staff'

export interface CaptchaChallenge {
  algorithm: string
  challenge: string
  maxnumber: number
  salt: string
  signature: string
}

export interface CaptchaConfig {
  provider: 'altcha' | 'turnstile' | 'hcaptcha'
  siteKey?: string
  challenge?: CaptchaChallenge
}

export interface LiveForm {
  formId: string
  versionId: string
  version: number
  orgName: string
  brand?: Brand
  accessMode: AccessMode
  title: string
  language: FormLanguage
  /** Null until the respondent has confirmed their email (email-code forms). */
  schema: Form | null
  thaanaFontCssUrl: string
  /** Per-page-load upload session; sent with every upload and with the submit. */
  uploadNonce?: string
  maxUploadMb: number
  respondentEmail: string | null
  captcha: CaptchaConfig | null
  otp?: { allowedDomains: string[]; oneResponse: boolean }
  /** Keep answers on this device while filling in (days until they expire); null when off. */
  saveProgress?: { days: number } | null
  /** Anonymous "where people get stuck" counters are on for this form. */
  friction?: boolean
}

/** How requests prove who the respondent is. */
export interface Access {
  mode: AccessMode
  /** Respondent token (email-code forms), held in memory only. */
  token?: string
}

export type LoadResult =
  | { ok: true; form: LiveForm }
  | { ok: false; reason: 'not_found' | 'closed' | 'error' | 'login' | 'already' }

export const formPath = (slug: string) => `/api/v1/public/forms/${encodeURIComponent(slug)}`

function csrfToken(): string {
  // Secure installs use the __Host- name (set by the API); prefer it over a leftover plain one.
  const match =
    document.cookie.match(/(?:^|;\s*)__Host-justforms_csrf=([^;]+)/) ??
    document.cookie.match(/(?:^|;\s*)justforms_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

/** Fetch options for a request made as this respondent. */
export function authInit(access: Access | undefined, unsafe: boolean): RequestInit {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (access?.token) headers.Authorization = `Bearer ${access.token}`
  if (access?.mode === 'staff' && unsafe) headers['X-CSRF-Token'] = csrfToken()
  return { headers, credentials: access?.mode === 'staff' ? 'same-origin' : 'omit' }
}

export async function loadForm(slug: string, access?: Access): Promise<LoadResult> {
  if (!slug) return { ok: false, reason: 'not_found' }
  try {
    let res = await fetch(formPath(slug), authInit(access, false))
    let body = (await res.json().catch(() => null)) as { detail?: string } | null
    // A staff-only form: try again with the staff session cookie.
    if (res.status === 401 && body?.detail === 'login_required' && access?.mode !== 'staff') {
      res = await fetch(formPath(slug), authInit({ mode: 'staff' }, false))
      body = (await res.json().catch(() => null)) as { detail?: string } | null
    }
    if (res.status === 401) return { ok: false, reason: 'login' }
    if (res.status === 409 && body?.detail === 'already_responded') return { ok: false, reason: 'already' }
    if (res.status === 404 || res.status === 403) return { ok: false, reason: 'not_found' }
    if (res.status === 410) return { ok: false, reason: 'closed' }
    if (!res.ok) return { ok: false, reason: 'error' }
    // An earlier address of the form (the web server redirects the page itself; the dev
    // server doesn't): show the current one.
    const moved = res.redirected ? new URL(res.url).pathname.split('/').pop() : undefined
    if (moved && moved !== slug && window.location.pathname.replace(/\/$/, '') === `/${slug}`)
      window.history.replaceState(window.history.state, '', `/${moved}${window.location.search}`)
    return { ok: true, form: body as unknown as LiveForm }
  } catch {
    return { ok: false, reason: 'error' }
  }
}

export type SubmitResponse =
  | { status: 'ok'; reference: string }
  | { status: 'version' }
  | { status: 'closed' }
  | { status: 'invalid'; errors: ServerError[] }
  | { status: 'captcha' }
  | { status: 'already' }
  | { status: 'expired' }
  | { status: 'busy' }
  | { status: 'network' }

export async function submitAnswers(
  slug: string,
  access: Access,
  versionId: string,
  data: Record<string, unknown>,
  uploadNonce: string,
  captchaToken?: string,
): Promise<SubmitResponse> {
  try {
    const init = authInit(access, true)
    const res = await fetch(`${formPath(slug)}/submissions`, {
      ...init,
      method: 'POST',
      headers: { ...(init.headers as Record<string, string>), 'Content-Type': 'application/json' },
      body: JSON.stringify({ versionId, data, uploadNonce, captchaToken }),
    })
    const body = (await res.json().catch(() => null)) as Record<string, unknown> | null
    if (res.ok) return { status: 'ok', reference: String(body?.reference ?? '') }
    if (res.status === 409 && body?.detail === 'already_responded') return { status: 'already' }
    if (res.status === 409) return { status: 'version' }
    if (res.status === 410) return { status: 'closed' }
    if (res.status === 401) return { status: 'expired' }
    if (res.status === 429) return { status: 'busy' }
    if (res.status === 422 && Array.isArray(body?.errors))
      return { status: 'invalid', errors: body.errors as ServerError[] }
    if (res.status === 422 && typeof body?.detail === 'string' && body.detail.startsWith('captcha_'))
      return { status: 'captcha' }
    return { status: 'network' }
  } catch {
    return { status: 'network' }
  }
}
