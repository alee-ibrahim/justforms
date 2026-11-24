/**
 * Alignment of form text (docs/DESIGN.md §16): Auto follows each text's own direction (Dhivehi
 * at the right, English at the left); Left / Center / Right fix it. An element or page left
 * unset follows the form default, so its toggle can be cleared (press the selected item again).
 */
import { AlignCenterIcon, AlignLeftIcon, AlignRightIcon } from 'lucide-react'

import { Field, FieldDescription, FieldLabel } from '@/components/ui/field'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { toggleGroupOn } from '@/lib/toggle'
import { type TextAlign } from '@/schema/direction'
import { ALIGN_OPTIONS } from '@/schema/align'

const ICONS = { left: AlignLeftIcon, center: AlignCenterIcon, right: AlignRightIcon } as const

function labelOf(value: TextAlign): string {
  return ALIGN_OPTIONS.find((o) => o.value === value)?.label ?? value
}

export function AlignField({
  id,
  label = 'Alignment',
  value,
  inherited,
  onChange,
  description,
}: {
  id: string
  label?: string
  value: TextAlign | null | undefined
  /** What an unset value follows (the form default); omit when a value is always set. */
  inherited?: TextAlign
  onChange: (value: TextAlign | undefined) => void
  description?: string
}) {
  const unset = value === undefined || value === null
  const hint =
    description ??
    (inherited !== undefined
      ? unset
        ? `Follows the form default (${labelOf(inherited)}). Auto puts Dhivehi on the right and English on the left.`
        : 'Press the selected option again to follow the form default.'
      : 'Auto puts Dhivehi text on the right and English on the left. Each question can change it.')
  return (
    <Field>
      <FieldLabel id={`${id}-label`}>{label}</FieldLabel>
      <ToggleGroup
        type="single"
        variant="outline"
        aria-labelledby={`${id}-label`}
        value={value ?? ''}
        onValueChange={(v) => {
          if (v) onChange(v as TextAlign)
          else if (inherited !== undefined) onChange(undefined)
        }}
        className={toggleGroupOn}
      >
        {ALIGN_OPTIONS.map(({ value: v, label: name }) => {
          const Icon = v === 'auto' ? null : ICONS[v]
          return (
            <ToggleGroupItem key={v} value={v} aria-label={name} title={name} className="px-3">
              {Icon ? <Icon /> : name}
            </ToggleGroupItem>
          )
        })}
      </ToggleGroup>
      <FieldDescription>{hint}</FieldDescription>
    </Field>
  )
}
