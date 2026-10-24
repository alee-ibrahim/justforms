/** The three organisation roles as choice cards (PEOPLE-SCREENS 3.1, 3.2). */
import { Field, FieldContent, FieldDescription, FieldLabel, FieldTitle } from '@/components/ui/field'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import type { OrgRole } from '@/lib/api'
import { ORG_ROLES } from '@/lib/roles'

export function RolePicker({
  id,
  value,
  onChange,
  disabled,
  labelledBy,
}: {
  id: string
  value: OrgRole
  onChange: (role: OrgRole) => void
  /** Roles that can't be chosen (e.g. demoting the last admin). */
  disabled?: (role: OrgRole) => boolean
  labelledBy?: string
}) {
  return (
    <RadioGroup value={value} onValueChange={(v) => onChange(v as OrgRole)} aria-labelledby={labelledBy}>
      {ORG_ROLES.map((r) => (
        <FieldLabel key={r.value} htmlFor={`${id}-${r.value}`}>
          <Field orientation="horizontal" data-disabled={disabled?.(r.value) ? true : undefined}>
            <FieldContent>
              <FieldTitle>{r.label}</FieldTitle>
              <FieldDescription>{r.description}</FieldDescription>
            </FieldContent>
            <RadioGroupItem value={r.value} id={`${id}-${r.value}`} disabled={disabled?.(r.value)} />
          </Field>
        </FieldLabel>
      ))}
    </RadioGroup>
  )
}
