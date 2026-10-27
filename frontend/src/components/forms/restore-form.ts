/** Restoring a form from the trash (SUBMISSIONS-SORT-AND-TRASH 4): its address may have been
 * taken meanwhile, then the server answers 409 with a suggestion. */
import { ApiError, api, type FormSummary } from '@/lib/api'

export type RestoreResult = { ok: true; form: FormSummary } | { ok: false; taken: string; suggestion: string }

export async function restoreForm(formId: string, slug?: string): Promise<RestoreResult> {
  try {
    return { ok: true, form: await api.restoreForm(formId, slug) }
  } catch (e) {
    if (e instanceof ApiError && e.status === 409 && e.detail === 'slug_taken') {
      const body = e.body as { slug?: string; suggestion?: string } | null
      return { ok: false, taken: body?.slug ?? slug ?? '', suggestion: body?.suggestion ?? '' }
    }
    throw e
  }
}
