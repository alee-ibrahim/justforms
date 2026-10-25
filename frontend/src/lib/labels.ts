/** English labels for studio UI enums. The studio UI is English only. */
import type { FormRole, FormStatus } from '@/lib/api'
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

/** Per-form roles. The API value `viewer` reads "Submissions viewer" everywhere in the UI. */
export const FORM_ROLE_LABELS: Record<FormRole, string> = {
  owner: 'Owner',
  editor: 'Editor',
  viewer: 'Submissions viewer',
}

export const FORM_ROLE_DESCRIPTIONS: Record<FormRole, string> = {
  owner: 'Everything an editor can do, plus manage access and delete the form.',
  editor: 'Can edit and publish the form and change submission status.',
  viewer: "Can view and export submissions, can't edit the form.",
}
