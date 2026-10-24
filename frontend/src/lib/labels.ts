/** English labels for studio UI enums. The studio UI is English only. */
import type { FormStatus } from '@/lib/api'
import type { FieldType } from '@/schema'

export const FIELD_TYPE_LABELS: Record<FieldType, string> = {
  short_text: 'Short text',
  long_text: 'Long text',
  email: 'Email',
  phone: 'Phone',
  number: 'Number',
  date: 'Date',
  time: 'Time',
  single_choice: 'Single choice',
  multi_choice: 'Multiple choice',
  yes_no: 'Yes / No',
  rating: 'Rating',
  file: 'File upload',
  signature: 'Signature',
  hidden: 'Hidden value',
}

export const FORM_STATUS_LABELS: Record<FormStatus, string> = {
  draft: 'Draft',
  live: 'Live',
  closed: 'Closed',
  archived: 'Archived',
}
