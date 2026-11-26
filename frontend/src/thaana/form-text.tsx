/**
 * Inline form text that may mix English and Dhivehi ("Name / ނަން"). The surrounding element
 * carries the text's own `lang`/`dir` (`textProps`); here, runs in the *other* script are
 * marked so they get their own face and are isolated for bidi: Thaana runs inside English text
 * get `lang="dv" dir="rtl"`, Latin runs inside Dhivehi text `lang="en" dir="ltr"`.
 */
import { Fragment, type ReactNode } from 'react'

import { isMultiline, paragraphStyle, textDirection, textLines, type TextAlign, type TextDirection } from '@/schema/direction'

import { displayText } from './display'
import { bilingualParts, isMixed, isolateRuns, type BilingualParts } from './runs'

/**
 * `split`: a bilingual one-line text ("Full name: ފުރިހަމަ ނަން", `bilingualParts`) is shown as
 * its two parts in one row, English at the left and Dhivehi at the right (`Bilingual`). Only for
 * `auto` alignment; explicit left/center/right/justify keep the text in one piece.
 */
export function FormText({
  text,
  dir,
  split,
}: {
  text: string
  dir?: TextDirection
  split?: boolean | 'inline'
}): ReactNode {
  const parts = split ? bilingualParts(text) : null
  if (parts) return <Bilingual parts={parts} inline={split === 'inline'} />
  const shown = displayText(text)
  if (!isMixed(text)) return shown
  return <Isolated text={shown} dir={dir ?? textDirection(text)} />
}

/**
 * A bilingual text as two parts in one row: the English part left to right at the left, the
 * Dhivehi part right to left at the right (pushed there by its end margin, the left one in its own
 * direction, so it stays at the right when the row wraps to two lines on narrow widths). `end` follows the English part (the
 * question's required "*"). `inline`: a row as wide as its parts (buttons, chips).
 */
export function Bilingual({
  parts,
  end,
  inline,
}: {
  parts: BilingualParts
  end?: ReactNode
  inline?: boolean
}): ReactNode {
  return (
    <span
      dir="ltr"
      data-slot="bilingual"
      className={inline ? 'inline-flex flex-wrap items-baseline gap-x-2' : 'flex w-full flex-wrap items-baseline gap-x-6 gap-y-1'}
    >
      <span lang="en" dir="ltr" className="text-start" data-part="ltr">
        <FormText text={parts.ltr} />
        {end}
      </span>
      <span lang="dv" dir="rtl" className={inline ? 'text-start' : 'me-auto text-start'} data-part="rtl">
        <FormText text={parts.rtl} />
      </span>
    </span>
  )
}

/**
 * `text` (already prepared for display) in a block whose direction is `dir`: runs of the other
 * script are isolated in their own direction and language (`isolateRuns`), so brackets and
 * punctuation next to them stay on the side of the surrounding text.
 */
export function Isolated({ text, dir }: { text: string; dir: TextDirection }): ReactNode {
  return isolateRuns(text, dir).map((run, i) =>
    run.dir === null ? (
      <Fragment key={i}>{run.text}</Fragment>
    ) : run.dir === 'rtl' ? (
      <span key={i} lang="dv" dir="rtl" className="df-run">
        {run.text}
      </span>
    ) : (
      <span key={i} lang="en" dir="ltr">
        {run.text}
      </span>
    ),
  )
}

/**
 * Multi-line form text in a plain-text slot (a long answer, the success message): each line
 * break-separated paragraph is a block in its own direction and language, so an English
 * paragraph followed by Dhivehi ones reads left to right, then right to left. Lines without
 * letters take the whole text's direction (`fallback` when it has none). Single-line text is
 * plain `FormText` in its container's direction.
 *
 * `align`: `auto` aligns each paragraph to its own start edge, left/center/right apply to all;
 * omitted, the paragraphs inherit the container's `text-align`. `measure`: cap each paragraph
 * at a reading width (36em), placed on its alignment side.
 */
export function FormLines({
  text,
  align,
  measure,
  fallback,
}: {
  text: string
  align?: TextAlign
  measure?: boolean
  fallback?: TextDirection
}): ReactNode {
  if (!isMultiline(text)) return <FormText text={text} />
  const style = align || measure ? paragraphStyle(align ?? 'auto', measure) : undefined
  return textLines(text, fallback).map((line, i) => (
    <span key={i} className={measure ? 'block max-w-[36em]' : 'block'} dir={line.dir} lang={line.lang} style={style}>
      {line.text.trim() ? <FormText text={line.text} /> : <br />}
    </span>
  ))
}
