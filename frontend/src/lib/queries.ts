import { queryOptions } from '@tanstack/react-query'

import { api, ApiError } from './api'

export const metaQuery = queryOptions({
  queryKey: ['meta'],
  queryFn: api.meta,
  staleTime: Infinity,
})

/** The signed-in user, or null when there is no session. */
export const meQuery = queryOptions({
  queryKey: ['me'],
  queryFn: async () => {
    try {
      return await api.me()
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return null
      throw err
    }
  },
  staleTime: 60_000,
})

/** Branding for the studio: the user's organisation, or the default one before sign-in. */
export const brandQuery = (slug: string) =>
  queryOptions({ queryKey: ['brand', slug], queryFn: () => api.publicBrand(slug), staleTime: 300_000 })

export const brandingQuery = (orgId: string) =>
  queryOptions({ queryKey: ['branding', orgId], queryFn: () => api.branding(orgId) })

export const orgThemeQuery = (orgId: string) =>
  queryOptions({ queryKey: ['org-theme', orgId], queryFn: () => api.orgTheme(orgId) })

/** A form's theme: its overrides, the organisation's values and the resolved preview. */
export const formThemeQuery = (formId: string) =>
  queryOptions({ queryKey: ['form-theme', formId], queryFn: () => api.formTheme(formId) })

export const formsQuery = (orgId: string) =>
  queryOptions({ queryKey: ['forms', orgId], queryFn: () => api.listForms(orgId) })

export const draftQuery = (formId: string) =>
  queryOptions({ queryKey: ['draft', formId], queryFn: () => api.getDraft(formId), staleTime: 0 })

/** A missing form (404, also for a malformed id) is final: no retry, so the page says so at once. */
const retryUnlessMissing = (count: number, err: unknown) =>
  !(err instanceof ApiError && (err.status === 404 || err.status === 422)) && count < 1

export const formQuery = (formId: string) =>
  queryOptions({ queryKey: ['form', formId], queryFn: () => api.getForm(formId), retry: retryUnlessMissing })

export const versionsQuery = (formId: string) =>
  queryOptions({ queryKey: ['versions', formId], queryFn: () => api.versions(formId) })

export const versionQuery = (formId: string, n: number | null) =>
  queryOptions({
    queryKey: ['version', formId, n],
    queryFn: () => api.getVersion(formId, n!),
    enabled: n !== null,
    staleTime: Infinity,
  })

export const peopleQuery = (orgId: string) =>
  queryOptions({ queryKey: ['people', orgId], queryFn: () => api.people(orgId) })
