/** Forms list view state kept in the URL (FORMS-LIST-SCREENS 2): search, filters and sort. */
import type { FormListItem, FormStatus } from '@/lib/api'

export type FormsSort = 'edited' | 'submission' | 'name' | 'submissions'

export interface FormsSearch {
  q?: string
  owner?: 'mine'
  status?: FormStatus
  /** Missing = last edited. */
  sort?: Exclude<FormsSort, 'edited'>
}

export const SORT_LABELS: Record<FormsSort, string> = {
  edited: 'Last edited',
  submission: 'Last submission',
  name: 'Name',
  submissions: 'Submissions',
}

const STATUSES = new Set<FormStatus>(['draft', 'live', 'closed', 'archived'])
const SORTS = new Set(['submission', 'name', 'submissions'])

export function validateFormsSearch(search: Record<string, unknown>): FormsSearch {
  return {
    q: typeof search.q === 'string' && search.q.trim() ? search.q.slice(0, 200) : undefined,
    owner: search.owner === 'mine' ? 'mine' : undefined,
    status: typeof search.status === 'string' && STATUSES.has(search.status as FormStatus) ? (search.status as FormStatus) : undefined,
    sort: typeof search.sort === 'string' && SORTS.has(search.sort) ? (search.sort as FormsSearch['sort']) : undefined,
  }
}

export function isFiltered(search: FormsSearch): boolean {
  return Boolean(search.q || search.owner || search.status)
}

const collator = new Intl.Collator('en', { sensitivity: 'base', numeric: true })
const time = (iso: string | null) => (iso ? new Date(iso).getTime() : -Infinity)
const byEdited = (a: FormListItem, b: FormListItem) => time(b.lastEditedAt) - time(a.lastEditedAt)

const COMPARE: Record<FormsSort, (a: FormListItem, b: FormListItem) => number> = {
  edited: byEdited,
  // Newest first; never submitted at the end.
  submission: (a, b) => time(b.lastSubmissionAt) - time(a.lastSubmissionAt) || byEdited(a, b),
  // A to Z; untitled forms at the end.
  name: (a, b) => (!a.title ? 1 : 0) - (!b.title ? 1 : 0) || collator.compare(a.title, b.title) || byEdited(a, b),
  submissions: (a, b) => b.submissionCount - a.submissionCount || byEdited(a, b),
}

/** The rows to show, filtered and sorted; the input is not changed. */
export function applyFormsView(forms: FormListItem[], search: FormsSearch): FormListItem[] {
  const q = search.q?.trim().toLowerCase()
  return forms
    .filter((f) => !search.owner || f.ownedByMe)
    .filter((f) => !search.status || f.status === search.status)
    .filter(
      (f) =>
        !q ||
        [f.title, f.owner?.name ?? '', f.owner?.email ?? ''].some((text) => text.toLowerCase().includes(q)),
    )
    .sort(COMPARE[search.sort ?? 'edited'])
}

/** Where opening a form goes: its submissions once it has any (and always for submissions
 * viewers), else the editor. */
export function openPath(form: FormListItem): '/forms/$formId/submissions' | '/forms/$formId/edit' {
  return form.role === 'viewer' || form.submissionCount > 0 ? '/forms/$formId/submissions' : '/forms/$formId/edit'
}
