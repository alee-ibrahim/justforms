/**
 * Inspector (PHASE-2-SCREENS 2.7): edits the selected question, section, repeater, text block,
 * page or (nothing selected) the form. Accordion groups; the open set is remembered per type.
 */
import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { EllipsisIcon, GripVerticalIcon, LockIcon, PlusIcon, XIcon } from 'lucide-react'
import { type ReactNode, useContext, useState } from 'react'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useMenuTooltip } from '@/components/layout/use-menu-tooltip'
import { toggleGroupOn } from '@/lib/toggle'
import { cn } from '@/lib/utils'
import { ltrRun, MSG } from '@/renderer/messages'
import type { Element, FieldElement, Form, Option } from '@/schema'
import { contentProps, formLanguage, isFormLanguage } from '@/schema/language'

import { duplicate, requestDelete, wrap } from './actions'
import { ContentInput, ContentTextarea } from './content-input'
import { blockInfo } from './block-types'
import { PageJumps, RequiredEditor, VisibilityEditor } from './logic-editor'
import { FormContext } from './form-context'
import { usePublished, usePublishedSensitive } from './published'
import { useBuilder, useStore } from './store'
import {
  addPage,
  duplicatePage,
  findElement,
  movePage,
  optionsFromText,
  renameId,
  takenIds,
  updateElement,
  updatePage,
} from './tree'

// -- small field helpers ---------------------------------------------------------------------

function TextField({
  id,
  label,
  value,
  onChange,
  content,
  multiline,
  description,
  error,
  placeholder,
  mono,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  content?: boolean
  multiline?: boolean
  description?: ReactNode
  error?: string | null
  placeholder?: string
  mono?: boolean
}) {
  const form = useBuilder((s) => s.schema)
  const publishTried = useBuilder((s) => s.publishTried)
  // Missing text is flagged quietly on the canvas at once; the red error waits until the input
  // was left once or Publish was tried (REVIEW P2-4).
  const [touched, setTouched] = useState(false)
  const language = formLanguage(form)
  const props = content ? contentProps(language) : {}
  const shown = error && (touched || publishTried) ? error : null
  return (
    <Field data-invalid={shown ? true : undefined} onBlur={() => setTouched(true)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {content && multiline ? (
        <ContentTextarea id={id} rows={2} language={language} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      ) : content ? (
        <ContentInput
          id={id}
          language={language}
          value={value}
          placeholder={placeholder}
          aria-invalid={shown ? true : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : multiline ? (
        <Textarea id={id} rows={2} {...props} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <Input
          id={id}
          {...props}
          value={value}
          placeholder={placeholder}
          aria-invalid={shown ? true : undefined}
          className={cn(mono && 'font-mono')}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {description && <FieldDescription>{description}</FieldDescription>}
      {shown && <FieldError>{shown}</FieldError>}
    </Field>
  )
}

function NumberField({
  id,
  label,
  value,
  onChange,
  min,
  integer,
}: {
  id: string
  label: string
  value: number | null | undefined
  onChange: (v: number | undefined) => void
  min?: number
  integer?: boolean
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        type="number"
        inputMode={integer ? 'numeric' : 'decimal'}
        min={min}
        value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value
          if (raw === '') return onChange(undefined)
          const n = Number(raw)
          if (Number.isFinite(n)) onChange(integer ? Math.round(n) : n)
        }}
      />
    </Field>
  )
}

function SwitchField({
  id,
  label,
  checked,
  onChange,
  description,
  disabled,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  description?: string
  disabled?: boolean
}) {
  return (
    <Field orientation="horizontal">
      <div className="flex flex-1 flex-col gap-1">
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
        {description && <FieldDescription>{description}</FieldDescription>}
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </Field>
  )
}

/** Optional texts and settings that are dropped from the draft when empty. */
const OPTIONAL_KEYS = new Set([
  'description', 'placeholder', 'pattern', 'patternMessage', 'prefillParam', 'addLabel',
  'submitLabel', 'nextLabel', 'backLabel', 'successMessage', 'title', 'minDate', 'maxDate', 'attestation',
])

/** Remove unset keys so optional props don't linger as nulls or empty strings in the draft. */
function clean<T extends object>(obj: T): T {
  const out = { ...obj } as Record<string, unknown>
  for (const k of Object.keys(out))
    if (out[k] === undefined || out[k] === null || (out[k] === '' && OPTIONAL_KEYS.has(k))) delete out[k]
  return out as T
}

function useOpenGroups(kind: string, first: string) {
  const storageKey = `justforms.inspector.${kind}`
  const [open, setOpen] = useState<string[]>(() => {
    try {
      const saved = window.localStorage.getItem(storageKey)
      return saved ? (JSON.parse(saved) as string[]) : [first]
    } catch {
      return [first]
    }
  })
  return [
    open,
    (next: string[]) => {
      setOpen(next)
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(next))
      } catch {
        /* storage may be unavailable */
      }
    },
  ] as const
}

// -- options ---------------------------------------------------------------------------------

function OptionRow({
  option,
  index,
  onChange,
  onRemove,
  canRemove,
}: {
  option: Option
  index: number
  onChange: (label: string) => void
  onRemove: () => void
  canRemove: boolean
}) {
  const form = useBuilder((s) => s.schema)
  const { setNodeRef, transform, transition, isDragging, attributes, listeners } = useSortable({ id: option.value })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn('flex items-center gap-1', isDragging && 'relative z-10 opacity-80')}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            className="cursor-grab touch-none text-muted-foreground"
            aria-label={`Reorder option ${index + 1}`}
            {...attributes}
            {...listeners}
          >
            <GripVerticalIcon />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{`Reorder option ${index + 1}`}</TooltipContent>
      </Tooltip>
      <ContentInput
        aria-label={`Option ${index + 1}`}
        language={formLanguage(form)}
        value={option.label}
        placeholder={`Option ${index + 1}`}
        onChange={(e) => onChange(e.target.value)}
      />
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex" tabIndex={canRemove ? undefined : 0}>
            <Button variant="ghost" size="icon-sm" aria-label={`Remove option ${index + 1}`} disabled={!canRemove} onClick={onRemove}>
              <XIcon />
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent>{canRemove ? `Remove option ${index + 1}` : 'A question needs at least one option'}</TooltipContent>
      </Tooltip>
    </div>
  )
}

