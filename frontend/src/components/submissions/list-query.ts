/** The submissions list query, shared by the list page and the viewer's Previous / Next. */
import { useInfiniteQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { api, type ListFilters } from '@/lib/api'

import type { SubmissionsSearch, Tab } from './search'

export function listFilters(search: SubmissionsSearch, tab: Tab): ListFilters {
  return {
    status: tab === 'all' ? undefined : tab,
    q: search.q,
    from: search.from,
    to: search.to,
    version: search.version,
    fields: search.fields ?? [],
  }
}

export function useSubmissionList(formId: string, filters: ListFilters, enabled: boolean) {
  const list = useInfiniteQuery({
    queryKey: ['submissions', formId, filters],
    queryFn: ({ pageParam }) => api.listSubmissions(formId, { ...filters, cursor: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    enabled,
  })
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data])
  const total = list.data?.pages[0]?.total ?? 0
  return { list, rows, total }
}

/** The submission last opened from this form's list: its row or card is focused on return. */
const lastKey = (formId: string) => `justforms:last-submission:${formId}`

export function rememberLastViewed(formId: string, id: string): void {
  try {
    window.sessionStorage.setItem(lastKey(formId), id)
  } catch {
    // storage blocked: focus simply isn't restored
  }
}

export function lastViewed(formId: string): string | null {
  try {
    return window.sessionStorage.getItem(lastKey(formId))
  } catch {
    return null
  }
}

/** The list's view state without the one-off `open` link parameter. */
export function listSearch(search: SubmissionsSearch): SubmissionsSearch {
  const { open: _open, ...rest } = search
  return rest
}

/** Where a submission sits in the loaded list: Previous is newer, Next is older. */
export function neighbours<T extends { id: string }>(rows: T[], id: string | undefined) {
  const index = id ? rows.findIndex((r) => r.id === id) : -1
  return {
    index,
    prev: index > 0 ? rows[index - 1] : undefined,
    next: index >= 0 ? rows[index + 1] : undefined,
    /** The last loaded row: Next has to load the next page first. */
    atEnd: index >= 0 && index === rows.length - 1,
  }
}
