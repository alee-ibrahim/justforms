/**
 * Restricted Markdown for help text and text blocks: **bold**, _italic_ / *italic*,
 * [links](https://...) and "- " lists. Produces React nodes, never HTML strings.
 */
import { isolateNumbers } from '@yashau/thaana-react'
import type { ReactNode } from 'react'

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)\s]+\))/g

function safeHref(href: string): string | null {
  return /^(https?:|mailto:|tel:)/i.test(href) ? href : null
}

function inline(text: string, key: string, rtl = false): ReactNode[] {
  const show = (s: string) => (rtl ? isolateNumbers(s, true) : s)
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

/** Paragraphs separated by blank lines; consecutive "- " lines become a list. */
/** `rtl`: isolate numbers and phone numbers inside Dhivehi text (display only). */
export function Markdown({
  text,
  className,
  id,
  rtl,
}: {
  text: string
  className?: string
  id?: string
  rtl?: boolean
}) {
  const blocks = text.trim().split(/\n{2,}/)
  return (
    <div id={id} className={className}>
      {blocks.map((block, b) => {
        const lines = block.split('\n')
        if (lines.every((l) => /^\s*[-*]\s+/.test(l)))
          return (
            <ul key={b} className="ms-5 list-disc">
              {lines.map((l, i) => (
                <li key={i}>{inline(l.replace(/^\s*[-*]\s+/, ''), `${b}-${i}`, rtl)}</li>
              ))}
            </ul>
          )
        return (
          <p key={b} className="[&+*]:mt-2">
            {lines.map((l, i) => (
              <span key={i}>
                {i > 0 && <br />}
                {inline(l, `${b}-${i}`, rtl)}
              </span>
            ))}
          </p>
        )
      })}
    </div>
  )
}