function OptionsEditor({ field, set }: { field: Extract<FieldElement, { options: Option[] }>; set: (o: [Option, ...Option[]]) => void }) {
  const form = useBuilder((s) => s.schema)
  const [paste, setPaste] = useState('')
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }))
  const options = field.options
  const nextValue = () => {
    const used = new Set(options.map((o) => o.value))
    let n = options.length + 1
    while (used.has(`option_${n}`)) n++
    return `option_${n}`
  }
  return (
    <FieldSet className="gap-2">
      <FieldLegend variant="label">Options</FieldLegend>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={({ active, over }) => {
          if (!over || active.id === over.id) return
          const from = options.findIndex((o) => o.value === active.id)
          const to = options.findIndex((o) => o.value === over.id)
          const next = [...options]
          const [moved] = next.splice(from, 1)
          next.splice(to, 0, moved)
          set(next as [Option, ...Option[]])
        }}
      >
        <SortableContext items={options.map((o) => o.value)} strategy={verticalListSortingStrategy}>
          {options.map((o, i) => (
            <OptionRow
              key={o.value}
              option={o}
              index={i}
              canRemove={options.length > 1}
              onChange={(label) => set(options.map((x, j) => (j === i ? { ...x, label } : x)) as [Option, ...Option[]])}
              onRemove={() => set(options.filter((_, j) => j !== i) as [Option, ...Option[]])}
            />
          ))}
        </SortableContext>
      </DndContext>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => set([...options, { value: nextValue(), label: '' }])}>
          <PlusIcon />
          Add option
        </Button>
        <Dialog onOpenChange={(open) => open && setPaste(options.map((o) => o.label).join('\n'))}>
          <DialogTrigger asChild>
            <Button variant="link" size="sm">
              Paste several
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Paste options</DialogTitle>
              <DialogDescription>One option per line. Existing options keep their place.</DialogDescription>
            </DialogHeader>
            <ContentTextarea
              rows={8}
              aria-label="Options, one per line"
              language={formLanguage(form)}
              value={paste}
              onChange={(e) => setPaste(e.target.value)}
            />
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">Cancel</Button>
              </DialogClose>
              <DialogClose asChild>
                <Button onClick={() => set(optionsFromText(options, paste))}>Use these options</Button>
              </DialogClose>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </FieldSet>
  )
}

// -- type-specific settings -------------------------------------------------------------------

