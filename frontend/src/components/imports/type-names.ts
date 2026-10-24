/** Plain names for the import report (REVIEW P2-17): raw type ids only under Technical details. */
import { BLOCK_TYPES } from '@/components/builder/block-types'

const JOTFORM: Record<string, string> = {
  textbox: 'Text box',
  textarea: 'Long text',
  email: 'Email',
  phone: 'Phone',
  number: 'Number',
  spinner: 'Number spinner',
  datetime: 'Date',
  time: 'Time',
  dropdown: 'Dropdown',
  radio: 'Single choice',
  checkbox: 'Multiple choice',
  fileupload: 'File upload',
  signature: 'Signature',
  fullname: 'Full name',
  address: 'Address',
  rating: 'Star rating',
  scale: 'Scale rating',
  hidden: 'Hidden field',
  autoincrement: 'Unique ID',
  head: 'Heading',
  collapse: 'Collapsible section',
  text: 'Paragraph',
  divider: 'Divider',
  button: 'Submit button',
  pagebreak: 'Page break',
  captcha: 'CAPTCHA',
  matrix: 'Matrix',
  inline: 'Fill in the blank',
  widget: 'Widget',
  appointment: 'Appointment',
  image: 'Image',
  mixed: 'Mixed question',
  products: 'Product list',
  payment: 'Payment',
  stripe: 'Payment',
}

/** "control_fullname" -> "Full name"; unknown types read as words ("control_star_rating" -> "Star rating"). */
export function jotformTypeName(type: string): string {
  const bare = type.replace(/^control_/, '')
  if (JOTFORM[bare]) return JOTFORM[bare]
  const words = bare.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** What the item became, with its article: "a section", "an email question", "the form title". */
function result(type: string): string {
  const special: Record<string, string> = {
    page: 'a new page',
    'form title': 'the form title',
    'page title': 'the page title',
    'submit label': 'the submit button text',
    'submit button': 'the submit button',
    CAPTCHA: 'the form’s CAPTCHA setting',
  }
  if (special[type]) return special[type]
  const block = BLOCK_TYPES.find((b) => b.type === type)
  const name = block ? block.label.toLowerCase() : type.replace(/_/g, ' ')
  const layout = block?.group === 'Layout'
  const phrase = layout ? name : `${name} question`
  return `${/^[aeiou]/.test(phrase) ? 'an' : 'a'} ${phrase}`
}

/** One plain sentence: "Full name became a section", "Matrix wasn't imported". */
export function importOutcome(jotformType: string, justformsType: string | null): string {
  const from = jotformTypeName(jotformType)
  return justformsType ? `${from} became ${result(justformsType)}` : `${from} wasn’t imported`
}
