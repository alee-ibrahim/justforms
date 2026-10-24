/** Checks on a paper form before it is sent (the server checks again). */
const MAX_BYTES = 20 * 1024 * 1024
const TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/webp']

export function fileProblem(file: File): string | null {
  const okType = TYPES.includes(file.type) || /\.(pdf|jpe?g|png|webp)$/i.test(file.name)
  if (!okType) return 'Choose a PDF, JPG, PNG or WebP file.'
  if (file.size > MAX_BYTES) return 'This file is larger than 20 MB. Scan it at a lower resolution.'
  return null
}

const THAANA = /[ހ-޿]/

/** `lang` for a snippet of form text shown in the English studio: "dv" only when it is in
 * Thaana, so Latin words in a Dhivehi form keep the Latin face. */
export function textLang(text: string, language: string): string | undefined {
  return language === 'dv' && THAANA.test(text) ? 'dv' : undefined
}
