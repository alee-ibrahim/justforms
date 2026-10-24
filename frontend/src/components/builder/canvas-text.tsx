/**
 * Canvas pieces that edit form text in place (docs/ux/INLINE-EDIT-AND-LOGO-SCREENS.md §1):
 * placeholders inside the answer box, choice options, the Back / Next / Submit buttons and the
 * message after submitting. Composed from official shadcn components; the answer controls stay
 * the renderer's own, inert.
 */
import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVerticalIcon, PlusIcon, XIcon } from 'lucide-react'
import { type KeyboardEvent, type ReactNode } from 'react'
import { flushSync } from 'react-dom'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { FieldContent, FieldLabel, Field as UiField, FieldTitle } from '@/components/ui/field'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { useRenderer } from '@/renderer/context'
import { FieldControl } from '@/renderer/fields'
import { ltrRun, MSG } from '@/renderer/messages'
import type { FieldElement, Form, Option } from '@/schema'
import type { FormLanguage } from '@/schema/language'

import { focusInlineText, insertOption, moveOption, removeOption, renameOption, setAllowOther, setSettingsText, textKey } from './inline-edit'
import { type EditControls, InlineText } from './inline-text'
import { useActivate, useBuilder, useStore } from './store'
import { updateElement } from './tree'


/** An English run inside form content (default button texts and the like). */
function En({ children }: { children: ReactNode }) {
  return (
    <bdi lang="en" dir="ltr">
      {children}
    </bdi>
  )
}

// -- placeholders ------------------------------------------------------------------------------


/** The answer box with its placeholder edited in place ("Add placeholder text…" when selected). */
export function PlaceholderControl({ field, active }: { field: FieldElement; active: boolean }) {
  const store = useStore()
  const { language } = useRenderer()
  const activate = useActivate({ type: 'element', id: field.id })
  const value = ('placeholder' in field ? field.placeholder : undefined) ?? ''
  const shown = { ...field, placeholder: value || (active ? ltrRun('Add placeholder text…') : undefined) } as FieldElement
  const latin = field.type === 'email' || field.type === 'phone' || field.type === 'number'
  return (
    <InlineText
      editKey={textKey.element(field.id, 'placeholder')}
      value={value}
      name="placeholder"
      language={latin ? 'en' : language}
      variant="box"
      block
      multiline={field.type === 'long_text'}
      active={active}
      activate={activate}
      placeholder="Placeholder text"
      frame={
        <div inert aria-hidden className="pointer-events-none">
          <FieldControl field={shown} path={{ id: field.id }} invalid={false} />
        </div>
      }
      onCommit={(text) => store.edit((f) => setPlaceholder(f, field.id, text))}
    />
  )
}

function setPlaceholder(form: Form, id: string, text: string): Form {
  return updateElement(form, id, (el) => {
    const out = { ...el } as Record<string, unknown>
    if (text.trim()) out.placeholder = text
    else delete out.placeholder
    return out as unknown as typeof el
  })
}

// -- options -----------------------------------------------------------------------------------

type ChoiceField = Extract<FieldElement, { type: 'single_choice' | 'multi_choice' }>

/** The radio or checkbox the respondent will see, inert (it is only a picture here). */
function Mark({ multi }: { multi: boolean }) {
  return (
    <div inert aria-hidden className="pointer-events-none flex">
      {multi ? (
        <Checkbox tabIndex={-1} />
      ) : (
        <RadioGroup tabIndex={-1}>
          <RadioGroupItem value="x" tabIndex={-1} />
        </RadioGroup>
      )}
    </div>
  )
}

