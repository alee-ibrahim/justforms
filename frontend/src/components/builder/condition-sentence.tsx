import { Fragment, type ReactNode } from 'react'

import type { Condition, Form } from '@/schema'
import { textLang } from '@/schema/direction'

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
  return (
    <>
      {prefix}
      {prefix && ' '}
      {piecesOf(cond, form, false).map((p, i) =>
        p.content ? (
          <bdi key={i} dir="auto" lang={textLang(p.text)}>
            {p.text}
          </bdi>
        ) : (
          <Fragment key={i}>{p.text}</Fragment>
        ),
      )}
    </>
  )
}
