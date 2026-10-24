/** Jotform import API (backend/app/api/v1/imports.py, DESIGN 13). Studio only. */
import type { Form, FormLanguage } from '@/schema'

import { ApiError, csrfToken, type SubmissionStatus } from './api'

async function call<T>(method: string, path: string, body?: unknown, raw?: { data: Blob; type: string }): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers['X-CSRF-Token'] = csrfToken()
  if (raw) headers['Content-Type'] = raw.type || 'application/octet-stream'
  else if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: raw ? raw.data : body === undefined ? undefined : JSON.stringify(body),
  })
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

export type ItemStatus = 'imported' | 'changed' | 'skipped'

export interface ReportItem {
  qid: string
  jotformType: string
  label: string
  status: ItemStatus
  justformsType: string | null
  elementId: string | null
  notes: string[]
}

export interface ConditionItem {
  description: string
  status: 'imported' | 'not_imported'
  reason: string
}

export interface FormImportReport {
  items: ReportItem[]
  counts: Record<ItemStatus, number>
  conditions: ConditionItem[]
  conditionsNote: string
  dropped: string[]
  notes: string[]
  /** The form's logo: downloaded and set as the draft's logo, or why not. */
  logo?: { status: 'imported' | 'not_imported' | 'none'; reason: string | null; source: string | null }
}

export interface FormImport {
  id: string
  kind: 'jotform_html' | 'jotform_api'
  status: 'preview' | 'done'
  schema: Form
  report: FormImportReport
  language: FormLanguage
  detectedLanguage: FormLanguage
  sourceUrl: string | null
  jotformFormId: string | null
  fieldCount: number
  pageCount: number
  formId: string | null
}

export type JotformRegion = 'us' | 'eu' | 'hipaa'

export interface JotformForm {
  id: string
  title: string
  count: number
  status: string
  updatedAt: string | null
}

export interface ImportColumn {
  index: number
  header: string
  samples: string[]
  target: string
}

export interface ImportTarget {
  value: string
  label: string
  type: string
}

export interface SubmissionsReport {
  rowsTotal: number
  imported: number
  skippedDuplicate: number
  skippedEmpty: number
  cellsDropped: number
  droppedByColumn: Record<string, number>
  links: number
  problemRows: { row: number; column: string; problem: string; value: string }[]
  dedupe: boolean
  error?: string
}

export type DateOrder = 'auto' | 'mdy' | 'dmy'

export interface SubmissionsImport {
  id: string
  formId: string
  status: 'preview' | 'running' | 'done' | 'failed'
  filename: string
  rowCount: number
  version: number
  columns: ImportColumn[]
  targets: ImportTarget[]
  dateOrder: DateOrder
  report: Partial<SubmissionsReport>
  stats: Record<string, number>
  createdAt: string
}

export interface MappingPreview {
  rows: { row: number; cells: { column: number; text: string; problem: string | null }[] }[]
  problems: number
  duplicateTargets: string[]
  hasSubmissionId: boolean
}

export const IGNORE = 'ignore'

export const importsApi = {
  fromHtml: (orgId: string, body: { html?: string; url?: string; language?: FormLanguage }) =>
    call<FormImport>('POST', `/orgs/${orgId}/imports/jotform/html`, body),
  listJotformForms: (orgId: string, apiKey: string, region: JotformRegion) =>
    call<JotformForm[]>('POST', `/orgs/${orgId}/imports/jotform/api/forms`, { apiKey, region }),
  fromApi: (orgId: string, apiKey: string, region: JotformRegion, formId: string) =>
    call<FormImport>('POST', `/orgs/${orgId}/imports/jotform/api`, { apiKey, region, formId }),
  createForm: (importId: string, body: { title?: string; language?: FormLanguage }) =>
    call<{ formId: string }>('POST', `/imports/${importId}/form`, body),
  uploadSubmissions: (formId: string, file: File) =>
    call<SubmissionsImport>(
      'POST',
      `/forms/${formId}/imports/submissions?filename=${encodeURIComponent(file.name)}`,
      undefined,
      { data: file, type: file.type || 'application/octet-stream' },
    ),
  getSubmissionsImport: (id: string) => call<SubmissionsImport>('GET', `/imports/${id}`),
  listSubmissionImports: (formId: string) => call<SubmissionsImport[]>('GET', `/forms/${formId}/imports`),
  setMapping: (id: string, columns: string[], dateOrder: DateOrder) =>
    call<MappingPreview>('PUT', `/imports/${id}/mapping`, { columns, dateOrder }),
  start: (id: string, status: SubmissionStatus) => call<SubmissionsImport>('POST', `/imports/${id}/start`, { status }),
}

/** Plain-English text for an API error code from the import endpoints. */
export function importErrorText(err: unknown): string {
  const detail = err instanceof ApiError ? err.detail : null
  switch (detail) {
    case 'not_a_jotform':
      return "We couldn't find any Jotform questions in this. Paste the form's full source code, or its public link."
    case 'fetch_not_jotform':
    case 'fetch_invalid_url':
      return 'Only links on jotform.com can be read. Paste the source code instead.'
    case 'fetch_too_large':
      return 'The form is larger than 5 MB. Paste the source code instead.'
    case 'jotform_bad_key':
      return "Jotform didn't accept this API key."
    case 'jotform_not_found':
      return "Jotform couldn't find that form for this API key."
    case 'jotform_rate_limited':
      return 'Jotform is limiting requests. Wait a minute and try again.'
    case 'jotform_unavailable':
      return "Jotform didn't answer. Try again in a moment."
    case 'file_empty':
      return 'This file is empty.'
    case 'file_unreadable':
      return "We couldn't read this file. Upload the .xlsx or .csv file Jotform gives you."
    case 'file_too_large':
      return 'The file is larger than 50 MB.'
    case 'file_too_many_rows':
      return 'The file has more than 100,000 rows. Split it and import each part.'
    case 'file_too_many_columns':
      return 'The file has more than 1,000 columns.'
    case 'not_published':
      return 'Publish the form first. Responses are imported into the published version.'
    case 'nothing_mapped':
      return 'Choose at least one column to import into a question.'
    case 'mapping_duplicate':
      return 'Two columns import into the same question. Choose one.'
    default:
      if (typeof detail === 'string' && detail.startsWith('fetch_'))
        return "Jotform didn't send the form. Check that the link is public, or paste the source code instead."
      if (err instanceof ApiError && err.status === 413) return 'The file is too large.'
      return 'Something went wrong. Check your connection and try again.'
  }
}

/** Problem codes from the converter (answer validation codes) as short English text. */
export const PROBLEM_TEXT: Record<string, string> = {
  unreadable: "Couldn't read this value",
  email: 'Not a valid email address',
  phone: 'Not a valid phone number',
  phone_mv: 'Not a valid phone number',
  number: 'Not a number',
  integer: 'Not a whole number',
  date: 'Not a date',
  time: 'Not a time',
  option: 'Not one of the options',
  too_long: 'Too long',
  pattern: "Doesn't match the expected format",
  between: 'Outside the allowed range',
  at_least: 'Below the minimum',
  at_most: 'Above the maximum',
  choose_at_least: 'Too few choices',
  choose_at_most: 'Too many choices',
  no_link: 'No link to the file',
}
