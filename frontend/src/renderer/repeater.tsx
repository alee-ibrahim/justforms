/**
 * Repeating groups (PHASE-2-SCREENS 4.7): one card per row with add and remove. A lazy chunk of
 * the public form; the builder canvas imports it directly.
 */
import { PlusIcon, Trash2Icon } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { FieldLegend, FieldSet } from '@/components/ui/field'
import { cn } from '@/lib/utils'
import type { RepeaterElement } from '@/schema'
import { FormText } from '@/thaana/form-text'
import { textDirection, textLang } from '@/schema/direction'

import { useRenderer } from './context'
import { DESCRIPTION } from './elements'
import { Markdown } from './markdown'
import { fmt, MSG } from './messages'
import { En } from './msg'
import { placement, rowTitle } from './util'

function RowRemove({
  name,
  confirmNeeded,
  onRemove,
}: {
  name: string
  confirmNeeded: boolean
  onRemove: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  useEffect(() => {
    if (!confirming) return
    const t = window.setTimeout(() => setConfirming(false), 5000)
    return () => window.clearTimeout(t)
  }, [confirming])
  if (confirming)
    return (
      <div className="flex flex-wrap items-center gap-2" role="group" aria-live="polite">
        <span className="text-sm">
          <En>{fmt(MSG.removeRowConfirm, { name })}</En>
        </span>
        <Button type="button" variant="destructive" size="sm" onClick={onRemove}>
          <En>{MSG.remove}</En>
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => setConfirming(false)}>
          <En>{MSG.keep}</En>
        </Button>
      </div>
    )
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="text-destructive hover:text-destructive"
      onClick={() => (confirmNeeded ? setConfirming(true) : onRemove())}
      aria-label={fmt(MSG.removeFile, { name })}
      lang="en"
    >
      <Trash2Icon />
      <En>{MSG.remove}</En>
    </Button>
  )
}

export function RepeaterFrame({
  el,
  label,
  renderRow,
  sample,
  description,
  addText,
}: {
  el: RepeaterElement
  label?: ReactNode
  /** Builder: replaces the description (inline editing). */
  description?: ReactNode
  /** Builder: the add button's text, edited in place (the button itself does nothing). */
  addText?: ReactNode
  /** Fill mode: one row's questions. */
  renderRow?: (row: number) => ReactNode
  /** Canvas mode: the sample row's content. */
  sample?: ReactNode
}) {
  const ctx = useRenderer()
  const place = placement(el.label, el.align, ctx.form.settings.align, ctx.dir)
  const rows = ctx.mode === 'fill' ? ctx.rowCount(el.id) : 1
  const min = el.minRows ?? 0
  const max = el.maxRows ?? null
  const addLabel = el.addLabel?.trim()
  const rowHasAnswers = (row: number) =>
    (el.elements ?? []).some((child) => {
      const v = ctx.getValue({ id: child.id, repeater: el.id, row })
      return v !== undefined && v !== null && v !== ''
    })
  return (
    <FieldSet className="gap-3">
      <FieldLegend
        dir={place.dir}
        lang={place.lang}
        style={place.text}
        className={cn(
          'mb-0 w-full text-lg data-[variant=legend]:text-lg',
          place.lang === 'dv' ? 'font-normal' : 'font-semibold',
        )}
      >
        {label ?? <FormText text={el.label} />}
      </FieldLegend>
      {description !== undefined ? (
        description
      ) : (
        el.description && (
          <div dir={place.dir} lang={place.lang}>
            <Markdown text={el.description} className={DESCRIPTION} style={place.block} rtl={place.dir === 'rtl'} />
          </div>
        )
      )}
      {Array.from({ length: rows }, (_, row) => {
        // "Dependent 2" comes from the builder's English add label; "Entry 2" is system text.
        const custom = rowTitle(el, row + 1)
        const title = custom ?? fmt(MSG.entry, { n: row + 1 })
        return (
          <Card key={row} className="gap-4 rounded-md py-4 shadow-none ring-0 border" role="group" aria-label={title}>
            <CardHeader className="flex flex-row items-center justify-between gap-2 px-4">
              <CardTitle
                id={`${el.id}-row-${row}`}
                tabIndex={-1}
                dir={custom ? textDirection(custom, place.dir) : undefined}
                lang={custom ? textLang(custom) : undefined}
                className={cn('text-base outline-none', custom && textLang(custom) === 'dv' ? 'font-normal' : 'font-semibold')}
              >
                {custom ? <FormText text={custom} /> : <En>{title}</En>}
              </CardTitle>
              {ctx.mode === 'fill' && rows > min && (
                <RowRemove
                  name={title}
                  confirmNeeded={rowHasAnswers(row)}
                  onRemove={() => ctx.removeRow(el.id, row)}
                />
              )}
            </CardHeader>
            <CardContent className="px-4">{ctx.mode === 'fill' ? renderRow?.(row) : sample}</CardContent>
          </Card>
        )
      })}
      {addText !== undefined ? (
        <Button asChild variant="outline" className="h-12 text-base sm:h-11 max-sm:w-full sm:w-fit">
          <div>
            <PlusIcon />
            {addText}
          </div>
        </Button>
      ) : (
      <Button
        type="button"
        variant="outline"
        className="h-12 text-base sm:h-11 max-sm:w-full sm:w-fit"
        disabled={ctx.mode === 'canvas' || (max !== null && rows >= max)}
        onClick={() => ctx.addRow(el.id)}
      >
        <PlusIcon />
        {addLabel ? (
          <bdi dir={textDirection(addLabel)} lang={textLang(addLabel)}>
            <FormText text={addLabel} />
          </bdi>
        ) : (
          <En>{MSG.addEntry}</En>
        )}
      </Button>
      )}
      {max !== null && rows >= Math.max(1, max - 2) && (
        <p className="text-sm text-muted-foreground">
          <En>{fmt(MSG.upTo, { n: max })}</En>
        </p>
      )}
    </FieldSet>
  )
}

