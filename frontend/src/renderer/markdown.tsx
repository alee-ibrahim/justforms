/**
 * Restricted Markdown for help text and text blocks: **bold**, _italic_ / *italic*,
 * [links](https://...) and "- " lists. Produces React nodes, never HTML strings.
 */
import type { CSSProperties, ReactNode } from 'react'

import { textDirection, textLang } from '@/schema/direction'
import { isolateNumbers } from '@/thaana/display'

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)\s]+\))/g

function safeHref(href: string): string | null {
  return /^(https?:|mailto:|tel:)/i.test(href) ? href : null
}

function inline(text: string, key: string, rtl = false): ReactNode[] {
  const show = (s: string) => (rtl ? isolateNumbers(s) : s)
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
    return show(part)
  })
}

/**
 * Paragraphs separated by blank lines; consecutive "- " lines become a list. Each paragraph and
 * list item takes its own direction from its text (English and Dhivehi may alternate), and
 * numbers inside right-to-left lines are isolated (display only). `rtl`: the direction of
 * lines without letters.
 */
export function Markdown({
  text,
  className,
  id,
  rtl,
  style,
}: {
  text: string
  className?: string
  id?: string
  rtl?: boolean
  style?: CSSProperties
}) {
  const blocks = text.trim().split(/\n{2,}/)
  return (
    <div id={id} className={className} style={style}>
      {blocks.map((block, b) => {
        const lines = block.split('\n')
        const fallback = rtl ? 'rtl' : 'ltr'
        if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
          const items = lines.map((l) => l.replace(/^\s*[-*]\s+/, ''))
          return (
            <ul key={b} className="list-disc ps-5" dir={textDirection(items[0], fallback)}>
              {items.map((l, i) => {
                const dir = textDirection(l, fallback)
                return (
                  <li key={i} dir={dir} lang={textLang(l)}>
                    {inline(l, `${b}-${i}`, dir === 'rtl')}
                  </li>
                )
              })}
            </ul>
          )
        }
        const dir = textDirection(block, fallback)
        return (
          <p key={b} className="[&+*]:mt-2" dir={dir} lang={textLang(block)}>
            {lines.map((l, i) => (
              <span key={i}>
                {i > 0 && <br />}
                {inline(l, `${b}-${i}`, textDirection(l, dir) === 'rtl')}
              </span>
            ))}
          </p>
        )
      })}
    </div>
  )
}
