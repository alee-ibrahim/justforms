/**
 * Questions, sections, repeaters and content blocks (PHASE-2-SCREENS 4.5 to 4.7). The same
 * pieces render the public form and, inert, the builder canvas (WYSIWYG).
 */
import { lazy, Suspense, type ReactNode } from 'react'

import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import type {
  ContentElement,
  Element,
  FieldElement,
  SectionElement,
} from '@/schema'

import { type AnswerPath, controlId, pathKey, useRenderer } from './context'
import { FieldControl } from './fields'
import { Markdown } from './markdown'
import { displayText } from '@/thaana/display'

import { MSG } from './messages'
import { En } from './msg'
import { isGroupControl, widthClass } from './util'

/** Help text may hold lists and paragraphs, so it is a div styled like FieldDescription. */
export const DESCRIPTION = 'max-w-xl text-base text-muted-foreground'

/** Grid that pairs half-width questions on ≥ sm and stacks them on phones. */
export function QuestionGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('grid gap-[var(--df-gap,2rem)] @min-[32rem]:grid-cols-2', className)}>{children}</div>
}

/** "(optional)" / "(required)" after the label, per the form's convention. */
function RequirementMark({ required }: { required: boolean }) {
  const { convention } = useRenderer()
  const show = convention === 'optional' ? !required : required
  if (!show) return null
  return (
    <span className="font-normal text-muted-foreground">
      {' '}
      <En>{convention === 'optional' ? MSG.optional : MSG.required}</En>
    </span>
  )
}

export function QuestionView({
  field,
  path,
  required,
  label,
  extra,
  description,
  control: controlOverride,
}: {
  field: FieldElement
  path: AnswerPath
  required: boolean
  /** Builder: replaces the label text (inline editing). */
  label?: ReactNode
  /** Builder: badges after the label and its requirement mark. */
  extra?: ReactNode
  /** Builder: replaces the help text (inline editing). */
  description?: ReactNode
  /** Builder: replaces the inert control (placeholder and options edited in place). */
  control?: ReactNode
}) {
  const ctx = useRenderer()
  const cid = controlId(path)
  const error = ctx.mode === 'fill' ? ctx.errorFor(path) : null
  const invalid = error !== null
  const labelId = `${cid}-label`
  const descId = field.description ? `${cid}-desc` : undefined
  const errId = invalid ? `${cid}-err` : undefined
  const describedBy = [errId, descId].filter(Boolean).join(' ') || undefined
  const group = isGroupControl(field)
  const labelClass = cn(
    'text-lg leading-snug',
    ctx.language === 'dv' ? 'font-normal' : 'font-semibold',
    invalid && 'text-destructive',
  )
  // Half-width pairs: the control sits at the bottom of the cell so a neighbour's help text or
  // badge doesn't push one input below the other.
  const half = field.width === 'half'
  const labelText = label ?? (field.label.trim() ? displayText(field.label, ctx.language) : null)
  const heading = (
    <>
      {labelText}
      <RequirementMark required={required} />
      {extra}
    </>
  )
  const control = (
    <FieldControl
      field={field}
      path={path}
      invalid={invalid}
      describedBy={describedBy}
      labelledBy={labelId}
    />
  )
  const body = (
    <>
      {description !== undefined
        ? description
        : field.description && (
            <Markdown id={descId} text={field.description} className={DESCRIPTION} rtl={ctx.language === 'dv'} />
          )}
      {invalid && (
        <FieldError id={errId} className="text-base">
          {/* System messages are English runs; a builder's own pattern message is content. */}
          {error && /[\u0780-\u07bf]/.test(error) ? error : <En>{error}</En>}
        </FieldError>
      )}
      {controlOverride !== undefined ? (
        half ? <div className="mt-auto flex flex-col gap-2">{controlOverride}</div> : controlOverride
      ) : ctx.mode === 'canvas' ? (
        // The builder canvas shows the real control, inert, so clicks select the block.
        <div inert className={cn('pointer-events-none', half && 'mt-auto')}>
          {control}
        </div>
      ) : half ? (
        <div className="mt-auto flex flex-col gap-2">{control}</div>
      ) : (
        control
      )}
    </>
  )
  // The error marker is drawn in the gutter (a pseudo-element), so the question keeps its width
  // and nothing moves when errors appear. Only the label and the message turn red: help text and
  // a signing statement must not read as part of the error.
  const frame = cn(
    'relative gap-2 rounded-sm transition-colors motion-reduce:transition-none data-[invalid=true]:text-foreground',
    half && 'h-full',
    invalid &&
      'before:absolute before:inset-y-0 before:-start-[15px] before:w-[3px] before:rounded-full before:bg-destructive',
    ctx.highlighted.has(field.id) && 'bg-marker-wash -mx-2 px-2 py-2',
  )
  if (group)
    return (
      <FieldSet className={frame} data-invalid={invalid || undefined}>
        <FieldLegend id={labelId} className={cn(labelClass, 'mb-0 data-[variant=legend]:text-lg')}>
          {heading}
        </FieldLegend>
        {body}
      </FieldSet>
    )
  return (
    <Field className={frame} data-invalid={invalid || undefined}>
      <FieldLabel htmlFor={cid} id={labelId} className={cn(labelClass, 'block w-full')}>
        {heading}
      </FieldLabel>
      {body}
    </Field>
  )
}

