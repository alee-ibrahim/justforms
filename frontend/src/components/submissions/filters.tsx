/**
 * Submission filters (PHASE-3-SCREENS 4): a "Filter" popover that adds one question filter at
 * a time, chips that read as sentences, the "Submitted" date range and the version picker.
 */
import { CalendarIcon, ListFilterIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import type { DateRange } from 'react-day-picker'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { FieldFilter, FilterOp } from '@/lib/api'
import type { FieldElement, FormLanguage } from '@/schema'

type Kind = 'text' | 'number' | 'date' | 'choice' | 'multi' | 'yes_no' | 'presence'

function kindOf(field: FieldElement): Kind {
  switch (field.type) {
    case 'number':
    case 'rating':
      return 'number'
    case 'date':
    case 'time':
      return 'date'
    case 'single_choice':
      return 'choice'
    case 'multi_choice':
      return 'multi'
    case 'yes_no':
      return 'yes_no'
    case 'file':
    case 'signature':
      return 'presence'
    default:
      return 'text'
  }
}

const OPS: Record<Kind, [FilterOp, string][]> = {
  text: [['contains', 'contains']],
  number: [
    ['eq', 'is'],
    ['gte', 'at least'],
    ['lte', 'at most'],
  ],
  date: [
    ['gte', 'on or after'],
    ['lte', 'on or before'],
  ],
  choice: [
    ['eq', 'is'],
    ['neq', 'is not'],
  ],
  multi: [['includes', 'includes']],
  yes_no: [['eq', 'is']],
  presence: [
    ['answered', 'has an answer'],
    ['unanswered', 'has no answer'],
  ],
}

function opLabel(field: FieldElement, op: FilterOp): string {
  return OPS[kindOf(field)].find(([o]) => o === op)?.[1] ?? op
}

function valueLabel(field: FieldElement, value: FieldFilter['value']): string {
  if (value === undefined) return ''
  if (field.type === 'yes_no') return value ? 'Yes' : 'No'
  if (field.type === 'single_choice' || field.type === 'multi_choice')
    return field.options.find((o) => o.value === value)?.label ?? String(value)
  return String(value)
}

/** "Age at least 18" */
function filterSentence(field: FieldElement | undefined, f: FieldFilter): string {
  if (!field) return `${f.field} ${f.op} ${f.value ?? ''}`.trim()
  return [field.label, opLabel(field, f.op), valueLabel(field, f.value)].filter(Boolean).join(' ')
}

export function AddFilter({
  fields,
  language,
  onAdd,
}: {
  fields: FieldElement[]
  language: FormLanguage
  onAdd: (f: FieldFilter) => void
}) {
  const [open, setOpen] = useState(false)
  const [fieldId, setFieldId] = useState('')
  const [op, setOp] = useState<FilterOp | ''>('')
  const [value, setValue] = useState('')
  const field = fields.find((f) => f.id === fieldId)
  const kind = field ? kindOf(field) : null
  const needsValue = kind !== 'presence'
  const ready = field && op && (!needsValue || value !== '')

  const reset = () => {
    setFieldId('')
    setOp('')
    setValue('')
  }
  const add = () => {
    if (!field || !op) return
    let v: FieldFilter['value']
    if (needsValue) v = kind === 'number' ? Number(value) : kind === 'yes_no' ? value === 'true' : value
    onAdd({ field: field.id, op, ...(v !== undefined ? { value: v } : {}) })
    reset()
    setOpen(false)
  }
  const lang = { lang: language, dir: 'auto' as const }

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) reset()
      }}
    >
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm">
          <ListFilterIcon />
          Filter
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            add()
          }}
        >
          <FieldGroup className="gap-3">
            <Field>
              <FieldLabel htmlFor="filter-field">Question</FieldLabel>
              <Select
                value={fieldId}
                onValueChange={(v) => {
                  setFieldId(v)
                  const next = fields.find((f) => f.id === v)
                  setOp(next ? OPS[kindOf(next)][0][0] : '')
                  setValue('')
                }}
              >
                <SelectTrigger id="filter-field" className="w-full">
                  <SelectValue placeholder="Choose a question" />
                </SelectTrigger>
                <SelectContent>
                  {fields.map((f) => (
                    <SelectItem key={f.id} value={f.id}>
                      <bdi {...lang}>{f.label}</bdi>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            {field && kind && (
              <Field>
                <FieldLabel htmlFor="filter-op">Condition</FieldLabel>
                <Select value={op} onValueChange={(v) => setOp(v as FilterOp)}>
                  <SelectTrigger id="filter-op" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {OPS[kind].map(([o, label]) => (
                      <SelectItem key={o} value={o}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            )}
            {field && needsValue && (
              <Field>
                <FieldLabel htmlFor="filter-value">Value</FieldLabel>
                {field.type === 'single_choice' || field.type === 'multi_choice' || field.type === 'yes_no' ? (
                  <Select value={value} onValueChange={setValue}>
                    <SelectTrigger id="filter-value" className="w-full">
                      <SelectValue placeholder="Choose" />
                    </SelectTrigger>
                    <SelectContent>
                      {field.type === 'yes_no' ? (
                        <>
                          <SelectItem value="true">Yes</SelectItem>
                          <SelectItem value="false">No</SelectItem>
                        </>
                      ) : (
                        field.options.map((o) => (
                          <SelectItem key={o.value} value={o.value}>
                            <bdi {...lang}>{o.label}</bdi>
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id="filter-value"
                    type={kind === 'number' ? 'number' : field.type === 'date' ? 'date' : field.type === 'time' ? 'time' : 'text'}
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    {...(kind === 'text' ? lang : { dir: 'ltr' })}
                  />
                )}
              </Field>
            )}
            <Button type="submit" size="sm" disabled={!ready}>
              Add filter
            </Button>
          </FieldGroup>
        </form>
      </PopoverContent>
    </Popover>
  )
}

export function FilterChips({
  filters,
  fields,
  language,
  onRemove,
}: {
  filters: FieldFilter[]
  fields: FieldElement[]
  language: FormLanguage
  onRemove: (index: number) => void
}) {
  return (
    <>
      {filters.map((f, i) => {
        const field = fields.find((x) => x.id === f.field)
        const sentence = filterSentence(field, f)
        return (
          <Badge key={`${f.field}-${i}`} variant="outline" className="h-7 gap-1 pe-0.5 text-sm font-normal">
            <bdi lang={language} dir="auto">
              {sentence}
            </bdi>
            <Button
              variant="ghost"
              size="icon-xs"
              className="rounded-full"
              aria-label={`Remove filter: ${sentence}`}
              onClick={() => onRemove(i)}
            >
              <XIcon />
            </Button>
          </Badge>
        )
      })}
    </>
  )
}

const pad = (n: number) => String(n).padStart(2, '0')
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const daysAgo = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return isoDay(d)
}

const PRESETS: { key: string; label: string; range: () => { from?: string; to?: string } }[] = [
  { key: 'any', label: 'Any time', range: () => ({}) },
  { key: 'today', label: 'Today', range: () => ({ from: daysAgo(0) }) },
  { key: '7', label: 'Last 7 days', range: () => ({ from: daysAgo(6) }) },
  { key: '30', label: 'Last 30 days', range: () => ({ from: daysAgo(29) }) },
]

function rangeLabel(from?: string, to?: string): string {
  if (!from && !to) return 'Any time'
  const preset = PRESETS.find((p) => {
    const r = p.range()
    return r.from === from && r.to === to
  })
  if (preset) return preset.label
  const fmt = (s: string) =>
    new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(new Date(`${s}T00:00`))
  if (from && to) return from === to ? fmt(from) : `${fmt(from)} to ${fmt(to)}`
  return from ? `From ${fmt(from)}` : `Until ${fmt(to!)}`
}

export function DateRangeFilter({
  from,
  to,
  onChange,
}: {
  from?: string
  to?: string
  onChange: (range: { from?: string; to?: string }) => void
}) {
  const [open, setOpen] = useState(false)
  const [today] = useState(() => new Date())
  const selected: DateRange | undefined = from ? { from: new Date(`${from}T00:00`), to: to ? new Date(`${to}T00:00`) : undefined } : undefined
  const current = PRESETS.find((p) => {
    const r = p.range()
    return r.from === from && r.to === to
  })?.key
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm">
          <CalendarIcon />
          Submitted: {rangeLabel(from, to)}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-auto flex-col gap-3 sm:flex-row">
        <RadioGroup
          value={current ?? ''}
          onValueChange={(key) => {
            const p = PRESETS.find((x) => x.key === key)
            if (p) {
              onChange(p.range())
              setOpen(false)
            }
          }}
          aria-label="Submitted"
          className="min-w-36 content-start gap-3 self-start sm:border-e sm:pe-3"
        >
          {PRESETS.map((p) => (
            <div key={p.key} className="flex items-center gap-2">
              <RadioGroupItem value={p.key} id={`range-${p.key}`} />
              <Label htmlFor={`range-${p.key}`} className="font-normal">
                {p.label}
              </Label>
            </div>
          ))}
        </RadioGroup>
        <Calendar
          mode="range"
          selected={selected}
          onSelect={(r) => onChange({ from: r?.from ? isoDay(r.from) : undefined, to: r?.to ? isoDay(r.to) : undefined })}
          disabled={{ after: today }}
          numberOfMonths={1}
        />
      </PopoverContent>
    </Popover>
  )
}

export function VersionFilter({
  versions,
  value,
  onChange,
}: {
  versions: number[]
  value?: number
  onChange: (v?: number) => void
}) {
  if (versions.length < 2) return null
  return (
    <Select value={value ? String(value) : 'all'} onValueChange={(v) => onChange(v === 'all' ? undefined : Number(v))}>
      <SelectTrigger size="sm" aria-label="Version">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">All versions</SelectItem>
        {versions.map((n) => (
          <SelectItem key={n} value={String(n)}>
            Version {n}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
