import { Fragment, type ReactNode } from 'react'

/**
 * System text (always English) inside a form that may be Dhivehi. The page direction follows the
 * form's content (RTL for `dv`), so English chrome is isolated as a left-to-right, `lang="en"`
 * run: punctuation and numbers stay in place, the Latin face is used (index.css), screen readers
 * switch voice, and the run still sits at the start (right) edge of an RTL block.
 */
export function En({ children }: { children: ReactNode }): ReactNode {
  return (
    <bdi dir="ltr" lang="en">
      {children}
    </bdi>
  )
}

/** Render a message template with `{name}` placeholders filled by nodes, as an `<En>` run. */
export function Msg({
  t,
  params = {},
}: {
  t: string
  params?: Record<string, ReactNode>
}): ReactNode {
  return (
    <En>
      {t.split(/(\{\w+\})/).map((part, i) => {
        const m = /^\{(\w+)\}$/.exec(part)
        return <Fragment key={i}>{m && m[1] in params ? params[m[1]] : part}</Fragment>
      })}
    </En>
  )
}