export function ContentView({ el, placeholder }: { el: ContentElement; placeholder?: ReactNode }) {
  const { language } = useRenderer()
  switch (el.contentType) {
    case 'heading':
      return <h3 className="text-xl font-semibold tracking-tight">{el.text ? displayText(el.text, language) : placeholder}</h3>
    case 'paragraph':
      return el.text ? (
        <Markdown text={el.text} className="max-w-xl text-base" rtl={language === 'dv'} />
      ) : (
        <p className="text-base">{placeholder}</p>
      )
    case 'divider':
      return <Separator className="my-2" />
    case 'image':
      return placeholder ? <div className="h-24 rounded-md border border-dashed" /> : null
  }
}

export function SectionFrame({
  el,
  children,
  title,
  description,
}: {
  el: SectionElement
  children: ReactNode
  title?: ReactNode
  /** Builder: replaces the description (inline editing). */
  description?: ReactNode
}) {
  const { language } = useRenderer()
  return (
    <FieldSet className="gap-4">
      {(title ?? el.title) && (
        <FieldLegend
          className={cn(
            'mb-0 text-lg data-[variant=legend]:text-lg',
            language === 'dv' ? 'font-normal' : 'font-semibold',
          )}
        >
          {title ?? displayText(el.title ?? '', language)}
        </FieldLegend>
      )}
      {description !== undefined
        ? description
        : el.description && <Markdown text={el.description} className={DESCRIPTION} rtl={language === 'dv'} />}
      <FieldGroup className="gap-[var(--df-gap,2rem)] @min-[32rem]:border-s @min-[32rem]:ps-4">{children}</FieldGroup>
    </FieldSet>
  )
}

// Repeaters are uncommon: their frame (cards, add and remove buttons) is a lazy chunk.
const RepeaterFrame = lazy(() => import('./repeater').then((m) => ({ default: m.RepeaterFrame })))

/** Fill mode: renders the visible elements of a list (optionally inside a repeater row). */
export function FillElements({
  elements,
  scope,
}: {
  elements: Element[]
  scope?: { repeater: string; row: number }
}) {
  const ctx = useRenderer()
  const visible = elements.filter((el) => ctx.isVisible(el.id, scope))
  return (
    <QuestionGrid>
      {visible.map((el) => (
        <div key={el.id} className={cn('min-w-0', widthClass(el), el.kind === 'field' && el.type === 'hidden' && 'hidden')}>
          <FillElement el={el} scope={scope} />
        </div>
      ))}
    </QuestionGrid>
  )
}

function FillElement({ el, scope }: { el: Element; scope?: { repeater: string; row: number } }) {
  const ctx = useRenderer()
  switch (el.kind) {
    case 'field': {
      if (el.type === 'hidden') return null
      const path: AnswerPath = scope ? { id: el.id, ...scope } : { id: el.id }
      return <QuestionView key={pathKey(path)} field={el} path={path} required={ctx.isRequired(el.id, scope)} />
    }
    case 'content':
      return <ContentView el={el} />
    case 'section':
      return (
        <SectionFrame el={el}>
          <FillElements elements={el.elements ?? []} scope={scope} />
        </SectionFrame>
      )
    case 'repeater':
      return (
        <Suspense fallback={null}>
          <RepeaterFrame
            el={el}
            renderRow={(row) => (
              <FillElements elements={el.elements ?? []} scope={{ repeater: el.id, row }} />
            )}
          />
        </Suspense>
      )
  }
}
