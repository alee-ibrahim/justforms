/**
 * Logic editor (PHASE-2-SCREENS 2.8): "Show this question when…", "Make required when…" and
 * "After this page, go to…". Composed from Card, Select, Popover + Command, Input and Button.
 * Only complete conditions are written to the draft, and an edit that would create a loop is
 * held back with an explanation (the server rejects cyclic drafts).
 */
import { CheckIcon, ChevronsUpDownIcon, PlusIcon, Trash2Icon, TriangleAlertIcon } from 'lucide-react'
import { useState } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { buildIndex, type ElementInfo } from '@/logic/form-index'
import { cn } from '@/lib/utils'
import type { Condition, Element, FieldCondition, Form, NavigationRule, Op } from '@/schema'
import { contentProps, formLanguage } from '@/schema/language'

import { blockInfo, blockLabel } from './block-types'
import { ConditionSentence } from './condition-sentence'
import { countUnit, isSimpleCondition, opLabel, opsFor } from './logic-text'
import { cycleText } from './problems'
import { useStore } from './store'
import { updatePage } from './tree'

/** One editable row; incomplete rows stay local until they make a valid condition. */
interface Row {
  key: number
  field?: string
  op?: Op
  value?: unknown
}
type Join = 'all' | 'any'

let rowKey = 0
const UNARY: Op[] = ['empty', 'not_empty']

function rowsOf(cond: Condition | null | undefined): { join: Join; rows: Row[] } {
  if (!cond) return { join: 'all', rows: [] }
  const leaves: FieldCondition[] = 'field' in cond ? [cond] : 'all' in cond ? (cond.all as FieldCondition[]) : 'any' in cond ? (cond.any as FieldCondition[]) : []
  return {
    join: 'any' in cond ? 'any' : 'all',
    rows: leaves.map((l) => ({ key: ++rowKey, field: l.field, op: l.op, value: l.value })),
  }
}

function complete(row: Row): FieldCondition | null {
  if (!row.field || !row.op) return null
  if (UNARY.includes(row.op)) return { field: row.field, op: row.op }
  if (row.value === undefined || row.value === '' || (Array.isArray(row.value) && !row.value.length)) return null
  return { field: row.field, op: row.op, value: row.value as FieldCondition['value'] }
}

function toCondition(join: Join, rows: Row[]): Condition {
  const leaves = rows.map(complete).filter((c): c is FieldCondition => c !== null)
  return join === 'all' ? { all: leaves } : { any: leaves }
}

/** Questions a condition owned by `ownerId` may read (DESIGN 5.3 scope rules). */
function candidates(form: Form, ownerId: string | null): ElementInfo[] {
  const index = buildIndex(form)
  const owner = ownerId ? index.elements.get(ownerId) : undefined
  const ownerRepeater = owner?.repeaterId ?? null
  const exclude = new Set<string>()
  if (owner) {
    const walk = (el: Element) => {
      exclude.add(el.id)
      if (el.kind === 'section' || el.kind === 'repeater') (el.elements ?? []).forEach(walk)
    }
    walk(owner.element)
  }
  return [...index.elements.values()].filter((info) => {
    if (exclude.has(info.id)) return false
    if (info.kind === 'repeater') return info.repeaterId === null
    if (info.kind !== 'field') return false
    return info.repeaterId === null || info.repeaterId === ownerRepeater
  })
}