/** One row looking like the renderer's choice card, with the label edited in place. */
function OptionRow({
  field,
  option,
  index,
  active,
  compact,
}: {
  field: ChoiceField
  option: Option
  index: number
  active: boolean
  compact: boolean
}) {
  const store = useStore()
  const { language } = useRenderer()
  const activate = useActivate({ type: 'element', id: field.id })
  const { setNodeRef, setActivatorNodeRef, transform, transition, isDragging, attributes, listeners } = useSortable({
    id: option.value,
  })
  const options = field.options
  const key = textKey.option(field.id, option.value)

  const move = (delta: number) => {
    store.edit((f) => moveOption(f, field.id, option.value, delta))
  }
  const onEditKey = (e: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>, c: EditControls) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      c.finish(true)
      flushSync(() => store.setEditing(textKey.newOption(field.id, index)))
      return true
    }
    if (e.key === 'Backspace' && c.draft === '' && options.length > 1) {
      e.preventDefault()
      const prev = options[index - 1] ?? options[index + 1]
      c.finish(false)
      store.edit((f) => removeOption(f, field.id, option.value))
      flushSync(() => store.setEditing(textKey.option(field.id, prev.value)))
      return true
    }
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault()
      c.finish(true)
      move(e.key === 'ArrowUp' ? -1 : 1)
      flushSync(() => store.setEditing(key))
      return true
    }
    return false
  }
  const onIdleKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault()
      e.stopPropagation()
      move(e.key === 'ArrowUp' ? -1 : 1)
      focusInlineText(key)
      return true
    }
    return false
  }

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn('relative flex items-center gap-1', isDragging && 'z-10 opacity-80')}
    >
      {active && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              ref={setActivatorNodeRef}
              variant="ghost"
              size="icon-sm"
              lang="en"
              className="shrink-0 cursor-grab touch-none text-muted-foreground"
              aria-label={`Reorder option ${index + 1}`}
              {...attributes}
              {...listeners}
              onClick={(e) => e.stopPropagation()}
            >
              <GripVerticalIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Drag to reorder, or press Alt+↑ / Alt+↓</TooltipContent>
        </Tooltip>
      )}
      <OptionFrame compact={compact} mark={<Mark multi={field.type === 'multi_choice'} />}>
        <InlineText
          editKey={key}
          value={option.label}
          name={`option ${index + 1}`}
          language={language}
          active={active}
          activate={activate}
          empty={`Option ${index + 1}`}
          placeholder={`Option ${index + 1}`}
          className="w-full"
          block
          onEditKey={onEditKey}
          onIdleKey={onIdleKey}
          onCommit={(text) => store.edit((f) => renameOption(f, field.id, option.value, text))}
        />
      </OptionFrame>
      {active && (
        <RemoveButton
          label={`Remove option ${index + 1}`}
          disabled={options.length < 2}
          disabledReason="A question needs at least one option"
          onClick={() => store.edit((f) => removeOption(f, field.id, option.value))}
        />
      )}
    </div>
  )
}

function OptionFrame({ compact, mark, children }: { compact: boolean; mark: ReactNode; children: ReactNode }) {
  if (compact)
    return (
      <div className="flex min-h-11 min-w-0 flex-1 items-center gap-3 px-1 text-base">
        <span aria-hidden className="text-muted-foreground">
          •
        </span>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    )
  return (
    <FieldLabel className="min-w-0 flex-1">
      <UiField orientation="horizontal" className="min-h-12 items-center gap-3">
        {mark}
        <FieldContent>
          <FieldTitle className="w-full text-base font-normal">{children}</FieldTitle>
        </FieldContent>
      </UiField>
    </FieldLabel>
  )
}

function RemoveButton({
  label,
  disabled,
  disabledReason,
  onClick,
}: {
  label: string
  disabled?: boolean
  disabledReason?: string
  onClick: () => void
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex" tabIndex={disabled ? 0 : undefined} lang="en">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            disabled={disabled}
            onClick={(e) => {
              e.stopPropagation()
              onClick()
            }}
          >
            <XIcon />
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent>{disabled ? disabledReason : label}</TooltipContent>
    </Tooltip>
  )
}

/** A new option typed after position `after`; committing it adds it (one undo step). */
function NewOptionRow({ field, after, compact }: { field: ChoiceField; after: number; compact: boolean }) {
  const store = useStore()
  const { language } = useRenderer()
  const position = after + 2
  // Spacers where the other rows have their grip and remove buttons, so the cards line up.
  const spacer = <span aria-hidden className="w-8 shrink-0 pointer-coarse:w-11" />
  return (
    <div className="flex items-center gap-1">
      {spacer}
      <OptionFrame compact={compact} mark={<Mark multi={field.type === 'multi_choice'} />}>
        <InlineText
          editKey={textKey.newOption(field.id, after)}
          value=""
          name={`new option ${position}`}
          language={language}
          placeholder={`Option ${position}`}
          className="w-full"
          block
          onEditKey={(e, c) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              if (!c.draft.trim()) {
                c.finish(false, false)
                return true
              }
              c.finish(true)
              flushSync(() => store.setEditing(textKey.newOption(field.id, after + 1)))
              return true
            }
            if (e.key === 'Backspace' && c.draft === '') {
              e.preventDefault()
              c.finish(false)
              const prev = field.options[after]
              if (prev) flushSync(() => store.setEditing(textKey.option(field.id, prev.value)))
              return true
            }
            return false
          }}
          onCommit={(text) => {
            if (text.trim()) store.edit((f) => insertOption(f, field.id, after, text).form)
          }}
        />
      </OptionFrame>
      {spacer}
    </div>
  )
}

