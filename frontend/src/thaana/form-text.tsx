/**
 * Inline form text that may mix English and Dhivehi ("Name / ނަން"). The surrounding element
 * carries the text's own `lang`/`dir` (`textProps`); here, runs in the *other* script are
 * marked so they get their own face and are isolated for bidi: Thaana runs inside English text
 * get `lang="dv" dir="rtl"`, Latin runs inside Dhivehi text `lang="en" dir="ltr"`.
 */
import { Fragment, type ReactNode } from 'react'

import { isMultiline, paragraphStyle, textDirection, textLines, type TextAlign, type TextDirection } from '@/schema/direction'

import { displayText } from './display'
import { isMixed, scriptRuns } from './runs'

export function FormText({ text }: { text: string }): ReactNode {
  const shown = displayText(text)
  if (!isMixed(text)) return shown
  const rtl = textDirection(text) === 'rtl'
  const minority = rtl ? 'latin' : 'thaana'
  return scriptRuns(shown).map((run, i) => {
    if (run.script !== minority) return <Fragment key={i}>{run.text}</Fragment>
    return run.script === 'thaana' ? (
      <span key={i} lang="dv" dir="rtl" className="df-run">
        {run.text}
      </span>
    ) : (
      <span key={i} lang="en" dir="ltr">
        {run.text}
      </span>
    )
  })
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