function FieldPicker({
  form,
  ownerId,
  value,
  onChange,
}: {
  form: Form
  ownerId: string | null
  value?: string
  onChange: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const index = buildIndex(form)
  const list = candidates(form, ownerId)
  const ownerOrder = ownerId ? [...index.elements.keys()].indexOf(ownerId) : -1
  const order = [...index.elements.keys()]
  const current = value ? index.elements.get(value)?.element : undefined
  const lang = formLanguage(form)
  const name = (el: Element) => blockLabel(el) || blockInfo(el).label
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Question"
          className={cn('w-full min-w-0 justify-between border-input font-normal', !value && 'text-muted-foreground')}
        >
          <span className="truncate">
            {current ? (
              <bdi dir="auto" lang={lang}>
                {name(current)}
              </bdi>
            ) : value ? (
              'Missing question'
            ) : (
              'Choose a question'
            )}
          </span>
          <ChevronsUpDownIcon className="text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        <Command>
          <CommandInput placeholder="Search questions" />
          <CommandList>
            <CommandEmpty>No question matches.</CommandEmpty>
            {form.pages.map((page, pi) => {
              const items = list.filter((i) => i.pageIndex === pi)
              if (!items.length) return null
              return (
                <CommandGroup key={page.id} heading={`Page ${pi + 1}${page.title ? `, ${page.title}` : ''}`}>
                  {items.map((info) => (
                    <CommandItem
                      key={info.id}
                      value={`${name(info.element)} ${info.id}`}
                      onSelect={() => {
                        onChange(info.id)
                        setOpen(false)
                      }}
                    >
                      <CheckIcon className={cn(value === info.id ? 'opacity-100' : 'opacity-0')} />
                      <span className="min-w-0 flex-1 truncate">
                        <bdi dir="auto" lang={lang}>
                          {name(info.element)}
                        </bdi>
                      </span>
                      <span className="font-mono text-xs text-muted-foreground">{info.id}</span>
                      {ownerOrder >= 0 && order.indexOf(info.id) > ownerOrder && (
                        <span className="text-xs text-muted-foreground">later in the form</span>
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
              )
            })}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

function ValueControl({ form, row, onChange }: { form: Form; row: Row; onChange: (v: unknown) => void }) {
  const el = row.field ? buildIndex(form).elements.get(row.field)?.element : undefined
  const content = contentProps(formLanguage(form))
  if (!row.op || UNARY.includes(row.op)) return null
  if (row.op.startsWith('count_'))
    return (
      <div className="flex items-center gap-2">
        <Input
          type="number"
          min={0}
          inputMode="numeric"
          aria-label="Count"
          className="w-20"
          value={typeof row.value === 'number' ? row.value : ''}
          onChange={(e) => onChange(e.target.value === '' ? undefined : Math.max(0, Math.floor(Number(e.target.value))))}
        />
        <span className="text-sm text-muted-foreground">{countUnit(el)}</span>
      </div>
    )
  if (el?.kind === 'field' && el.type === 'yes_no')
    return (
      <RadioGroup
        value={row.value === true ? 'yes' : row.value === false ? 'no' : ''}
        onValueChange={(v) => onChange(v === 'yes')}
        className="flex gap-4"
        aria-label="Answer"
      >
        {(['yes', 'no'] as const).map((v) => (
          <Field key={v} orientation="horizontal" className="w-auto">
            <RadioGroupItem value={v} id={`yn-${row.key}-${v}`} />
            <FieldLabel htmlFor={`yn-${row.key}-${v}`} className="font-normal">
              {v === 'yes' ? 'Yes' : 'No'}
            </FieldLabel>
          </Field>
        ))}
      </RadioGroup>
    )
  if (el?.kind === 'field' && (el.type === 'single_choice' || el.type === 'multi_choice')) {
    if (row.op === 'in' || row.op === 'not_in') {
      const chosen = Array.isArray(row.value) ? (row.value as string[]) : []
      return (
        <div className="flex flex-wrap gap-1" role="group" aria-label="Answers">
          {el.options.map((o) => {
            const on = chosen.includes(o.value)
            return (
              <Button
                key={o.value}
                type="button"
                size="xs"
                variant={on ? 'secondary' : 'outline'}
                aria-pressed={on}
                onClick={() => onChange(on ? chosen.filter((v) => v !== o.value) : [...chosen, o.value])}
              >
                {on && <CheckIcon />}
                <bdi dir="auto" lang={content.lang}>
                  {o.label || o.value}
                </bdi>
              </Button>
            )
          })}
        </div>
      )
    }
    return (
      <Select value={typeof row.value === 'string' ? row.value : ''} onValueChange={onChange}>
        <SelectTrigger className="w-full" aria-label="Answer">
          <SelectValue placeholder="Choose an answer" />
        </SelectTrigger>
        <SelectContent>
          {el.options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              <bdi dir="auto" lang={content.lang}>
                {o.label || o.value}
              </bdi>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }
  const numeric = el?.kind === 'field' && (el.type === 'number' || el.type === 'rating')
  const kind = el?.kind === 'field' && (el.type === 'date' || el.type === 'time') ? el.type : numeric ? 'number' : 'text'
  return (
    <Input
      type={kind}
      aria-label="Value"
      {...(kind === 'text' ? content : { dir: 'ltr' })}
      value={row.value === undefined || row.value === null ? '' : String(row.value)}
      onChange={(e) => {
        const raw = e.target.value
        if (numeric) onChange(raw === '' || Number.isNaN(Number(raw)) ? undefined : Number(raw))
        else onChange(raw)
      }}
    />
  )
}

/** The "when [all/any] of these are true" card with condition rows. */
function ConditionCard({
  form,
  ownerId,
  initial,
  onCommit,
  autoRow,
}: {
  form: Form
  ownerId: string | null
  initial: Condition | null | undefined
  /** Returns an error message when the condition can't be applied (loops). */
  onCommit: (cond: Condition) => string | null
  autoRow?: boolean
}) {
  const store = useStore()
  const start = rowsOf(initial)
  const [join, setJoin] = useState<Join>(start.join)
  const [rows, setRows] = useState<Row[]>(start.rows.length || !autoRow ? start.rows : [{ key: ++rowKey }])
  const [error, setError] = useState<string | null>(null)
  const index = buildIndex(form)

  const update = (nextJoin: Join, nextRows: Row[]) => {
    setJoin(nextJoin)
    setRows(nextRows)
    setError(onCommit(toCondition(nextJoin, nextRows)))
  }
  const patchRow = (key: number, patch: Partial<Row>) =>
    update(join, rows.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  return (
    <Card size="sm" className="gap-3 rounded-md shadow-none">
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-sm">
          <span>when</span>
          <Select value={join} onValueChange={(v) => update(v as Join, rows)}>
            <SelectTrigger size="sm" aria-label="All or any">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">all</SelectItem>
              <SelectItem value="any">any</SelectItem>
            </SelectContent>
          </Select>
          <span>of these are true</span>
        </div>
        {rows.map((row) => {
          const el = row.field ? index.elements.get(row.field)?.element : undefined
          const missing = row.field !== undefined && !el
          const ops = opsFor(el)
          return (
            <div
              key={row.key}
              className="flex flex-col gap-2 rounded-md border p-2"
              onMouseEnter={() => row.field && store.setHighlight([row.field])}
              onMouseLeave={() => store.setHighlight([])}
              onFocus={() => row.field && store.setHighlight([row.field])}
              onBlur={() => store.setHighlight([])}
            >
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <FieldPicker
                    form={form}
                    ownerId={ownerId}
                    value={row.field}
                    onChange={(id) => {
                      const next = buildIndex(form).elements.get(id)?.element
                      const nextOps = opsFor(next)
                      const op = row.op && nextOps.includes(row.op) ? row.op : nextOps[0]
                      const value =
                        next?.kind === 'field' && next.type === 'yes_no'
                          ? true
                          : next?.kind === 'field' && next.type === 'single_choice' && op === 'eq'
                            ? next.options[0]?.value
                            : undefined
                      patchRow(row.key, { field: id, op, value })
                    }}
                  />
                </div>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Remove condition"
                      onClick={() => update(join, rows.filter((r) => r.key !== row.key))}
                    >
                      <Trash2Icon />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Remove condition</TooltipContent>
                </Tooltip>
              </div>
              {missing && (
                <Badge variant="destructive">
                  <TriangleAlertIcon data-icon="inline-start" />
                  Missing question
                </Badge>
              )}
              {row.field && !missing && (
                <div className="flex flex-wrap items-center gap-2">
                  <Select value={row.op} onValueChange={(op) => patchRow(row.key, { op: op as Op, value: (op as Op).startsWith('count_') || op === 'in' || op === 'not_in' ? undefined : row.value })}>
                    <SelectTrigger className="min-w-36" aria-label="Comparison">
                      <SelectValue placeholder="Choose" />
                    </SelectTrigger>
                    <SelectContent>
                      {ops.map((op) => (
                        <SelectItem key={op} value={op}>
                          {opLabel(op, el)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <div className="min-w-0 flex-1">
                    <ValueControl form={form} row={row} onChange={(value) => patchRow(row.key, { value })} />
                  </div>
                </div>
              )}
            </div>
          )
        })}
        <Button variant="ghost" size="sm" className="self-start" onClick={() => setRows([...rows, { key: ++rowKey }])}>
          <PlusIcon />
          Add condition
        </Button>
        {error && (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}

/** Apply a change unless it creates a dependency loop. */
function useGuardedEdit() {
  const store = useStore()
  return (change: (f: Form) => Form): string | null => {
    const next = change(store.get().schema)
    const loop = cycleText(next)
    if (loop) return loop
    store.edit(() => next)
    return null
  }
}

function TooComplex({ cond, form, onRemove }: { cond: Condition; form: Form; onRemove: () => void }) {
  return (
    <Alert>
      <TriangleAlertIcon />
      <AlertDescription className="flex flex-col gap-2">
        <span>
          <ConditionSentence cond={cond} form={form} prefix="Shown when" />.
        </span>
        <span>This rule is too complex to edit here.</span>
        <Button variant="outline" size="sm" className="self-start" onClick={onRemove}>
          Remove rule
        </Button>
      </AlertDescription>
    </Alert>
  )
}

/** "Show this question / section / page" with Always or Only when…. */
export function VisibilityEditor({
  form,
  ownerId,
  noun,
  cond,
  apply,
}: {
  form: Form
  ownerId: string | null
  noun: 'question' | 'section' | 'page' | 'block'
  cond: Condition | null | undefined
  apply: (f: Form, cond: Condition | null) => Form
}) {
  const guarded = useGuardedEdit()
  const [mode, setMode] = useState<'always' | 'when'>(cond ? 'when' : 'always')
  if (cond && !isSimpleCondition(cond))
    return <TooComplex cond={cond} form={form} onRemove={() => guarded((f) => apply(f, null))} />
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">Show this {noun}</span>
        <Select
          value={mode}
          onValueChange={(v) => {
            setMode(v as 'always' | 'when')
            if (v === 'always') guarded((f) => apply(f, null))
            else guarded((f) => apply(f, { all: [] }))
          }}
        >
          <SelectTrigger size="sm" aria-label={`Show this ${noun}`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="always">Always</SelectItem>
            <SelectItem value="when">Only when…</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {mode === 'when' && (
        <>
          <ConditionCard
            form={form}
            ownerId={ownerId}
            initial={cond}
            autoRow
            onCommit={(c) => guarded((f) => apply(f, c))}
          />
          {cond && ('field' in cond || ('all' in cond ? cond.all : 'any' in cond ? cond.any : []).length > 0) && (
            <p className="text-sm text-muted-foreground" aria-live="polite">
              <ConditionSentence cond={cond} form={form} prefix="Shown when" />.
            </p>
          )}
        </>
      )}
    </div>
  )
}

/** "Make required" Never / Always / When…, kept in sync with the Required switch. */
export function RequiredEditor({
  form,
  field,
  apply,
}: {
  form: Form
  field: Extract<Element, { kind: 'field' }>
  apply: (f: Form, change: { required: boolean; requiredIf: Condition | null }) => Form
}) {
  const guarded = useGuardedEdit()
  const mode = field.requiredIf ? 'when' : field.required ? 'always' : 'never'
  const [local, setLocal] = useState<'never' | 'always' | 'when'>(mode)
  const shown = mode === 'when' || local === 'when' ? 'when' : mode
  if (field.requiredIf && !isSimpleCondition(field.requiredIf))
    return <TooComplex cond={field.requiredIf} form={form} onRemove={() => guarded((f) => apply(f, { required: false, requiredIf: null }))} />
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">Make required</span>
        <Select
          value={shown}
          onValueChange={(v) => {
            setLocal(v as typeof local)
            if (v === 'never') guarded((f) => apply(f, { required: false, requiredIf: null }))
            if (v === 'always') guarded((f) => apply(f, { required: true, requiredIf: null }))
          }}
        >
          <SelectTrigger size="sm" aria-label="Make required">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="never">Never</SelectItem>
            <SelectItem value="always">Always</SelectItem>
            <SelectItem value="when">When…</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {shown === 'when' && (
        <>
          <ConditionCard
            form={form}
            ownerId={field.id}
            initial={field.requiredIf}
            autoRow
            onCommit={(c) => {
              const leaves = 'all' in c ? c.all : 'any' in c ? c.any : [c]
              // Nothing complete yet: don't make it always required.
              if (!leaves.length) return guarded((f) => apply(f, { required: false, requiredIf: null }))
              return guarded((f) => apply(f, { required: false, requiredIf: c }))
            }}
          />
          {field.requiredIf && (
            <p className="text-sm text-muted-foreground" aria-live="polite">
              <ConditionSentence cond={field.requiredIf} form={form} prefix="Required when" />.
            </p>
          )}
        </>
      )}
    </div>
  )
}

/** "After this page, go to…" rules; targets are later pages or Submit (forward only). */
export function PageJumps({ form, pageIndex }: { form: Form; pageIndex: number }) {
  const guarded = useGuardedEdit()
  const page = form.pages[pageIndex]
  const rules = page.next ?? []
  const later = form.pages.slice(pageIndex + 1)
  const lang = formLanguage(form)
  const setRules = (f: Form, next: NavigationRule[]) => updatePage(f, pageIndex, (p) => ({ ...p, next }))
  const [errors, setErrors] = useState<Record<number, string | null>>({})
  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm font-medium">After this page</span>
      {rules.map((rule, i) => (
        <div key={i} className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2 text-sm">
            <span>If</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Remove rule"
                  onClick={() => guarded((f) => setRules(f, rules.filter((_, j) => j !== i)))}
                >
                  <Trash2Icon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Remove rule</TooltipContent>
            </Tooltip>
          </div>
          <ConditionCard
            form={form}
            ownerId={null}
            initial={rule.if}
            onCommit={(c) => {
              const err = guarded((f) => setRules(f, rules.map((r, j) => (j === i ? { ...r, if: c } : r))))
              setErrors((e) => ({ ...e, [i]: err }))
              return err
            }}
          />
          <div className="flex items-center gap-2 text-sm">
            <span>go to</span>
            <Select
              value={rule.goto}
              onValueChange={(goto) => guarded((f) => setRules(f, rules.map((r, j) => (j === i ? { ...r, goto } : r))))}
            >
              <SelectTrigger className="min-w-0 flex-1" aria-label="Go to">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectLabel>Later pages</SelectLabel>
                  {later.map((p) => {
                    const n = form.pages.indexOf(p) + 1
                    return (
                      <SelectItem key={p.id} value={p.id}>
                        {n}.{' '}
                        {p.title ? (
                          <bdi dir="auto" lang={lang}>
                            {p.title}
                          </bdi>
                        ) : (
                          `Page ${n}`
                        )}
                      </SelectItem>
                    )
                  })}
                </SelectGroup>
                <SelectItem value="submit">Submit the form</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {errors[i] && <span className="sr-only">{errors[i]}</span>}
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() =>
          guarded((f) => setRules(f, [...rules, { if: { any: [] }, goto: later[0]?.id ?? 'submit' }]))
        }
      >
        <PlusIcon />
        Add a rule
      </Button>
      <p className="text-sm text-muted-foreground">
        {rules.length ? 'Otherwise go to the next page.' : 'Goes to the next page.'}
      </p>
    </div>
  )
}
