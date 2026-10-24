/** Which organisation Organisation settings is showing (`?org=`, PEOPLE-SCREENS 2). */
import { useQuery } from '@tanstack/react-query'
import { useSearch } from '@tanstack/react-router'

import type { Me } from './api'
import { meQuery } from './queries'

export function validateSettingsSearch(search: Record<string, unknown>): { org?: string } {
  return typeof search.org === 'string' && search.org ? { org: search.org } : {}
}

/** The organisation these settings are for: `?org=` when it is one of yours, else your first. */
export function useSettingsOrg(): { me: Me | null | undefined; org: Me['orgs'][number] | undefined } {
  const { data: me } = useQuery(meQuery)
  const search = useSearch({ from: '/authed/settings' })
  const org = me?.orgs.find((o) => o.id === search.org) ?? me?.orgs[0]
  return { me, org }
}
