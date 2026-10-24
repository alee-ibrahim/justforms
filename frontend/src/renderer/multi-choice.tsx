/** Multiple-choice question (PHASE-2-SCREENS 4.5): checkbox cards. A lazy chunk of the renderer. */
import { Checkbox } from '@/components/ui/checkbox'
import { displayText } from '@/thaana/display'
import type { MultiChoiceField } from '@/schema'

import { controlId, useRenderer } from './context'
import { ChoiceCard, type ControlProps } from './fields'
import { leaveGroup } from './util'
import { fmt, MSG } from './messages'
import { En } from './msg'

export default function MultiChoiceControl({
  field,
  path,
  describedBy,
}: ControlProps & { field: MultiChoiceField }) {
  const ctx = useRenderer()
  const value = ctx.getValue(path)
  const set = (v: unknown) => ctx.setValue(path, v)
  const blur = () => ctx.blur(path)
  const chosen = Array.isArray(value) ? (value as string[]) : []
  const max = field.maxSelected ?? null
  const full = max !== null && chosen.length >= max
  const base = controlId(path)
  return (
    <div className="flex flex-col gap-2" aria-describedby={describedBy} onBlur={leaveGroup(blur)}>
      {field.options.map((o, i) => {
        const id = i === 0 ? base : `${base}-${i}`
        const checked = chosen.includes(o.value)
        const disabled = full && !checked
        return (
          <ChoiceCard
            key={o.value}
            id={id}
            disabled={disabled}
            control={
              <Checkbox
                id={id}
                checked={checked}
                disabled={disabled}
                onCheckedChange={(on) => {
                  const next = on ? [...chosen, o.value] : chosen.filter((v) => v !== o.value)
                  // Keep the schema's option order.
                  const ordered = field.options.map((x) => x.value).filter((v) => next.includes(v))
                  set(ordered.length ? ordered : undefined)
                }}
              />
            }
          >
            {displayText(o.label, ctx.language)}
          </ChoiceCard>
        )
      })}
      {full && (
        <p className="text-sm text-muted-foreground" aria-live="polite">
          <En>{fmt(MSG.maxReached, { n: max })}</En>
        </p>
      )}
    </div>
  )
}
