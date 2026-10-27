/**
 * The form's address: `https://<host>/<slug>` (docs/ux/FORM-THEME-SCREENS.md 1.2). Checked live
 * against the API (unique across the install, not one of the app's own words).
 */
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api, type FormSummary, type SlugCheck } from '@/lib/api'
import { hasThaana, isGenericSlug, titleSlug, toSlugText } from '@/thaana/latin'

export const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,99}$/

/** Lower case, spaces and other characters to hyphens, as people type; Thaana is romanised. */
export function normalizeSlug(value: string): string {
  return (hasThaana(value) ? toSlugText(value) : value)
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .slice(0, 100)
}

function useDebounced<T>(value: T, ms: number): T {
  const [out, setOut] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setOut(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return out
}

/** `null` while typing or checking; the API's answer otherwise. */
export function useSlugCheck(slug: string, formId: string | undefined, enabled: boolean) {
  const debounced = useDebounced(slug, 300)
  const settled = debounced === slug
  const query = useQuery({
    queryKey: ['slug-check', debounced, formId ?? null],
    queryFn: () => api.checkSlug(debounced, formId),
    enabled: enabled && settled && debounced.length > 0 && SLUG_RE.test(debounced),
    staleTime: 5_000,
  })
  if (!enabled || !slug) return { result: null, checking: false }
  if (!SLUG_RE.test(slug)) {
    const result: SlugCheck = { slug, available: false, problem: 'invalid', suggestion: null, url: '' }
    return { result, checking: false }
  }
  if (!settled || query.isFetching || !query.data || query.data.slug !== slug) return { result: null, checking: true }
  return { result: query.data, checking: false }
}

/** "forms.example.org/" for the address prefix. */
export function hostPrefix(url?: string): string {
  try {
    return `${new URL(url ?? window.location.origin).host}/`
  } catch {
    return `${window.location.host}/`
  }
}

/** The romanised address to offer, or null when the form doesn't need one. */
export function readableSlug(form: Pick<FormSummary, 'slug' | 'title'>): string | null {
  if (!isGenericSlug(form.slug) || !hasThaana(form.title)) return null
  const slug = titleSlug(form.title)
  return isGenericSlug(slug) ? null : slug
}
