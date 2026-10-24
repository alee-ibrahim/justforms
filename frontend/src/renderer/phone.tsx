/** Phone question (PHASE-2-SCREENS 4.5): country code + local number. A lazy chunk of the renderer. */
import { useState } from 'react'

import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import type { PhoneField } from '@/schema'

import { controlId, useRenderer } from './context'
import type { ControlProps } from './fields'
import { MSG } from './messages'

const COUNTRIES: [code: string, dial: string][] = [
  ['MV', '+960'],
  ['IN', '+91'],
  ['LK', '+94'],
  ['BD', '+880'],
  ['PK', '+92'],
  ['NP', '+977'],
  ['AE', '+971'],
  ['SA', '+966'],
  ['MY', '+60'],
  ['SG', '+65'],
  ['TH', '+66'],
  ['CN', '+86'],
  ['GB', '+44'],
  ['US', '+1'],
  ['AU', '+61'],
]

function splitPhone(value: unknown, fallback: string): [string, string] {
  if (typeof value !== 'string') return [fallback, '']
  const match = [...COUNTRIES]
    .sort((a, b) => b[1].length - a[1].length)
    .find(([, dial]) => value.startsWith(dial))
  return match ? [match[1], value.slice(match[1].length)] : [fallback, value.replace(/^\+/, '')]
}

export default function PhoneControl({ field, path, invalid, describedBy }: ControlProps & { field: PhoneField }) {
  const ctx = useRenderer()
  const value = ctx.getValue(path)
  const set = (v: unknown) => ctx.setValue(path, v)
  const blur = () => ctx.blur(path)
  const fallback = COUNTRIES.find(([c]) => c === (field.defaultCountry ?? 'MV'))?.[1] ?? '+960'
  const [dial, local] = splitPhone(value, fallback)
  const [dialCode, setDial] = useState(dial)
  const emit = (d: string, digits: string) => set(digits ? `${d}${digits}` : undefined)
  return (
    <InputGroup className="h-12 sm:h-11" dir="ltr">
      <InputGroupAddon className="ps-1">
        <NativeSelect
          aria-label={MSG.countryCode}
          size="sm"
          value={dialCode}
          onChange={(e) => {
            setDial(e.target.value)
            emit(e.target.value, local)
          }}
          className="[&_select]:border-0 [&_select]:bg-transparent [&_select]:text-base"
        >
          {COUNTRIES.map(([code, d]) => (
            <NativeSelectOption key={code} value={d}>
              {code} {d}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </InputGroupAddon>
      <InputGroupInput
        id={controlId(path)}
        type="tel"
        inputMode="tel"
        autoComplete="tel-national"
        dir="ltr"
        value={local}
        placeholder={field.placeholder ?? (dialCode === '+960' ? '7771234' : undefined)}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onChange={(e) => emit(dialCode, e.target.value.replace(/[^\d]/g, ''))}
        onBlur={blur}
        className="text-base md:text-base"
      />
    </InputGroup>
  )
}
