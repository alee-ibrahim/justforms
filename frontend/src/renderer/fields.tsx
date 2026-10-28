/**
 * One control per field type (PHASE-2-SCREENS 4.5), composed from official shadcn components.
 * Used by the public renderer, the preview and (inert) the builder canvas.
 */
import { lazy, Suspense, useMemo, useState } from 'react'

import { FieldContent, FieldLabel, Field as UiField, FieldTitle } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { displayText } from '@/thaana/display'
import type {
  FieldElement,
  LongTextField,
  ShortTextField,
  SingleChoiceField,
} from '@/schema'

import { type AnswerPath, controlId, useRenderer } from './context'
import { idPresetOf, normalizeWith } from './id-presets'
import { leaveGroup } from './util'
import { ltrRun, MSG } from './messages'
import { En, Msg } from './msg'

const DatePicker = lazy(() => import('./date-picker'))
const SignaturePad = lazy(() => import('./signature-pad'))
const FileUpload = lazy(() => import('./file-upload'))
// Rare question types are lazy chunks too, to keep the public form's first load small.
const RatingControl = lazy(() => import('./rating'))
const MultiChoiceControl = lazy(() => import('./multi-choice'))
const PhoneControl = lazy(() => import('./phone'))
const ThaanaInput = lazy(() => import('./thaana-input'))

/** Comfortable public sizing, applied at the call site (components/ui stays untouched). */
export const CONTROL = 'h-12 text-base md:text-base sm:h-11'
const SELECT = '[&_select]:h-12 [&_select]:text-base sm:[&_select]:h-11 w-full'

export interface ControlProps {
  field: FieldElement
  path: AnswerPath
  invalid: boolean
  describedBy?: string
  labelledBy?: string
}

function useAnswer(path: AnswerPath) {
  const ctx = useRenderer()
  return {
    ctx,
    value: ctx.getValue(path),
    set: (v: unknown) => ctx.setValue(path, v),
    blur: () => ctx.blur(path),
  }
}


function useCoarsePointer(): boolean {
  return useMemo(
    () => typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches,
    [],
  )
}

/** Sensible `autocomplete` from the question key. */
function autoComplete(id: string): string | undefined {
  if (/(^|_)(full_)?name$/.test(id)) return 'name'
  if (/email/.test(id)) return 'email'
  if (/phone|mobile|tel/.test(id)) return 'tel'
  if (/address/.test(id)) return 'street-address'
  return undefined
}

// -- text ----------------------------------------------------------------------------------

function TextControl({
  field,
  path,
  invalid,
  describedBy,
}: ControlProps & { field: ShortTextField | LongTextField }) {
  const { ctx, value, set, blur } = useAnswer(path)
  // An ID number: Latin typing (never the Thaana keyboard), normalised as it is typed.
  const preset = idPresetOf(field)
  const script = preset ? 'latin' : (field.inputScript ?? 'auto')
  const text = typeof value === 'string' ? value : ''
  const dir = script === 'latin' ? 'ltr' : script === 'thaana' ? 'rtl' : undefined
  const common = {
    id: controlId(path),
    dir,
    value: text,
    placeholder: field.placeholder || preset?.placeholder || undefined,
    'aria-invalid': invalid || undefined,
    'aria-describedby': describedBy,
    onChange: (e: { target: { value: string } }) => {
      const next = normalizeWith(preset, e.target.value) as string
      set(next === '' ? undefined : next)
    },
    onBlur: blur,
  }
  const max = preset ? preset.maxLength : field.maxLength
  const counter =
    max && text.length >= max * 0.8 ? (
      <p className="text-sm text-muted-foreground tabular-nums" aria-live="polite">
        <Msg t={MSG.charCount} params={{ n: text.length, max }} />
      </p>
    ) : null

  if (script === 'latin' || (script === 'auto' && ctx.language !== 'dv')) {
    return (
      <>
        {field.type === 'long_text' ? (
          <Textarea {...common} rows={field.rows ?? 4} className="min-h-28 text-base md:text-base" />
        ) : (
          <Input
            {...common}
            {...(preset
              ? { autoComplete: 'off', autoCapitalize: 'characters', autoCorrect: 'off', spellCheck: false }
              : { autoComplete: autoComplete(field.id) })}
            className={cn(CONTROL, preset && 'tabular-nums tracking-wide')}
          />
        )}
        {counter}
      </>
    )
  }
  // Thaana input with the phonetic keyboard toggle: only Dhivehi forms need it (lazy chunk).
  const long = field.type === 'long_text'
  const rows = field.type === 'long_text' ? (field.rows ?? 4) : 4
  return (
    <>
      <Suspense
        fallback={
          long ? (
            <Textarea {...common} rows={rows} className="min-h-28 text-base md:text-base" />
          ) : (
            <Input {...common} className={CONTROL} />
          )
        }
      >
        <ThaanaInput common={common} long={long} rows={rows} canvas={ctx.mode === 'canvas'} />
      </Suspense>
      {counter}
    </>
  )
}

