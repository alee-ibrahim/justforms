/**
 * Identity-number presets for the "ID number" question (a short_text with `idPreset`). The
 * presets are data (`spec/id-presets.v1.json`, exported from the backend's canonical copy), so
 * the renderer and the server (`backend/app/schemas/id_presets.py`) apply the same pattern and
 * normalising. `idPreset: "custom"` keeps the question's own pattern, placeholder and message.
 */
import type { FieldElement } from '@/schema'
import data from '@/schema/generated/id-presets.v1.json'

export interface IdPreset {
  id: string
  label: string
  example: string
  pattern: string
  placeholder: string
  message: string
  maxLength: number
  uppercase?: boolean
  stripSpaces?: boolean
  sensitive?: boolean
}

export const CUSTOM_ID = 'custom'
export const ID_PRESETS: readonly IdPreset[] = (data as { presets: IdPreset[] }).presets

/** The preset whose rules apply to this question, or null (no preset, custom or unknown). */
export function idPresetOf(field: FieldElement): IdPreset | null {
  if (field.type !== 'short_text' || !field.idPreset || field.idPreset === CUSTOM_ID) return null
  return ID_PRESETS.find((p) => p.id === field.idPreset) ?? null
}

export function normalizeWith(preset: IdPreset | null, value: unknown): unknown {
  if (!preset || typeof value !== 'string') return value
  let out = value
  if (preset.stripSpaces) out = out.replace(/\s+/gu, '')
  if (preset.uppercase) out = out.toUpperCase()
  return out
}

/** The answer as stored: ID numbers without spaces and upper-cased, as the preset says. */
export function normalizeAnswer(field: FieldElement, value: unknown): unknown {
  return normalizeWith(idPresetOf(field), value)
}
