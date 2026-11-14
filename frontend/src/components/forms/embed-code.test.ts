// @vitest-environment happy-dom
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { embedCode } from './embed-code'

describe('embedCode', () => {
  it('inline: a working iframe plus the resize helper from the form site', () => {
    const code = embedCode('inline', 'https://forms.example.org/my-form', 'Sign "up" & <go>')
    expect(code).toContain('<iframe src="https://forms.example.org/my-form?embed=1"')
    expect(code).toContain('title="Sign &quot;up&quot; &amp; &lt;go>"')
    expect(code).toContain('height:800px')
    expect(code).toContain('<script src="https://forms.example.org/embed.js" async></script>')
  })

  it('full page: the normal page filling the window, no helper', () => {
    const code = embedCode('full', 'https://forms.example.org/my-form', 'Form')
    expect(code).toContain('src="https://forms.example.org/my-form"')
    expect(code).not.toContain('embed=1')
    expect(code).not.toContain('<script')
  })
})

// public/embed.js runs on other websites: it only obeys its own origin's frames.
describe('embed.js', () => {
  const ORIGIN = 'https://forms.example.org'
  const source = readFileSync(path.resolve(__dirname, '../../../public/embed.js'), 'utf8')

  function setup() {
    delete (window as { __justformsEmbed?: boolean }).__justformsEmbed
    Object.defineProperty(document, 'currentScript', { value: { src: `${ORIGIN}/embed.js` }, configurable: true })
    new Function(source)()
    const frame = document.createElement('iframe')
    const child = {} as Window
    Object.defineProperty(frame, 'contentWindow', { value: child })
    // Not added to the page (the test DOM would try to load it): the script finds it here.
    vi.spyOn(document, 'getElementsByTagName').mockReturnValue([frame] as unknown as HTMLCollectionOf<HTMLIFrameElement>)
    const send = (data: unknown, origin = ORIGIN, from: unknown = child) =>
      window.dispatchEvent(new MessageEvent('message', { data, origin, source: from as Window }))
    return { frame, send }
  }

  afterEach(() => vi.restoreAllMocks())

  it('sizes the frame that sent the height and stops its own scrolling', () => {
    const { frame, send } = setup()
    send({ type: 'justforms:resize', height: 1234.2 })
    expect(frame.style.height).toBe('1235px')
    expect(frame.getAttribute('scrolling')).toBe('no')
  })

  it('ignores other origins, unknown windows and silly heights', () => {
    const { frame, send } = setup()
    send({ type: 'justforms:resize', height: 500 }, 'https://evil.example')
    send({ type: 'justforms:resize', height: 500 }, ORIGIN, {})
    send({ type: 'justforms:resize', height: -1 })
    send({ type: 'justforms:resize', height: 'x' })
    send({ type: 'justforms:resize', height: 1e9 })
    expect(frame.style.height).toBe('')
  })

  it('scrolls to the frame only when its top is out of view', () => {
    const { frame, send } = setup()
    const scroll = vi.fn()
    frame.scrollIntoView = scroll
    vi.spyOn(frame, 'getBoundingClientRect').mockReturnValue({ top: 10 } as DOMRect)
    send({ type: 'justforms:top' })
    expect(scroll).not.toHaveBeenCalled()
    vi.spyOn(frame, 'getBoundingClientRect').mockReturnValue({ top: -400 } as DOMRect)
    send({ type: 'justforms:top' })
    expect(scroll).toHaveBeenCalledWith({ block: 'start' })
  })
})