// -- number --------------------------------------------------------------------------------

function NumberControl({ field, path, invalid, describedBy }: ControlProps) {
  const { value, set, blur } = useAnswer(path)
  const integer = field.type === 'number' && field.integer
  const [text, setText] = useState(value === undefined || value === null ? '' : String(value))
  const shown = typeof value === 'number' && Number(text) !== value ? String(value) : text
  return (
    <Input
      id={controlId(path)}
      inputMode={integer ? 'numeric' : 'decimal'}
      dir="ltr"
      value={shown}
      placeholder={field.placeholder ?? undefined}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(e) => {
        const raw = e.target.value
        setText(raw)
        const trimmed = raw.trim().replace(',', '.')
        if (trimmed === '') set(undefined)
        else if (/^-?\d+(\.\d+)?$/.test(trimmed)) set(Number(trimmed))
        else set(raw)
      }}
      onBlur={blur}
      className={cn(CONTROL, 'max-w-48')}
    />
  )
}

// -- date / time ---------------------------------------------------------------------------

function DateControl({ field, path, invalid, describedBy }: ControlProps) {
  const { value, set, blur } = useAnswer(path)
  const coarse = useCoarsePointer()
  const native = (
    <Input
      id={controlId(path)}
      type="date"
      dir="ltr"
      value={typeof value === 'string' ? value : ''}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(e) => set(e.target.value || undefined)}
      onBlur={blur}
      className={cn(CONTROL, 'max-w-56')}
    />
  )
  // Native picker on touch devices (better UX, smaller bundle); Calendar on pointer devices.
  if (coarse || field.type !== 'date') return native
  return (
    <Suspense fallback={native}>
      <DatePicker field={field} path={path} invalid={invalid} describedBy={describedBy} />
    </Suspense>
  )
}

function TimeControl({ path, invalid, describedBy }: ControlProps) {
  const { value, set, blur } = useAnswer(path)
  return (
    <Input
      id={controlId(path)}
      type="time"
      dir="ltr"
      value={typeof value === 'string' ? value : ''}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(e) => set(e.target.value || undefined)}
      onBlur={blur}
      className={cn(CONTROL, 'max-w-40')}
    />
  )
}

// -- choices -------------------------------------------------------------------------------

const OTHER = '__other__'

/** shadcn "choice card": the whole row is the label and the tap target. */
export function ChoiceCard({
  id,
  children,
  control,
  disabled,
}: {
  id: string
  children: React.ReactNode
  control: React.ReactNode
  disabled?: boolean
}) {
  return (
    <FieldLabel htmlFor={id} className="w-full">
      <UiField
        orientation="horizontal"
        data-disabled={disabled || undefined}
        className="min-h-12 items-center gap-3"
      >
        {control}
        <FieldContent>
          <FieldTitle className="text-base font-normal">{children}</FieldTitle>
        </FieldContent>
      </UiField>
    </FieldLabel>
  )
}

