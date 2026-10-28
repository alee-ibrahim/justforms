/**
 * Scrubbing for browser error reports, the twin of `backend/app/telemetry/scrub.py` (both run
 * `spec/telemetry/scrub.json`). Keeps what describes the failure (exception types, stack frames
 * without variables, the page's path, browser context) and masks emails, phone and ID numbers,
 * tokens and query strings in every text it keeps. The server scrubs again in the tunnel.
 */

const FILTERED = '[Filtered]'
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/
const MAX_TEXT = 4096

const TEXT_RULES: [RegExp, string][] = [
  [/input_value=.*?(?=, input_type=|$)/gm, `input_value=${FILTERED}`],
  [/\[parameters: [^\n]*/g, `[parameters: ${FILTERED}]`],
  [/(Key \([^)\n]*\)=)\([^\n]*?\)(?= already| is not|\.|$)/gm, `$1(${FILTERED})`],
  [
    /\b(bearer|token|authorization|cookie|session|csrf|password|passwd|secret|api[_-]?key|code)(\s*[:=]\s*["']?|\s+)(?=[^\s"',;&]*[0-9])[^\s"',;&]+/gi,
    `$1$2${FILTERED}`,
  ],
  [/[^\s@<>"'(),;:/]+@[^\s@<>"'(),;:/]+\.[A-Za-z]{2,}/g, '[email]'],
  [/\b[A-Z][0-9]{6}\b/g, '[id]'],
  [/(?<![\w.-])\+?[0-9](?:[ -]?[0-9]){6,14}(?![\w.-])/g, '[number]'],
]
const TOKEN = /[A-Za-z0-9_-]{24,}/g
const SEGMENT = /^[A-Za-z0-9_-]{16,}$/

/** Long, has a digit, not a UUID: a token rather than a word or an identifier. */
const secretish = (value: string) => /[0-9]/.test(value) && !UUID.test(value)

export function scrubText(text: string): string {
  let out = text.slice(0, MAX_TEXT)
  for (const [pattern, repl] of TEXT_RULES) out = out.replace(pattern, repl)
  return out.replace(TOKEN, (m) => (secretish(m) ? '[token]' : m))
}

/** Scheme, host and path only; token-like path segments masked; no query or fragment. */
export function scrubUrl(url: string): string {
  const m = /^([a-zA-Z][a-zA-Z0-9+.-]*:\/\/[^/?#]*)?([^?#]*)/.exec(url)
  const base = m?.[1] ?? ''
  const path = (m?.[2] ?? '')
    .split('/')
    .map((s) => (SEGMENT.test(s) && secretish(s) ? ':token' : s))
    .join('/')
  return scrubText(base + path)
}

type Json = Record<string, unknown>
const isObj = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

function scrubValues(value: unknown, depth = 0): unknown {
  if (depth > 6) return FILTERED
  if (typeof value === 'string') return scrubText(value)
  if (Array.isArray(value)) return value.slice(0, 50).map((v) => scrubValues(v, depth + 1))
  if (isObj(value))
    return Object.fromEntries(Object.entries(value).slice(0, 50).map(([k, v]) => [k, scrubValues(v, depth + 1)]))
  return value
}

const EVENT_KEYS = new Set([
  'event_id', 'timestamp', 'platform', 'level', 'logger', 'transaction', 'server_name', 'release', 'dist',
  'environment', 'message', 'logentry', 'exception', 'tags', 'contexts', 'request', 'sdk', 'fingerprint', 'type',
])
const CONTEXT_KEYS = new Set(['runtime', 'os', 'browser', 'device', 'app', 'trace', 'culture'])
const FRAME_KEYS = new Set([
  'filename', 'abs_path', 'module', 'function', 'lineno', 'colno', 'in_app', 'context_line', 'pre_context',
  'post_context', 'platform',
])

function pick(obj: Json, keys: Iterable<string>): Json {
  const out: Json = {}
  for (const k of keys) if (k in obj) out[k] = obj[k]
  return out
}

function scrubFrame(frame: unknown): Json | null {
  if (!isObj(frame)) return null
  const out = pick(frame, [...FRAME_KEYS].filter((k) => k in frame)) // no "vars"
  for (const key of ['abs_path', 'filename'])
    if (typeof out[key] === 'string' && (out[key] as string).includes('://')) out[key] = scrubUrl(out[key] as string)
  if (typeof out.context_line === 'string') out.context_line = scrubText(out.context_line)
  for (const key of ['pre_context', 'post_context'])
    if (Array.isArray(out[key])) out[key] = (out[key] as unknown[]).map((x) => (typeof x === 'string' ? scrubText(x) : ''))
  return out
}

function scrubException(exc: unknown): unknown {
  if (!isObj(exc)) return exc
  if (!Array.isArray(exc.values)) return {}
  const kept: Json[] = []
  for (const item of exc.values.slice(0, 10)) {
    if (!isObj(item)) continue
    const entry = pick(item, ['type', 'module', 'mechanism'])
    if (typeof item.value === 'string') entry.value = scrubText(item.value)
    if (isObj(entry.mechanism)) entry.mechanism = pick(entry.mechanism, ['type', 'handled', 'synthetic'])
    const trace = item.stacktrace
    if (isObj(trace) && Array.isArray(trace.frames))
      entry.stacktrace = { frames: trace.frames.slice(-100).map(scrubFrame).filter((f): f is Json => !!f) }
    kept.push(entry)
  }
  return { values: kept }
}

/** A copy of `event` with only failure details, every text scrubbed. */
export function scrubEvent<T extends object>(event: T): T {
  const src = event as Json
  const out = pick(src, Object.keys(src).filter((k) => EVENT_KEYS.has(k)))
  if ('message' in out) {
    const msg = out.message
    out.message = typeof msg === 'string' ? scrubText(msg) : msg ? scrubValues(msg) : msg
  }
  if (isObj(out.logentry)) {
    const entry = out.logentry
    out.logentry = { message: scrubText(String(entry.formatted || entry.message || '')) }
  }
  if ('exception' in out) out.exception = scrubException(out.exception)
  if ('request' in out) {
    const req = out.request
    const kept: Json = {}
    if (isObj(req)) {
      if (typeof req.url === 'string') kept.url = scrubUrl(req.url)
      if (typeof req.method === 'string') kept.method = req.method.slice(0, 10)
    }
    if (Object.keys(kept).length) out.request = kept
    else delete out.request
  }
  if (typeof out.transaction === 'string') out.transaction = scrubUrl(out.transaction)
  if (isObj(out.tags))
    out.tags = Object.fromEntries(
      Object.entries(out.tags)
        .slice(0, 50)
        .map(([k, v]) => [k.slice(0, 32), scrubText(String(v)).slice(0, 200)]),
    )
  else delete out.tags
  if (isObj(out.contexts))
    out.contexts = Object.fromEntries(
      Object.entries(out.contexts)
        .filter(([k]) => CONTEXT_KEYS.has(k))
        .map(([k, v]) => [k, scrubValues(v)]),
    )
  else delete out.contexts
  return out as T
}
