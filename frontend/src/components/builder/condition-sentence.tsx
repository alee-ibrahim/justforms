import { Fragment, type ReactNode } from 'react'

import type { Condition, Form } from '@/schema'
import { contentProps, formLanguage } from '@/schema/language'

import { piecesOf } from './logic-text'

/** The condition as a sentence; question labels and values keep the form's script. */
export function ConditionSentence({
  cond,
  form,
  prefix,
}: {
  cond: Condition
  form: Form
  prefix?: string
}): ReactNode {
  const lang = contentProps(formLanguage(form)).lang
  return (
    <>
      {prefix}
      {prefix && ' '}
      {piecesOf(cond, form, false).map((p, i) =>
        p.content ? (
          <bdi key={i} dir="auto" lang={lang}>
            {p.text}
          </bdi>
        ) : (
          <Fragment key={i}>{p.text}</Fragment>
        ),
      )}
    </>
  )
}
