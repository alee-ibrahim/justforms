// @vitest-environment happy-dom
import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'

import { Accordion, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'

import { GroupContent } from './inspector-group'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null
let host: HTMLElement | null = null

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  root = null
  host = null
})

function Group() {
  const [cards, setCards] = useState(0)
  return (
    <Accordion type="multiple" defaultValue={['logic']}>
      <AccordionItem value="logic">
        <AccordionTrigger>Logic</AccordionTrigger>
        <GroupContent>
          <button type="button" aria-label="Add card" onClick={() => setCards((n) => n + 1)}>
            Add
          </button>
          {Array.from({ length: cards }, (_, i) => (
            <div key={i} data-testid="card" />
          ))}
        </GroupContent>
      </AccordionItem>
    </Accordion>
  )
}

describe('GroupContent', () => {
  it('lets an open group grow instead of pinning it to the height measured on open', () => {
    host = document.createElement('div')
    document.body.append(host)
    root = createRoot(host)
    act(() => root!.render(<Group />))
    act(() => host!.querySelector<HTMLButtonElement>('[aria-label="Add card"]')!.click())

    expect(host.querySelectorAll('[data-testid="card"]')).toHaveLength(1)
    const body = host.querySelector('[data-slot="accordion-content"] > div')!
    expect(body.classList.contains('h-auto')).toBe(true)
    expect([...body.classList].some((c) => c.includes('--radix-accordion-content-height'))).toBe(false)
  })
})