function SingleChoiceControl({
  field,
  path,
  invalid,
  describedBy,
  labelledBy,
}: ControlProps & { field: SingleChoiceField }) {
  const { ctx, value, set, blur } = useAnswer(path)
  const values = field.options.map((o) => o.value)
  const current = typeof value === 'string' ? value : undefined
  const isOther = current !== undefined && !values.includes(current)
  const [otherOpen, setOtherOpen] = useState(isOther)
  const base = controlId(path)

  if (field.display === 'dropdown') {
    return (
      <NativeSelect
        id={base}
        value={current ?? ''}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onChange={(e) => set(e.target.value || undefined)}
        onBlur={blur}
        className={SELECT}
      >
        <NativeSelectOption value="" disabled lang="en">
          {ltrRun(MSG.choose)}
        </NativeSelectOption>
        {field.options.map((o) => (
          <NativeSelectOption key={o.value} value={o.value}>
            {o.label}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    )
  }
  return (
    <div className="flex flex-col gap-2" onBlur={leaveGroup(blur)}>
      <RadioGroup
        value={otherOpen ? OTHER : (current ?? '')}
        onValueChange={(v) => {
          if (v === OTHER) {
            setOtherOpen(true)
            set(isOther ? current : undefined)
          } else {
            setOtherOpen(false)
            set(v)
          }
        }}
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
      >
        {field.options.map((o, i) => (
          <ChoiceCard
            key={o.value}
            id={i === 0 ? base : `${base}-${i}`}
            control={<RadioGroupItem value={o.value} id={i === 0 ? base : `${base}-${i}`} />}
          >
            {displayText(o.label, ctx.language)}
          </ChoiceCard>
        ))}
        {field.allowOther && (
          <ChoiceCard
            id={`${base}-other`}
            control={<RadioGroupItem value={OTHER} id={`${base}-other`} />}
          >
            <En>{MSG.other}</En>
          </ChoiceCard>
        )}
      </RadioGroup>
      {field.allowOther && otherOpen && (
        <Input
          aria-label={MSG.other}
          placeholder={MSG.otherPlaceholder}
          value={isOther ? current : ''}
          onChange={(e) => set(e.target.value || undefined)}
          className={CONTROL}
          autoFocus={ctx.mode === 'fill'}
        />
      )}
    </div>
  )
}

function YesNoControl({ path, invalid, describedBy, labelledBy }: ControlProps) {
  const { value, set, blur } = useAnswer(path)
  const base = controlId(path)
  return (
    <RadioGroup
      value={value === true ? 'yes' : value === false ? 'no' : ''}
      onValueChange={(v) => set(v === 'yes')}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      onBlur={leaveGroup(blur)}
      className="grid grid-cols-2 max-[359px]:grid-cols-1"
    >
      <ChoiceCard id={base} control={<RadioGroupItem value="yes" id={base} />}>
        <En>{MSG.yes}</En>
      </ChoiceCard>
      <ChoiceCard id={`${base}-no`} control={<RadioGroupItem value="no" id={`${base}-no`} />}>
        <En>{MSG.no}</En>
      </ChoiceCard>
    </RadioGroup>
  )
}

function EmailControl({ field, path, invalid, describedBy }: ControlProps) {
  const { value, set, blur } = useAnswer(path)
  return (
    <Input
      id={controlId(path)}
      type="email"
      inputMode="email"
      autoComplete="email"
      dir="ltr"
      value={typeof value === 'string' ? value : ''}
      placeholder={field.placeholder ?? undefined}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(e) => set(e.target.value.trim() === '' ? undefined : e.target.value.trim())}
      onBlur={blur}
      className={CONTROL}
    />
  )
}

/** Picks the control for a field type. Group-like controls are labelled by the legend. */
export function FieldControl(props: ControlProps) {
  const { field } = props
  switch (field.type) {
    case 'short_text':
    case 'long_text':
      return <TextControl {...props} field={field} />
    case 'email':
      return <EmailControl {...props} />
    case 'phone':
      return (
        <Suspense fallback={<Input className={CONTROL} aria-hidden tabIndex={-1} readOnly dir="ltr" />}>
          <PhoneControl {...props} field={field} />
        </Suspense>
      )
    case 'number':
      return <NumberControl {...props} />
    case 'date':
      return <DateControl {...props} />
    case 'time':
      return <TimeControl {...props} />
    case 'single_choice':
      return <SingleChoiceControl {...props} field={field} />
    case 'multi_choice':
      return (
        <Suspense fallback={<div className="h-12" />}>
          <MultiChoiceControl {...props} field={field} />
        </Suspense>
      )
    case 'yes_no':
      return <YesNoControl {...props} />
    case 'rating':
      return (
        <Suspense fallback={<div className="h-12 sm:h-11" />}>
          <RatingControl {...props} />
        </Suspense>
      )
    case 'file':
      return (
        <Suspense fallback={<div className="h-36 rounded-md border border-input" />}>
          <FileUpload {...props} field={field} />
        </Suspense>
      )
    case 'signature':
      return (
        <Suspense fallback={<div className="h-48 rounded-md border bg-card" />}>
          <SignaturePad {...props} field={field} />
        </Suspense>
      )
    case 'hidden':
      return null
  }
}
