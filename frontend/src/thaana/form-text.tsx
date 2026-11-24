/**
 * Inline form text that may mix English and Dhivehi ("Name / ނަން"). The surrounding element
 * carries the text's own `lang`/`dir` (`textProps`); here, runs in the *other* script are
 * marked so they get their own face and are isolated for bidi: Thaana runs inside English text
 * get `lang="dv" dir="rtl"`, Latin runs inside Dhivehi text `lang="en" dir="ltr"`.
 */
import { Fragment, type ReactNode } from 'react'

import { textDirection } from '@/schema/direction'

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
