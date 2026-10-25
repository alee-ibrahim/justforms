/** Studio date formatting: English, Western digits, 24-hour clock. */
const dateTime = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  numberingSystem: 'latn',
})

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso))
}

const dateTimeSeconds = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  numberingSystem: 'latn',
})

/** With seconds, for audit data. */
export function formatDateTimeSeconds(iso: string): string {
  return dateTimeSeconds.format(new Date(iso))
}

/** "3f9a…c21e" for long hashes; the full value goes in a tooltip. */
export function shortHash(hex: string): string {
  return hex.length > 12 ? `${hex.slice(0, 4)}…${hex.slice(-4)}` : hex
}

const dateOnly = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  numberingSystem: 'latn',
})

/** "7 Nov 2026". */
export function formatDate(iso: string): string {
  return dateOnly.format(new Date(iso))
}

const relative = new Intl.RelativeTimeFormat('en', { numeric: 'auto', style: 'long' })

/** "just now", "5 minutes ago", "yesterday", "3 days ago"; older than 30 days: "7 Nov 2026". */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const abs = Math.abs(seconds)
  if (abs < 45) return 'just now'
  if (abs < 3600) return relative.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return relative.format(Math.round(seconds / 3600), 'hour')
  if (abs < 30 * 86400) return relative.format(Math.round(seconds / 86400), 'day')
  return formatDate(iso)
}
