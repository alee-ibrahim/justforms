/**
 * Strings for the verify page. System text, so English for every form (docs/DESIGN.md,
 * "Languages"). Placeholders are `{name}`.
 */
export const DOC = {
  verifyTitle: 'Verify a document',
  genuineTitle: 'Genuine document',
  changedTitle: 'This document was changed',
  changedBody:
    "The record behind this document no longer matches what was signed. Don't rely on it; contact the organisation that issued it.",
  notFoundTitle: 'Document not found',
  notFoundBody: "This link doesn't match any document. Check that you scanned the code on the document itself.",
  loadFailed: "Couldn't load this page. Check your connection and try again.",
  issuedBy: 'Issued by {org}',
  reference: 'Reference',
  issued: 'Issued',
  approval: 'Approval',
  approvedOn: 'Approved on {date}',
  rejectedOn: 'Rejected on {date}',
  inProgress: 'In progress (step {n} of {total})',
  stopped: 'Stopped',
  approvedBy: 'Step {n} approved by',
  rejectedBy: 'Step {n} rejected by',
  about:
    "This page confirms the document came from this system and that its record hasn't changed since it was signed. It never shows the answers.",
  checkCopy: 'Check your copy',
  checkCopyHint: 'Choose the PDF you were given to check it is the genuine, latest copy.',
  choosePdf: 'Choose PDF',
  checking: 'Checking',
  result_genuine: 'This file is genuine and unchanged.',
  result_older: 'This file is genuine. A newer signed copy was issued on {date}.',
  result_modified: 'This file was changed after it was signed.',
  result_different: 'This file is a different document.',
  result_not_ours: "This isn't a signed PDF from this system.",
  result_changed: 'The record behind this file has changed since it was signed.',
  checkFailed: "Couldn't check the file. Try again.",
  tooMany: 'Too many tries. Wait a few minutes and try again.',
  tooLarge: 'This file is too large to be one of our documents.',
}

export function fmt(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, k: string) => String(values[k] ?? `{${k}}`))
}

/** "23 October 2026": system text, so English for every form. */
export function formatDay(iso: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    numberingSystem: 'latn',
  }).format(new Date(iso))
}

/** `lang` for a name that may be written in Thaana (an organisation name), so it gets the right face. */
export function scriptLang(text: string): 'dv' | 'en' {
  return /[\u0780-\u07bf]/.test(text) ? 'dv' : 'en'
}
