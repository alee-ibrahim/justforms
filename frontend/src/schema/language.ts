/**
 * Form language helpers. Kept free of zod and the JSON spec so the public renderer bundle can
 * import them cheaply.
 */
import type { JustFormsForm as Form } from './generated/form'

/**
 * A form is written in one language (`settings.language`, default `en`). The studio UI is
 * English only; this only affects how form content is typed and rendered.
 */
export type FormLanguage = NonNullable<Form['settings']['language']>
export type TextDirection = 'ltr' | 'rtl'

export const FORM_LANGUAGES = {
  en: { label: 'English', dir: 'ltr' },
  dv: { label: 'Dhivehi', dir: 'rtl' },
} as const satisfies Record<FormLanguage, { label: string; dir: TextDirection }>

export function isFormLanguage(value: unknown): value is FormLanguage {
  return typeof value === 'string' && Object.hasOwn(FORM_LANGUAGES, value)
}

export function formLanguage(form: Form): FormLanguage {
  return form.settings.language ?? 'en'
}

/** `lang` and `dir` for elements that show or edit form content (e.g. Thaana for `dv`). */
export function contentProps(language: FormLanguage): { lang: FormLanguage; dir: TextDirection } {
  return { lang: language, dir: FORM_LANGUAGES[language].dir }
}