const FILE_KINDS: { key: string; label: string; accept: string[] }[] = [
  { key: 'pdf', label: 'PDF', accept: ['application/pdf'] },
  { key: 'images', label: 'Images', accept: ['image/jpeg', 'image/png'] },
  {
    key: 'word',
    label: 'Word',
    accept: ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  },
  {
    key: 'excel',
    label: 'Excel',
    accept: ['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'text/csv'],
  },
]

const COUNTRY_CODES = ['MV', 'IN', 'LK', 'BD', 'PK', 'NP', 'AE', 'SA', 'MY', 'SG', 'TH', 'CN', 'GB', 'US', 'AU']

function DateBoundField({ id, label, value, onChange }: { id: string; label: string; value: string | null | undefined; onChange: (v: string | undefined) => void }) {
  const mode = !value ? 'none' : value === 'today' ? 'today' : value.startsWith('today') ? 'plus' : 'date'
  const days = mode === 'plus' ? Number(value!.slice(5)) : 30
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <NativeSelect
        id={id}
        className="w-full"
        value={mode}
        onChange={(e) => {
          const m = e.target.value
          onChange(m === 'none' ? undefined : m === 'today' ? 'today' : m === 'plus' ? 'today+30' : new Date().toISOString().slice(0, 10))
        }}
      >
        <NativeSelectOption value="none">No limit</NativeSelectOption>
        <NativeSelectOption value="today">Today</NativeSelectOption>
        <NativeSelectOption value="plus">Today plus a number of days</NativeSelectOption>
        <NativeSelectOption value="date">A date</NativeSelectOption>
      </NativeSelect>
      {mode === 'plus' && (
        <Input
          type="number"
          aria-label={`${label}: days from today`}
          value={days}
          onChange={(e) => {
            const n = Math.max(-9999, Math.min(9999, Math.round(Number(e.target.value) || 0)))
            onChange(n === 0 ? 'today' : `today${n > 0 ? '+' : ''}${n}`)
          }}
        />
      )}
      {mode === 'date' && (
        <Input type="date" aria-label={`${label}: date`} value={value!} onChange={(e) => onChange(e.target.value || undefined)} />
      )}
    </Field>
  )
}

