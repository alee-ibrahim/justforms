/** Checks on a paper form before it is sent (the server checks again). */
const MAX_BYTES = 20 * 1024 * 1024
const TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/webp']

export function fileProblem(file: File): string | null {
  const okType = TYPES.includes(file.type) || /\.(pdf|jpe?g|png|webp)$/i.test(file.name)
  if (!okType) return 'Choose a PDF, JPG, PNG or WebP file.'
  if (file.size > MAX_BYTES) return 'This file is larger than 20 MB. Scan it at a lower resolution.'
  return null
}
