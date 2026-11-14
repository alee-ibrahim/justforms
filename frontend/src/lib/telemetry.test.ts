// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'

import { errorOf } from './telemetry-error'

function rejection(reason: unknown): Event {
  const e = new Event('unhandledrejection')
  Object.defineProperty(e, 'reason', { value: reason })
  return e
}

describe('errorOf', () => {
  it('keeps the error object of an error event', () => {
    const error = new TypeError('boom')
    expect(errorOf(new ErrorEvent('error', { error, message: 'boom' }))).toBe(error)
  })

  it('gives an error event without an error object a readable message', () => {
    const e = errorOf(new ErrorEvent('error', { message: 'ResizeObserver loop completed with undelivered notifications.' }))
    expect(e).toBeInstanceOf(Error)
    expect(e.message).toBe('ResizeObserver loop completed with undelivered notifications.')
  })

  it('never reports undefined, even without a message', () => {
    const e = errorOf(new ErrorEvent('error'))
    expect(e).toBeInstanceOf(Error)
    expect(e.message).toBe('Error event without error object')
  })

  it('wraps a non-Error rejection reason', () => {
    expect(errorOf(rejection('nope')).message).toBe('Unhandled rejection: nope')
    expect(errorOf(rejection(undefined)).message).toBe('Unhandled rejection: undefined')
    const error = new Error('real')
    expect(errorOf(rejection(error))).toBe(error)
  })
})