function TypeSettings({ field, update }: { field: FieldElement; update: (patch: Partial<FieldElement>) => void }) {
  const set = (patch: object) => update(patch as Partial<FieldElement>)
  switch (field.type) {
    case 'single_choice':
      return (
        <>
          <OptionsEditor field={field} set={(options) => set({ options })} />
          <Field>
            <FieldLabel>Show as</FieldLabel>
            <ToggleGroup
              type="single"
              variant="outline"
              value={field.display ?? 'radio'}
              onValueChange={(v) => v && set({ display: v })}
              aria-label="Show as"
              className={toggleGroupOn}
            >
              <ToggleGroupItem value="radio">Buttons</ToggleGroupItem>
              <ToggleGroupItem value="dropdown">Dropdown</ToggleGroupItem>
            </ToggleGroup>
          </Field>
          <SwitchField id="allow-other" label="Allow 'Other'" checked={!!field.allowOther} onChange={(v) => set({ allowOther: v || undefined })} />
        </>
      )
    case 'multi_choice':
      return (
        <>
          <OptionsEditor field={field} set={(options) => set({ options })} />
          <div className="grid grid-cols-2 gap-3">
            <NumberField id="min-selected" label="At least" integer min={0} value={field.minSelected} onChange={(v) => set({ minSelected: v })} />
            <NumberField id="max-selected" label="At most" integer min={1} value={field.maxSelected} onChange={(v) => set({ maxSelected: v })} />
          </div>
        </>
      )
    case 'rating':
      return (
        <Field>
          <FieldLabel htmlFor="rating-max">Scale</FieldLabel>
          <NativeSelect id="rating-max" className="w-full" value={field.max ?? 5} onChange={(e) => set({ max: Number(e.target.value) })}>
            {[3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
              <NativeSelectOption key={n} value={n}>
                1 to {n}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </Field>
      )
    case 'number':
      return (
        <>
          <SwitchField id="integer" label="Whole numbers only" checked={!!field.integer} onChange={(v) => set({ integer: v || undefined })} />
          <div className="grid grid-cols-3 gap-3">
            <NumberField id="num-min" label="Min" value={field.min} onChange={(v) => set({ min: v })} />
            <NumberField id="num-max" label="Max" value={field.max} onChange={(v) => set({ max: v })} />
            <NumberField id="num-step" label="Step" min={0} value={field.step} onChange={(v) => set({ step: v && v > 0 ? v : undefined })} />
          </div>
        </>
      )
    case 'date':
      return (
        <>
          <DateBoundField id="min-date" label="Earliest" value={field.minDate} onChange={(v) => set({ minDate: v })} />
          <DateBoundField id="max-date" label="Latest" value={field.maxDate} onChange={(v) => set({ maxDate: v })} />
        </>
      )
    case 'phone':
      return (
        <Field>
          <FieldLabel htmlFor="country">Default country</FieldLabel>
          <NativeSelect id="country" className="w-full" value={field.defaultCountry ?? 'MV'} onChange={(e) => set({ defaultCountry: e.target.value })}>
            {COUNTRY_CODES.map((c) => (
              <NativeSelectOption key={c} value={c}>
                {c}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </Field>
      )
    case 'short_text':
    case 'long_text':
      return (
        <Field>
          <FieldLabel>Typing</FieldLabel>
          <ToggleGroup
            type="single"
            variant="outline"
            value={field.inputScript ?? 'auto'}
            onValueChange={(v) => v && set({ inputScript: v === 'auto' ? undefined : v })}
            aria-label="Typing"
            className={toggleGroupOn}
          >
            <ToggleGroupItem value="auto">Auto</ToggleGroupItem>
            <ToggleGroupItem value="latin">Latin</ToggleGroupItem>
            <ToggleGroupItem value="thaana">Thaana</ToggleGroupItem>
          </ToggleGroup>
          <FieldDescription>Thaana turns on the phonetic keyboard for this question.</FieldDescription>
        </Field>
      )
    case 'file': {
      const accept = field.accept ?? []
      const on = FILE_KINDS.filter((k) => k.accept.some((a) => accept.includes(a))).map((k) => k.key)
      return (
        <>
          <Field>
            <FieldLabel>Accepted files</FieldLabel>
            <ToggleGroup
              type="multiple"
              variant="outline"
              value={on}
              onValueChange={(keys) => set({ accept: FILE_KINDS.filter((k) => keys.includes(k.key)).flatMap((k) => k.accept) })}
              aria-label="Accepted files"
              className={cn('flex-wrap', toggleGroupOn)}
            >
              {FILE_KINDS.map((k) => (
                <ToggleGroupItem key={k.key} value={k.key}>
                  {k.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <FieldDescription>{on.length ? 'Only these types can be uploaded.' : 'Any file type can be uploaded.'}</FieldDescription>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <NumberField id="max-files" label="Max files" integer min={1} value={field.maxFiles ?? 1} onChange={(v) => set({ maxFiles: Math.max(1, Math.min(50, v ?? 1)) })} />
            <NumberField id="max-size" label="Max size (MB)" integer min={1} value={field.maxSizeMb} onChange={(v) => set({ maxSizeMb: v && v > 0 ? v : undefined })} />
          </div>
        </>
      )
    }
    case 'signature':
      return (
        <TextField
          id="attestation"
          label="Statement above the pad"
          content
          multiline
          value={field.attestation ?? ''}
          description="For example: I confirm the information in this form is true. It is printed with the signature in the signed PDF."
          onChange={(attestation) => set({ attestation })}
        />
      )
    case 'hidden':
      return (
        <TextField
          id="prefill"
          label="Fill from link parameter"
          mono
          value={field.prefillParam ?? ''}
          onChange={(v) => set({ prefillParam: v.replace(/[^A-Za-z0-9_.-]/g, '').slice(0, 64) || undefined })}
          description={field.prefillParam ? <span className="font-mono">?{field.prefillParam}=value</span> : 'The value comes from the form link, for example ?source=poster'}
        />
      )
    default:
      return null
  }
}

function PatternTester({ pattern }: { pattern: string }) {
  const [sample, setSample] = useState('')
  let ok: boolean | null = null
  try {
    ok = sample ? new RegExp(pattern, 'u').test(sample) : null
  } catch {
    ok = null
  }
  return (
    <Field>
      <FieldLabel htmlFor="pattern-test">Test</FieldLabel>
      <div className="flex items-center gap-2">
        <Input id="pattern-test" className="font-mono" value={sample} onChange={(e) => setSample(e.target.value)} />
        {ok !== null && <Badge variant={ok ? 'secondary' : 'destructive'}>{ok ? 'Matches' : "Doesn't match"}</Badge>}
      </div>
    </Field>
  )
}

/** Editors can mark a question sensitive, but only owners can turn it off once published. */
function SensitiveSwitch({ field, onChange }: { field: FieldElement; onChange: (v: boolean) => void }) {
  const role = useContext(FormContext)?.role
  const publishedSensitive = usePublishedSensitive()
  const locked = role !== undefined && role !== 'owner' && !!field.sensitive && publishedSensitive.has(field.id)
  return (
    <SwitchField
      id="el-sensitive"
      label="Sensitive"
      description={
        locked
          ? "Masked in tables and left out of emails and webhooks. Only the form's owner can turn this off."
          : 'Masked in tables and left out of emails and webhooks'
      }
      checked={!!field.sensitive}
      onChange={onChange}
      disabled={locked}
    />
  )
}

function KeyField({ el }: { el: Element }) {
  const store = useStore()
  const published = usePublished()
  const locked = published.has(el.id)
  const [draft, setDraft] = useState(el.id)
  const [error, setError] = useState<string | null>(null)
  const commit = () => {
    if (draft === el.id) return setError(null)
    if (!/^[a-z][a-z0-9_]{0,62}$/.test(draft)) return setError('Use lower-case letters, digits and _, starting with a letter')
    if (takenIds(store.get().schema).has(draft)) return setError('Another question already uses this key')
    setError(null)
    store.edit((f) => renameId(f, el.id, draft), { selection: { type: 'element', id: draft } })
  }
  return (
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor="el-key">
        Key {locked && <LockIcon className="size-3.5 text-muted-foreground" aria-label="Locked" />}
      </FieldLabel>
      <Input
        id="el-key"
        className="font-mono"
        dir="ltr"
        value={draft}
        disabled={locked}
        aria-invalid={error ? true : undefined}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
      />
      <FieldDescription>Used in exports and integrations. Locked after the form is first published.</FieldDescription>
      {error && <FieldError>{error}</FieldError>}
    </Field>
  )
}

// -- panels -----------------------------------------------------------------------------------

function useElementEdit(id: string) {
  const store = useStore()
  return (change: (el: Element) => Element) => store.edit((f) => updateElement(f, id, change))
}

function FieldPanel({ field, form }: { field: FieldElement; form: Form }) {
  const edit = useElementEdit(field.id)
  const update = (patch: Partial<FieldElement>) => edit((el) => clean({ ...el, ...patch } as Element))
  const [open, setOpen] = useOpenGroups('field', 'question')
  const rules = (field.visibleIf ? 1 : 0) + (field.requiredIf ? 1 : 0)
  const noPlaceholder = ['single_choice', 'multi_choice', 'yes_no', 'rating', 'file', 'hidden', 'signature'].includes(field.type)
  return (
    <Accordion type="multiple" value={open} onValueChange={setOpen}>
      <AccordionItem value="question">
        <AccordionTrigger>Question</AccordionTrigger>
        <AccordionContent>
          <FieldGroup className="gap-4">
            <TextField
              id="el-label"
              label="Label"
              content
              value={field.label}
              error={field.label.trim() ? null : 'Add a label so people know what to answer'}
              onChange={(label) => edit((el) => ({ ...el, label }) as Element)}
            />
            <TextField
              id="el-help"
              label="Help text"
              content
              multiline
              value={field.description ?? ''}
              description="Shown under the label. Bold, italic, links and lists are allowed."
              onChange={(description) => update({ description })}
            />
            {!noPlaceholder && (
              <TextField id="el-placeholder" label="Placeholder" content value={field.placeholder ?? ''} onChange={(placeholder) => update({ placeholder })} />
            )}
            {field.type !== 'hidden' && (
              <SwitchField
                id="el-required"
                label="Required"
                checked={!!field.required}
                onChange={(required) => edit((el) => clean({ ...el, required: required || undefined, requiredIf: undefined }) as Element)}
                description={field.requiredIf ? 'Required only when its rule matches (see Logic).' : undefined}
              />
            )}
            <TypeSettings field={field} update={update} />
          </FieldGroup>
        </AccordionContent>
      </AccordionItem>
      {field.type === 'short_text' && (
        <AccordionItem value="validation">
          <AccordionTrigger>Validation</AccordionTrigger>
          <AccordionContent>
            <FieldGroup className="gap-4">
              <NumberField id="max-length" label="Max length" integer min={1} value={field.maxLength} onChange={(maxLength) => update({ maxLength })} />
              <TextField id="pattern" label="Pattern" mono value={field.pattern ?? ''} onChange={(pattern) => update({ pattern })} description="A regular expression, for example ^A[0-9]{6}$" />
              <TextField
                id="pattern-message"
                label="Message when it doesn't match"
                content
                value={field.patternMessage ?? ''}
                onChange={(patternMessage) => update({ patternMessage })}
              />
              {field.pattern && <PatternTester pattern={field.pattern} />}
            </FieldGroup>
          </AccordionContent>
        </AccordionItem>
      )}
      {field.type === 'long_text' && (
        <AccordionItem value="validation">
          <AccordionTrigger>Validation</AccordionTrigger>
          <AccordionContent>
            <NumberField id="max-length" label="Max length" integer min={1} value={field.maxLength} onChange={(maxLength) => update({ maxLength })} />
          </AccordionContent>
        </AccordionItem>
      )}
      <AccordionItem value="logic">
        <AccordionTrigger id="inspector-logic">
          <span className="flex items-center gap-2">
            Logic {rules > 0 && <Badge variant="secondary">{rules}</Badge>}
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <FieldGroup className="gap-6">
            <VisibilityEditor
              key={`v-${field.id}`}
              form={form}
              ownerId={field.id}
              noun="question"
              cond={field.visibleIf}
              apply={(f, cond) => updateElement(f, field.id, (el) => clean({ ...el, visibleIf: cond ?? undefined }) as Element)}
            />
            {field.type !== 'hidden' && (
              <RequiredEditor
                key={`r-${field.id}`}
                form={form}
                field={field}
                apply={(f, { required, requiredIf }) =>
                  updateElement(f, field.id, (el) => clean({ ...el, required: required || undefined, requiredIf: requiredIf ?? undefined }) as Element)
                }
              />
            )}
          </FieldGroup>
        </AccordionContent>
      </AccordionItem>
      <AccordionItem value="advanced">
        <AccordionTrigger>Advanced</AccordionTrigger>
        <AccordionContent>
          <FieldGroup className="gap-4">
            <KeyField key={field.id} el={field} />
            <SensitiveSwitch field={field} onChange={(sensitive) => update({ sensitive: sensitive || undefined })} />
            <Field>
              <FieldLabel>Width</FieldLabel>
              <ToggleGroup type="single" variant="outline" value={field.width ?? 'full'} onValueChange={(v) => v && update({ width: v === 'full' ? undefined : 'half' })} aria-label="Width" className={toggleGroupOn}>
                <ToggleGroupItem value="full">Full</ToggleGroupItem>
                <ToggleGroupItem value="half">Half</ToggleGroupItem>
              </ToggleGroup>
              <FieldDescription>Two half-width questions sit side by side on wider screens.</FieldDescription>
            </Field>
            {field.type !== 'hidden' && (
              <TextField
                id="el-prefill"
                label="Prefill parameter"
                mono
                value={field.prefillParam ?? ''}
                onChange={(v) => update({ prefillParam: v.replace(/[^A-Za-z0-9_.-]/g, '').slice(0, 64) })}
                description="Fill this question from the link, for example ?name=Aminath"
              />
            )}
          </FieldGroup>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}

function ContainerPanel({ el, form }: { el: Extract<Element, { kind: 'section' | 'repeater' | 'content' }>; form: Form }) {
  const edit = useElementEdit(el.id)
  const update = (patch: object) => edit((x) => clean({ ...x, ...patch } as Element))
  const [open, setOpen] = useOpenGroups(el.kind, 'main')
  return (
    <Accordion type="multiple" value={open} onValueChange={setOpen}>
      <AccordionItem value="main">
        <AccordionTrigger>{el.kind === 'section' ? 'Section' : el.kind === 'repeater' ? 'Repeater' : 'Text'}</AccordionTrigger>
        <AccordionContent>
          <FieldGroup className="gap-4">
            {el.kind === 'section' && (
              <>
                <TextField id="sec-title" label="Title" content value={el.title ?? ''} onChange={(title) => edit((x) => ({ ...x, title }) as Element)} />
                <TextField id="sec-desc" label="Description" content multiline value={el.description ?? ''} onChange={(description) => update({ description })} />
              </>
            )}
            {el.kind === 'repeater' && (
              <>
                <TextField
                  id="rep-label"
                  label="Label"
                  content
                  value={el.label}
                  error={el.label.trim() ? null : 'Add a label so people know what to answer'}
                  onChange={(label) => edit((x) => ({ ...x, label }) as Element)}
                />
                <TextField id="rep-desc" label="Description" content multiline value={el.description ?? ''} onChange={(description) => update({ description })} />
                <TextField
                  id="rep-add"
                  label="Add button text"
                  content
                  value={el.addLabel ?? ''}
                  placeholder="Add entry"
                  onChange={(addLabel) => update({ addLabel })}
                  description="Rows are titled after it: “Add dependent” gives “Dependent 1”."
                />
                <div className="grid grid-cols-2 gap-3">
                  <NumberField id="min-rows" label="Minimum rows" integer min={0} value={el.minRows} onChange={(minRows) => update({ minRows })} />
                  <NumberField id="max-rows" label="Maximum rows" integer min={1} value={el.maxRows} onChange={(maxRows) => update({ maxRows })} />
                </div>
              </>
            )}
            {el.kind === 'content' &&
              (el.contentType === 'divider' ? (
                <p className="text-sm text-muted-foreground">A divider has no settings.</p>
              ) : (
                <TextField
                  id="content-text"
                  label={el.contentType === 'heading' ? 'Heading' : 'Text'}
                  content
                  multiline={el.contentType === 'paragraph'}
                  value={el.text ?? ''}
                  error={el.text?.trim() ? null : 'Add text or remove this block'}
                  description={el.contentType === 'paragraph' ? 'Bold, italic, links and lists are allowed.' : undefined}
                  onChange={(text) => edit((x) => ({ ...x, text }) as Element)}
                />
              ))}
          </FieldGroup>
        </AccordionContent>
      </AccordionItem>
      <AccordionItem value="logic">
        <AccordionTrigger id="inspector-logic">
          <span className="flex items-center gap-2">
            Logic {el.visibleIf && <Badge variant="secondary">1</Badge>}
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <VisibilityEditor
            key={`v-${el.id}`}
            form={form}
            ownerId={el.id}
            noun={el.kind === 'section' ? 'section' : el.kind === 'repeater' ? 'question' : 'block'}
            cond={el.visibleIf}
            apply={(f, cond) => updateElement(f, el.id, (x) => clean({ ...x, visibleIf: cond ?? undefined }) as Element)}
          />
        </AccordionContent>
      </AccordionItem>
      {el.kind === 'repeater' && (
        <AccordionItem value="advanced">
          <AccordionTrigger>Advanced</AccordionTrigger>
          <AccordionContent>
            <KeyField key={el.id} el={el} />
          </AccordionContent>
        </AccordionItem>
      )}
    </Accordion>
  )
}

function PagePanel({ pageIndex, form }: { pageIndex: number; form: Form }) {
  const store = useStore()
  const page = form.pages[pageIndex]
  const [open, setOpen] = useOpenGroups('page', 'page')
  const rules = (page.visibleIf ? 1 : 0) + (page.next?.length ?? 0)
  const setPage = (patch: object) => store.edit((f) => updatePage(f, pageIndex, (p) => clean({ ...p, ...patch })))
  return (
    <Accordion type="multiple" value={open} onValueChange={setOpen}>
      <AccordionItem value="page">
        <AccordionTrigger>Page</AccordionTrigger>
        <AccordionContent>
          <FieldGroup className="gap-4">
            <TextField id="page-title" label="Title" content value={page.title ?? ''} placeholder={`Page ${pageIndex + 1}`} onChange={(title) => setPage({ title })} />
            <TextField id="page-desc" label="Description" content multiline value={page.description ?? ''} onChange={(description) => setPage({ description })} />
          </FieldGroup>
        </AccordionContent>
      </AccordionItem>
      <AccordionItem value="logic">
        <AccordionTrigger id="inspector-logic">
          <span className="flex items-center gap-2">
            Logic {rules > 0 && <Badge variant="secondary">{rules}</Badge>}
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <FieldGroup className="gap-6">
            {pageIndex > 0 ? (
              <VisibilityEditor
                key={`pv-${page.id}`}
                form={form}
                ownerId={null}
                noun="page"
                cond={page.visibleIf}
                apply={(f, cond) => updatePage(f, pageIndex, (p) => clean({ ...p, visibleIf: cond ?? undefined }))}
              />
            ) : (
              <p className="text-sm text-muted-foreground">The first page is always shown.</p>
            )}
            {pageIndex < form.pages.length - 1 ? (
              <PageJumps key={`pj-${page.id}-${page.next?.length ?? 0}`} form={form} pageIndex={pageIndex} />
            ) : (
              <p className="text-sm text-muted-foreground">After the last page the form is submitted.</p>
            )}
          </FieldGroup>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}

function FormPanel({ form }: { form: Form }) {
  const store = useStore()
  const language = formLanguage(form)
  const setSettings = (patch: object) => store.edit((f) => ({ ...f, settings: clean({ ...f.settings, ...patch }) }))
  return (
    <FieldGroup className="gap-4 p-4">
      <TextField
        id="form-title"
        label="Title"
        content
        value={form.settings.title}
        error={form.settings.title.trim() ? null : 'Give the form a title'}
        onChange={(title) => store.edit((f) => ({ ...f, settings: { ...f.settings, title } }))}
      />
      <TextField id="form-desc" label="Description" content multiline value={form.settings.description ?? ''} onChange={(description) => setSettings({ description })} />
      <FieldSet>
        <FieldLegend variant="label">Form language</FieldLegend>
        <RadioGroup
          value={language}
          onValueChange={(v) => isFormLanguage(v) && store.edit((f) => ({ ...f, settings: { ...f.settings, language: v } }))}
        >
          <Field orientation="horizontal">
            <RadioGroupItem value="en" id="lang-en" />
            <FieldLabel htmlFor="lang-en" className="font-normal">
              English
            </FieldLabel>
          </Field>
          <Field orientation="horizontal">
            <RadioGroupItem value="dv" id="lang-dv" />
            <FieldLabel htmlFor="lang-dv" className="font-normal">
              Dhivehi
            </FieldLabel>
          </Field>
        </RadioGroup>
        <FieldDescription>Changing the language changes text direction. Existing text is kept.</FieldDescription>
      </FieldSet>
      <TextField id="form-next" label="Next button text" content value={form.settings.nextLabel ?? ''} placeholder={ltrRun(MSG.next)} onChange={(nextLabel) => setSettings({ nextLabel })} />
      <TextField id="form-back" label="Back button text" content value={form.settings.backLabel ?? ''} placeholder={ltrRun(MSG.back)} onChange={(backLabel) => setSettings({ backLabel })} />
      <TextField id="form-submit" label="Submit button text" content value={form.settings.submitLabel ?? ''} placeholder={ltrRun(MSG.submit)} onChange={(submitLabel) => setSettings({ submitLabel })} />
      <TextField id="form-success" label="Message after submitting" content multiline value={form.settings.successMessage ?? ''} placeholder={ltrRun(MSG.successDefault)} onChange={(successMessage) => setSettings({ successMessage })} />
    </FieldGroup>
  )
}

function PageMenu({ pageIndex }: { pageIndex: number }) {
  const menuTip = useMenuTooltip()
  const store = useStore()
  const count = useBuilder((s) => s.schema.pages.length)
  return (
    <DropdownMenu>
      <Tooltip {...menuTip.tooltip}>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Page actions">
              <EllipsisIcon />
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>Page actions</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" {...menuTip.content}>
        <DropdownMenuItem
          onSelect={() => {
            let id = ''
            store.edit((f) => {
              const out = duplicatePage(f, pageIndex)
              id = out.id
              return out.form
            })
            store.setPage(id)
          }}
        >
          Duplicate
        </DropdownMenuItem>
        <DropdownMenuItem disabled={pageIndex === 0} onSelect={() => store.edit((f) => movePage(f, pageIndex, pageIndex - 1))}>
          Move left
        </DropdownMenuItem>
        <DropdownMenuItem disabled={pageIndex === count - 1} onSelect={() => store.edit((f) => movePage(f, pageIndex, pageIndex + 1))}>
          Move right
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => {
            let id = ''
            store.edit((f) => {
              const out = addPage(f, pageIndex + 1)
              id = out.id
              return out.form
            })
            store.setPage(id)
          }}
        >
          Add page after
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" disabled={count <= 1} onSelect={() => store.setConfirm({ kind: 'page', pageIndex })}>
          Delete page
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function Inspector() {
  const menuTip = useMenuTooltip()
  const store = useStore()
  const form = useBuilder((s) => s.schema)
  const selection = useBuilder((s) => s.selection)
  const found = selection.type === 'element' ? findElement(form, selection.id) : null
  const pageIndex = selection.type === 'page' ? form.pages.findIndex((p) => p.id === selection.pageId) : -1

  let title: ReactNode
  let body: ReactNode
  let menu: ReactNode = null
  if (found) {
    const info = blockInfo(found.el)
    const Icon = info.icon
    title = (
      <>
        <Icon className="size-4 text-muted-foreground" />
        {info.label}
      </>
    )
    body =
      found.el.kind === 'field' ? (
        <FieldPanel key={found.el.id} field={found.el} form={form} />
      ) : (
        <ContainerPanel key={found.el.id} el={found.el} form={form} />
      )
    const id = found.el.id
    menu = (
      <DropdownMenu>
        <Tooltip {...menuTip.tooltip}>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Question actions">
                <EllipsisIcon />
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>Question actions</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="end" {...menuTip.content}>
          <DropdownMenuItem onSelect={() => duplicate(store, id)}>Duplicate</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => wrap(store, id)}>Wrap in section</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={() => requestDelete(store, id)}>
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    )
  } else if (pageIndex >= 0) {
    title = `Page ${pageIndex + 1}`
    body = <PagePanel key={form.pages[pageIndex].id} pageIndex={pageIndex} form={form} />
    menu = <PageMenu pageIndex={pageIndex} />
  } else {
    title = 'Form settings'
    body = <FormPanel form={form} />
  }

  return (
    <section aria-label="Question settings" className="flex h-full min-h-0 flex-col bg-card">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
        <h2 className="flex min-w-0 flex-1 items-center gap-2 text-sm font-medium" tabIndex={-1} id="inspector-heading">
          {title}
        </h2>
        {menu}
      </div>
      <ScrollArea className="min-h-0 flex-1 [&_[data-slot=scroll-area-viewport]>div]:block!">
        <div className={cn(found || pageIndex >= 0 ? 'px-4 pb-6' : '')}>{body}</div>
      </ScrollArea>
    </section>
  )
}

