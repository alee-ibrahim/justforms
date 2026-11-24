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
import { DirectionProvider } from '@/components/ui/direction'
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
import { FormText } from '@/thaana/form-text'

import { MSG } from './messages'
import { En } from './msg'
import { isGroupControl, placement, widthClass } from './util'

/** Help text may hold lists and paragraphs, so it is a div styled like FieldDescription. */
export const DESCRIPTION = 'max-w-[36em] text-base text-muted-foreground'

/** Grid that pairs half-width questions on ≥ sm and stacks them on phones. */
export function QuestionGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('grid gap-[var(--df-space,2rem)] @min-[32rem]:grid-cols-2', className)}>{children}</div>
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
  // The question is one block in its label's direction (Thaana right to left, English left to
  // right), aligned by its own `align` or the form default.
  const place = placement(field.label, field.align, ctx.form.settings.align, ctx.dir)
  const labelClass = cn(
    'text-lg leading-snug',
    place.lang === 'dv' ? 'font-normal' : 'font-semibold',
    invalid && 'text-destructive',
  )
  // Half-width pairs: the control sits at the bottom of the cell so a neighbour's help text or
  // badge doesn't push one input below the other.
  const half = field.width === 'half'
  const labelText = label ?? (field.label.trim() ? <FormText text={field.label} /> : null)
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
            <Markdown id={descId} text={field.description} className={DESCRIPTION} style={place.block} rtl={place.dir === 'rtl'} />
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
      <DirectionProvider dir={place.dir}>
        <FieldSet className={frame} data-invalid={invalid || undefined} dir={place.dir} lang={place.lang} style={place.text}>
          <FieldLegend id={labelId} className={cn(labelClass, 'mb-0 w-full data-[variant=legend]:text-lg')}>
            {heading}
          </FieldLegend>
          {body}
        </FieldSet>
      </DirectionProvider>
    )
  return (
    <DirectionProvider dir={place.dir}>
      <Field className={frame} data-invalid={invalid || undefined} dir={place.dir} lang={place.lang} style={place.text}>
        <FieldLabel htmlFor={cid} id={labelId} className={cn(labelClass, 'block w-full')}>
          {heading}
        </FieldLabel>
        {body}
      </Field>
    </DirectionProvider>
  )
}

export function ContentView({ el, placeholder }: { el: ContentElement; placeholder?: ReactNode }) {
  const { form, dir } = useRenderer()
  const place = placement(el.text, el.align, form.settings.align, dir)
  switch (el.contentType) {
    case 'heading':
      return (
        <h3
          dir={place.dir}
          lang={place.lang}
          style={place.text}
          className={cn('text-xl', place.lang === 'dv' ? 'font-normal' : 'font-semibold tracking-tight')}
        >
          {el.text ? <FormText text={el.text} /> : placeholder}
        </h3>
      )
    case 'paragraph':
      return el.text ? (
        <div dir={place.dir} lang={place.lang}>
          <Markdown text={el.text} className="max-w-[36em] text-base" style={place.block} rtl={place.dir === 'rtl'} />
        </div>
      ) : (
        <p className="text-base" dir={place.dir} style={place.text}>
          {placeholder}
        </p>
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
  const { form, dir } = useRenderer()
  const place = placement(el.title || el.description, el.align, form.settings.align, dir)
  // The heading block takes the section's direction; its questions each take their own.
  return (
    <FieldSet className="gap-4">
      {(title ?? el.title) && (
        <FieldLegend
          dir={place.dir}
          lang={place.lang}
          style={place.text}
          className={cn(
            'mb-0 w-full text-lg data-[variant=legend]:text-lg',
            place.lang === 'dv' ? 'font-normal' : 'font-semibold',
          )}
        >
          {title ?? <FormText text={el.title ?? ''} />}
        </FieldLegend>
      )}
      {description !== undefined ? (
        description
      ) : (
        el.description && (
          <div dir={place.dir} lang={place.lang}>
            <Markdown text={el.description} className={DESCRIPTION} style={place.block} rtl={place.dir === 'rtl'} />
          </div>
        )
      )}
      <FieldGroup className="gap-[var(--df-space,2rem)] @min-[32rem]:border-s @min-[32rem]:ps-4">{children}</FieldGroup>
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