export function OptionList({ field, active }: { field: ChoiceField; active: boolean }) {
  const store = useStore()
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }))
  const editing = useBuilder((st) => st.editing)
  const dropdown = field.type === 'single_choice' && field.display === 'dropdown'
  const options = field.options
  const prefix = `opt-new:${field.id}:`
  const newAfter = editing?.startsWith(prefix) ? Number(editing.slice(prefix.length)) : null

  const rows = options.map((o, i) => (
    <div key={o.value} className="contents">
      <OptionRow field={field} option={o} index={i} active={active} compact={dropdown} />
      {newAfter === i && <NewOptionRow field={field} after={i} compact={dropdown} />}
    </div>
  ))
  if (dropdown && !active)
    // Idle: exactly the live dropdown; its options are edited once the question is selected.
    return (
      <div inert aria-hidden className="pointer-events-none">
        <FieldControl field={field} path={{ id: field.id }} invalid={false} />
      </div>
    )
  return (
    <div className="flex flex-col gap-2">
      {dropdown && (
        <>
          <div inert aria-hidden className="pointer-events-none">
            <FieldControl field={field} path={{ id: field.id }} invalid={false} />
          </div>
          <p className="text-sm text-muted-foreground" lang="en" dir="ltr">
            Options in the list
          </p>
        </>
      )}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={({ active: a, over }) => {
          if (!over || a.id === over.id) return
          const from = options.findIndex((o) => o.value === a.id)
          const to = options.findIndex((o) => o.value === over.id)
          store.edit((f) => moveOption(f, field.id, String(a.id), to - from))
        }}
      >
        <SortableContext items={options.map((o) => o.value)} strategy={verticalListSortingStrategy}>
          {rows}
        </SortableContext>
      </DndContext>
      {newAfter === -1 && <NewOptionRow field={field} after={-1} compact={dropdown} />}
      {field.allowOther && (
        <div className="flex items-center gap-1">
          {active && <span aria-hidden className="w-8 shrink-0 pointer-coarse:w-11" />}
          <OptionFrame compact={dropdown} mark={<Mark multi={field.type === 'multi_choice'} />}>
            <En>{MSG.other}</En>
          </OptionFrame>
          {active && <RemoveButton label="Remove “Other”" onClick={() => store.edit((f) => setAllowOther(f, field.id, false))} />}
        </div>
      )}
      {active && (
        <div className="flex flex-wrap gap-1" lang="en" dir="ltr">
          <Button
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              flushSync(() => store.setEditing(textKey.newOption(field.id, options.length - 1)))
            }}
          >
            <PlusIcon />
            Add option
          </Button>
          {!field.allowOther && (
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation()
                store.edit((f) => setAllowOther(f, field.id, true))
              }}
            >
              <PlusIcon />
              Add “Other”
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

// -- buttons and the message after submitting ---------------------------------------------------

/** Back / Next / Submit at the bottom of the sheet, as on the live page, with their text edited
 * in place (form settings). */
export function NavPreview({ form, pageIndex, language }: { form: Form; pageIndex: number; language: FormLanguage }) {
  const store = useStore()
  const activate = useActivate({ type: 'form' })
  const last = pageIndex === form.pages.length - 1
  const s = form.settings
  const button = (part: 'backLabel' | 'nextLabel' | 'submitLabel', fallback: string, name: string) => (
    <InlineText
      editKey={textKey.settings(part)}
      value={s[part] ?? ''}
      name={name}
      language={language}
      activate={activate}
      empty={<En>{fallback}</En>}
      placeholder={fallback}
      inputClassName="min-w-24 text-center placeholder:text-current placeholder:opacity-70"
      onCommit={(text) => store.edit((f) => setSettingsText(f, part, text))}
    />
  )
  return (
    <div className="flex items-center gap-3 border-t pt-6" onClick={(e) => {
        e.stopPropagation()
        store.select({ type: 'form' }, { inspect: true })
      }}>
      {pageIndex > 0 && (
        <Button asChild variant="outline" className="h-12 px-4 text-base">
          <div>{button('backLabel', MSG.back, 'Back button text')}</div>
        </Button>
      )}
      <Button asChild className="ms-auto h-12 px-5 text-base">
        <div>{last ? button('submitLabel', MSG.submit, 'Submit button text') : button('nextLabel', MSG.next, 'Next button text')}</div>
      </Button>
    </div>
  )
}

export function SuccessPreview({ form, language }: { form: Form; language: FormLanguage }) {
  const store = useStore()
  const activate = useActivate({ type: 'form' })
  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-dashed p-4"
      onClick={(e) => {
        e.stopPropagation()
        store.select({ type: 'form' }, { inspect: true })
      }}
    >
      <p className="text-sm text-muted-foreground" lang="en" dir="ltr">
        Shown after submitting
      </p>
      <div className="text-2xl font-bold">
        <InlineText
          editKey={textKey.settings('successMessage')}
          value={form.settings.successMessage ?? ''}
          name="message after submitting"
          language={language}
          multiline
          activate={activate}
          empty={<En>{MSG.successDefault}</En>}
          placeholder={MSG.successDefault}
          onCommit={(text) => store.edit((f) => setSettingsText(f, 'successMessage', text))}
        />
      </div>
    </div>
  )
}
