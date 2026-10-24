// Shared logic conformance suite: spec/logic/vectors/*.json, also run by
// backend/tests/test_logic_vectors.py (see that file for the format).
import { describe, expect, it } from 'vitest'

import type { Form } from '@/schema'

import { evaluate, type Evaluation } from './engine'
import { loadSpecDir } from './spec-files'

interface Lists {
  visible?: string[]
  hidden?: string[]
  required?: string[]
  notRequired?: string[]
}
interface Expect extends Lists {
  path?: string[]
  strippedAnswers?: Record<string, unknown>
  rows?: Record<string, Lists[]>
}
interface VectorFile {
  name: string
  schema: Form
  cases: { name: string; answers: Record<string, unknown>; expect: Expect }[]
}

const files = loadSpecDir<VectorFile>('logic/vectors')
const MIN_VECTORS = 150

function checkLists(where: string, exp: Lists, visible: string[], hidden: string[], required: string[]) {
  for (const el of exp.visible ?? []) expect(visible, `${where}: ${el} visible`).toContain(el)
  for (const el of exp.hidden ?? []) expect(hidden, `${where}: ${el} hidden`).toContain(el)
  for (const el of exp.required ?? []) expect(required, `${where}: ${el} required`).toContain(el)
  for (const el of exp.notRequired ?? [])
    expect(required, `${where}: ${el} not required`).not.toContain(el)
}

function check(result: Evaluation, exp: Expect) {
  checkLists('top level', exp, result.visible, result.hidden, result.required)
  if (exp.path) expect(result.path).toEqual(exp.path)
  if (exp.strippedAnswers) expect(result.strippedAnswers).toStrictEqual(exp.strippedAnswers)
  for (const [rep, rows] of Object.entries(exp.rows ?? {})) {
    const actual = result.rows[rep] ?? []
    expect(actual.length, `repeater ${rep}: row count`).toBe(rows.length)
    rows.forEach((row, i) =>
      checkLists(`${rep}[${i}]`, row, actual[i].visible, actual[i].hidden, actual[i].required),
    )
  }
}

it(`has at least ${MIN_VECTORS} vectors`, () => {
  const total = files.reduce((n, f) => n + f.data.cases.length, 0)
  expect(total).toBeGreaterThanOrEqual(MIN_VECTORS)
})

for (const { data } of files) {
  describe(data.name, () => {
    for (const c of data.cases) {
      it(c.name, () => check(evaluate(data.schema, c.answers), c.expect))
    }
  })
}
