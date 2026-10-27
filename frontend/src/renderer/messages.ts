/**
 * Respondent-facing system strings (buttons, progress, validation, file and signature controls,
 * outcome screens). English only, for every form: Dhivehi appears only in form content and
 * answers (docs/DESIGN.md, "Languages"). Placeholders are `{name}`. Render these through `<En>`
 * (`./msg`) so they stay left to right and Latin inside a Dhivehi (RTL) form.
 */
export const MSG = {
  next: 'Next',
  back: 'Back',
  submit: 'Submit',
  stepOf: 'Step {n} of {total}',
  optional: '(optional)',
  required: '(required)',
  problemOne: "There's a problem",
  problemMany: 'There are {n} problems',
  answerThis: 'Answer this question',
  enterLabel: 'Enter {label}',
  chooseOption: 'Choose an option',
  chooseAtLeast: 'Choose at least {n}',
  chooseAtMost: 'Choose no more than {n}',
  chooseUpTo: 'Choose up to {n}',
  chooseAtLeastHint: 'Choose at least {n}',
  maxReached: 'You chose {n}, the most allowed. Clear one to pick another.',
  email: 'Enter an email address like name@example.com',
  phoneMv: 'Enter a phone number with 7 digits, like 7771234',
  approverDomain: 'Enter an address at {domains}',
  approverIsRespondent: "Enter someone else's address. You can't approve your own response.",
  phone: 'Enter a phone number using digits only',
  number: 'Enter a number',
  integer: 'Enter a whole number',
  between: 'Enter a number between {min} and {max}',
  atLeast: 'Enter a number of {min} or more',
  atMost: 'Enter a number of {max} or less',
  betweenHint: 'Between {min} and {max}',
  checkFormat: 'Check the format',
  tooLong: 'Use {max} characters or fewer',
  charCount: '{n} of {max}',
  dateFrom: 'Enter a date on or after {date}',
  dateTo: 'Enter a date on or before {date}',
  date: 'Enter a date',
  time: 'Enter a time',
  pickDate: 'Pick a date',
  choose: 'Choose…',
  other: 'Other',
  otherPlaceholder: 'Type your answer',
  yes: 'Yes',
  no: 'No',
  ratingItem: '{n} of {max}',
  thaanaKeyboard: 'Thaana keyboard',
  countryCode: 'Country code',
  // files
  dragFiles: 'Drag files here or',
  chooseFiles: 'Choose files',
  chooseFile: 'Choose a file',
  filesHint: '{types}. Up to {n} files, {size} MB each.',
  fileHint: '{types}. Up to {size} MB.',
  anyFile: 'Any file',
  filesMaxed: "You've added {n} files, the most allowed. Remove one to add another.",
  fileTooLarge: '“{name}” is larger than {size} MB. Choose a smaller file.',
  fileType: '“{name}” isn\'t allowed. Upload {types}.',
  uploadFailed: "Couldn't upload.",
  uploading: 'Uploading',
  retry: 'Retry',
  remove: 'Remove',
  removeFile: 'Remove {name}',
  waitUploads: 'Wait for uploads to finish',
  uploadFile: 'Upload a file',
  fileAgain: "Upload the file again. The upload didn't finish or has expired.",
  fileRejected: "This file can't be used. Upload a different file of an allowed type and size.",
  // repeater
  entry: 'Entry {n}',
  addEntry: 'Add entry',
  removeRowConfirm: 'Remove {name}?',
  keep: 'Keep',
  upTo: 'You can add up to {n}.',
  // signature
  signHere: 'Sign with your finger or mouse',
  undoStroke: 'Undo stroke',
  clear: 'Clear',
  signRequired: 'Sign in the box',
  signatureSmall: 'Your signature is too small. Sign across the box.',
  signatureEmpty: 'Signature pad. Empty',
  signatureSigned: 'Signature pad. Signed',
  signatureAlt: "If you can't draw a signature, contact the form owner.",
  turnPhone: 'Turn your phone sideways for more room.',
  // outcome
  successDefault: "Thanks. We've received your answers.",
  yourReference: 'Your reference',
  copyReference: 'Copy reference',
  copied: 'Copied',
  submitAnother: 'Submit another response',
  closedTitle: 'This form is closed',
  closedBody:
    "It's no longer accepting responses. Contact the organisation that sent you the link if you need help.",
  notFoundTitle: "We can't find this form",
  notFoundBody: 'Check the link. It may have been mistyped or the form may have been removed.',
  loadFailedTitle: "Couldn't open this form",
  loadFailedBody: 'Check your connection and try again.',
  tryAgain: 'Try again',
  submitFailed:
    "Couldn't send your answers. Check your connection and try again. Your answers are still here.",
  versionChanged:
    'This form was updated while you were filling it in. We kept your answers. Check the highlighted questions and submit again.',
  moreQuestions: '{n} more questions',
  oneMoreQuestion: '1 more question',
  madeWith: 'Made with JustForms',
  previewReference: 'Preview',
}

export type MessageKey = keyof typeof MSG

/** Fill `{name}` placeholders (plain text, e.g. for aria-labels). */
export function fmt(template: string, params: Record<string, string | number> = {}): string {
  return template.replace(/\{(\w+)\}/g, (_, k: string) =>
    Object.hasOwn(params, k) ? String(params[k]) : `{${k}}`,
  )
}

/**
 * System text in a plain-text slot (an <option>, a placeholder) inside right-to-left content:
 * LRI ... PDI isolates it so trailing punctuation stays at the end of the English.
 */
export function ltrRun(text: string): string {
  return `\u2066${text}\u2069`
}
