// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'

import { contentHeight, postHeight } from './embed'

describe('embedded form height', () => {
  afterEach(() => vi.restoreAllMocks())

  it('measures the content, rounded up so a fraction never scrolls', () => {
    const el = document.createElement('div')
    vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({ height: 1681.25 } as DOMRect)
    expect(contentHeight(el)).toBe(1682)
    expect(contentHeight(null)).toBe(0)
  })

  it('posts at most once a frame, and only when the height changed', () => {
    const root = document.createElement('div')
    root.id = 'root'
    document.body.append(root)
    let height = 900
    vi.spyOn(root, 'getBoundingClientRect').mockImplementation(() => ({ height }) as DOMRect)
    const parent = { postMessage: vi.fn() }
    vi.spyOn(window, 'parent', 'get').mockReturnValue(parent as unknown as Window)
    const frames: FrameRequestCallback[] = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => frames.push(cb))
    const flush = () => frames.splice(0).forEach((cb) => cb(0))

    postHeight()
    postHeight()
    flush()
    expect(parent.postMessage).toHaveBeenCalledTimes(1)
    expect(parent.postMessage).toHaveBeenCalledWith({ type: 'justforms:resize', height: 900 }, '*')
    postHeight()
    flush()
    expect(parent.postMessage).toHaveBeenCalledTimes(1)
    height = 600
    postHeight()
    flush()
    expect(parent.postMessage).toHaveBeenLastCalledWith({ type: 'justforms:resize', height: 600 }, '*')
  })
})
