/** Rating question (PHASE-2-SCREENS 4.5): a ToggleGroup of numbers. A lazy chunk of the renderer. */
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

import { controlId, useRenderer } from './context'
import type { ControlProps } from './fields'
import { fmt, MSG } from './messages'

export default function RatingControl({ field, path, describedBy, labelledBy }: ControlProps) {
  const ctx = useRenderer()
  const value = ctx.getValue(path)
  const set = (v: unknown) => ctx.setValue(path, v)
  const max = field.type === 'rating' ? (field.max ?? 5) : 5
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      value={typeof value === 'number' ? String(value) : ''}
      onValueChange={(v) => set(v ? Number(v) : undefined)}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      className="flex-wrap"
      dir="ltr"
    >
      {Array.from({ length: max }, (_, i) => i + 1).map((n) => (
        <ToggleGroupItem
          key={n}
          value={String(n)}
          id={n === 1 ? controlId(path) : undefined}
          aria-label={fmt(MSG.ratingItem, { n, max })}
          className="h-12 min-w-12 text-base tabular-nums sm:h-11 sm:min-w-11 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
        >
          {n}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
