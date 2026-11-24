/**
 * Restricted Markdown for help text and text blocks: **bold**, _italic_ / *italic*,
 * [links](https://...) and "- " lists. Produces React nodes, never HTML strings.
 */
import { Fragment, type CSSProperties, type ReactNode } from 'react'

import { paragraphStyle, textDirection, textLang, type TextAlign, type TextDirection } from '@/schema/direction'
import { isolateNumbers } from '@/thaana/display'
import { Isolated } from '@/thaana/form-text'

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)\s]+\))/g
const ITEM = /^\s*[-*]\s+/

function safeHref(href: string): string | null {
  return /^(https?:|mailto:|tel:)/i.test(href) ? href : null
}

function inline(text: string, key: string, rtl = false): ReactNode[] {
  // Numbers in right-to-left lines and runs of the other script are isolated (display only).
  const show = (s: string): ReactNode => <Isolated text={rtl ? isolateNumbers(s) : s} dir={rtl ? 'rtl' : 'ltr'} />
  return text.split(INLINE).map((part, i) => {
    const k = `${key}-${i}`
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
      return <strong key={k}>{show(part.slice(2, -2))}</strong>
    if (
      ((part.startsWith('*') && part.endsWith('*')) ||
        (part.startsWith('_') && part.endsWith('_'))) &&
      part.length > 2
    )
      return <em key={k}>{show(part.slice(1, -1))}</em>
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part)
    if (link) {
      const href = safeHref(link[2])
      return href ? (
        <a
          key={k}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline underline-offset-4"
        >
          {link[1]}
        </a>
      ) : (
        link[1]
      )
    }
    return <Fragment key={k}>{show(part)}</Fragment>
  })
}

interface Run {
  dir: TextDirection
  lines: string[]
}

/** Consecutive lines with the same direction, in order. */
function runs(lines: string[], base: TextDirection): Run[] {
  const out: Run[] = []
  for (const line of lines) {
    const dir = textDirection(line, base)
    const last = out[out.length - 1]
    if (last && last.dir === dir) last.lines.push(line)
    else out.push({ dir, lines: [line] })
  }
  return out
}

/**
 * Paragraphs separated by blank lines; consecutive "- " lines become a list. Direction is
 * resolved per line (each line break-separated paragraph, English and Dhivehi may alternate):
 * consecutive lines in one direction share a paragraph, a line in the other direction starts
 * its own. Lines without letters take the whole text's direction (`rtl`: its fallback), as
 * `unicode-bidi: plaintext` does in the editors. Numbers inside right-to-left lines are
 * isolated (display only).
 *
 * `align`: `auto` aligns each paragraph to its own start edge; left/center/right apply to all.
 * `measure`: cap each paragraph at a reading width (36em), placed on its alignment side.
 */
export function Markdown({
  text,
  className,
  id,
  rtl,
  style,
  align,
  measure,
}: {
  text: string
  className?: string
  id?: string
  rtl?: boolean
  style?: CSSProperties
  align?: TextAlign
  measure?: boolean
}) {
  const base = textDirection(text, rtl ? 'rtl' : 'ltr')
  const para = align || measure ? paragraphStyle(align ?? 'auto', measure) : undefined
  const width = measure ? 'max-w-[36em]' : undefined
  const blocks = text
    .replace(/\r\n?/g, '\n')
    .trim()
    .split(/\n[ \t]*\n\s*/)
  const out: ReactNode[] = []
  blocks.forEach((block, b) => {
    const lines = block.split('\n')
    const list = lines.every((l) => ITEM.test(l))
    runs(list ? lines.map((l) => l.replace(ITEM, '')) : lines, base).forEach((run, r) => {
      const key = `${b}-${r}`
      const gap = b > 0 && r === 0 ? 'mt-2' : undefined
      const cls = [gap, width].filter(Boolean).join(' ') || undefined
      const lang = textLang(run.lines.join(' '))
      const rtlRun = run.dir === 'rtl'
      if (list)
        out.push(
          <ul key={key} className={['list-disc ps-5', cls].filter(Boolean).join(' ')} dir={run.dir} lang={lang} style={para}>
            {run.lines.map((l, i) => (
              <li key={i} lang={textLang(l)}>
                {inline(l, `${key}-${i}`, rtlRun)}
              </li>
            ))}
          </ul>,
        )
      else
        out.push(
          <p key={key} className={cls} dir={run.dir} lang={lang} style={para}>
            {run.lines.map((l, i) => (
              <span key={i}>
                {i > 0 && <br />}
                {inline(l, `${key}-${i}`, rtlRun)}
              </span>
            ))}
          </p>,
        )
    })
  })
  return (
    <div id={id} className={className} style={style}>
      {out}
    </div>
  )
}
