// Cycle detector fixtures (spec/logic/cycles), also run by backend/tests/test_logic_cycles.py.
import { expect, it } from 'vitest'

import { parseForm, type Form } from '@/schema'

import { buildIndex } from './form-index'
import { buildGraph, findCycle } from './graph'
import { loadSpecDir } from './spec-files'

const fixtures = loadSpecDir<{ name: string; expect: 'cycle' | 'ok'; schema: Form }>('logic/cycles')

it('has at least 10 cyclic fixtures', () => {
  expect(fixtures.filter((f) => f.data.expect === 'cycle').length).toBeGreaterThanOrEqual(10)
})

for (const { data } of fixtures) {
  it(`${data.name} (${data.expect})`, () => {
    expect(parseForm(data.schema).ok).toBe(true)
    const cycle = findCycle(buildGraph(buildIndex(data.schema)))
    if (data.expect === 'cycle') expect(cycle).not.toBeNull()
    else expect(cycle).toBeNull()
  })
}
