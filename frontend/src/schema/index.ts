/**
 * Form schema types and structural validation, derived from spec/form-schema.v1.json
 * (which is exported from the canonical Pydantic models in backend/app/schemas/form.py).
 *
 * Structural validation only: cross-element rules (unique ids, references, cycles) are
 * enforced by the backend. The rule engine lives in `@/logic`.
 */
import { z } from 'zod'

import type {
  Condition,
  ContentElement,
  JustFormsForm,
  Page,
  RepeaterElement,
  SectionElement,
} from './generated/form'
import spec from './generated/form-schema.v1.json'

export type * from './generated/form'

export type Form = JustFormsForm
export type Element = NonNullable<Page['elements']>[number]
export type FieldElement = Exclude<Element, ContentElement | SectionElement | RepeaterElement>
export type FieldType = FieldElement['type']
export type ContainerElement = SectionElement | RepeaterElement
export type { Condition }

export const SCHEMA_VERSION = '1'
export const ID_PATTERN = /^[a-z][a-z0-9_]{0,62}$/

export const FIELD_TYPES = [
  'short_text',
  'long_text',
  'email',
  'phone',
  'number',
  'date',
  'time',
  'single_choice',
  'multi_choice',
  'yes_no',
  'rating',
  'file',
  'signature',
  'hidden',
] as const satisfies readonly FieldType[]

/** zod schema built from the generated JSON Schema. */
export const formSchema = z.fromJSONSchema(spec as Parameters<typeof z.fromJSONSchema>[0])

export function parseForm(data: unknown): { ok: true; form: Form } | { ok: false; error: z.ZodError } {
  const result = formSchema.safeParse(data)
  return result.success
    ? { ok: true, form: result.data as Form }
    : { ok: false, error: result.error }
}

export {
  contentProps,
  FORM_LANGUAGES,
  formLanguage,
  isFormLanguage,
  type FormLanguage,
  type TextDirection,
} from './language'
