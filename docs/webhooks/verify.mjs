// Reference verifier for JustForms webhooks (Node.js 18+, no dependencies).
//
//   import { verify } from './verify.mjs'
//   const ok = verify(secret, req.headers, rawBody) // rawBody: the exact Buffer received
//
// Reject the request when ok is false. Use the raw body, not re-serialised JSON.
import { createHmac, timingSafeEqual } from 'node:crypto'

const TOLERANCE_SECONDS = 300

function header(headers, name) {
  const key = Object.keys(headers).find((k) => k.toLowerCase() === name)
  const value = key === undefined ? undefined : headers[key]
  return Array.isArray(value) ? value[0] : value
}

export function verify(secret, headers, body, { now = Date.now() / 1000, tolerance = TOLERANCE_SECONDS } = {}) {
  const id = header(headers, 'justforms-webhook-id')
  const timestamp = header(headers, 'justforms-webhook-timestamp')
  if (!id || !/^\d+$/.test(timestamp ?? '')) return false
  if (Math.abs(now - Number(timestamp)) > tolerance) return false // possible replay
  const expected = createHmac('sha256', secret)
    .update(`${id}.${timestamp}.`)
    .update(typeof body === 'string' ? Buffer.from(body, 'utf8') : body)
    .digest()
  // During a secret rotation the header carries two signatures: "v1=...,v1=...".
  for (const part of (header(headers, 'justforms-webhook-signature') ?? '').split(',')) {
    const [version, value] = part.trim().split('=')
    if (version !== 'v1' || !/^[0-9a-f]{64}$/.test(value ?? '')) continue
    if (timingSafeEqual(Buffer.from(value, 'hex'), expected)) return true
  }
  return false
}
