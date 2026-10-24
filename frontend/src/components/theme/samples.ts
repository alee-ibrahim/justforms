/** Sample forms for the theme previews (docs/ux/FORM-THEME-SCREENS.md 3.4). The Dhivehi text
 * comes from spec/examples/youth-programme.json (a draft until checked, like all examples). */
import type { Form } from '@/schema'

export const SAMPLE_EN: Form = {
  schemaVersion: '1',
  settings: {
    language: 'en',
    title: 'Youth programme application',
    description: 'It takes about five minutes. You can come back to it before you submit.',
  },
  pages: [
    {
      id: 'p_you',
      title: 'Your details',
      elements: [
        { kind: 'field', id: 'full_name', type: 'short_text', label: 'Full name', required: true },
        {
          kind: 'field',
          id: 'national_id',
          type: 'short_text',
          label: 'ID card number',
          description: 'Like A123456',
          required: true,
          inputScript: 'latin',
        },
        {
          kind: 'field',
          id: 'relation',
          type: 'single_choice',
          label: 'Who is filling this in?',
          required: true,
          options: [
            { value: 'self', label: 'The applicant' },
            { value: 'parent', label: 'A parent' },
            { value: 'other', label: 'Someone else' },
          ],
        },
      ],
    },
    { id: 'p_more', title: 'Guardian', elements: [{ kind: 'field', id: 'guardian', type: 'short_text', label: 'Guardian name' }] },
  ],
} as Form

export const SAMPLE_DV: Form = {
  schemaVersion: '1',
  settings: { language: 'dv', title: 'ޒުވާނުންގެ ޕްރޮގްރާމަށް ހުށަހަޅާ ފޯމު' },
  pages: [
    {
      id: 'p_you',
      title: 'އަމިއްލަ މައުލޫމާތު',
      elements: [
        { kind: 'field', id: 'full_name', type: 'short_text', label: 'ފުރިހަމަ ނަން', required: true },
        {
          kind: 'field',
          id: 'national_id',
          type: 'short_text',
          label: 'އައިޑީ ކާޑު ނަންބަރު',
          required: true,
          inputScript: 'latin',
        },
        {
          kind: 'field',
          id: 'relation',
          type: 'single_choice',
          label: 'ގުޅުން',
          required: true,
          options: [
            { value: 'child', label: 'ދަރިފުޅު' },
            { value: 'parent', label: 'މައިންބަފައިން' },
            { value: 'other', label: 'އެހެނިހެން' },
          ],
        },
      ],
    },
    { id: 'p_more', title: 'ބެލެނިވެރިޔާ', elements: [{ kind: 'field', id: 'guardian', type: 'short_text', label: 'ބެލެނިވެރިޔާގެ ނަން' }] },
  ],
} as Form
