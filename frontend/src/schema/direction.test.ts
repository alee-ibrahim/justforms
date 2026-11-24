// Shared direction vectors (spec/direction/vectors.json), also run by
// backend/tests (app/schemas/direction.py).
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { isolateRuns } from '@/thaana/runs'

import { parseForm } from '.'
import { alignClass } from './align'
import {
  explicitAlign,
  formDirection,
  resolveAlign,
  textDirection,
  textLang,
  textLines,
  type TextAlign,
  type TextDirection,
} from './direction'

interface Vectors {
  direction: { text: string; fallback?: TextDirection; dir: TextDirection; lang: 'dv' | 'en' }[]
  align: {
    align: TextAlign | null
    default: TextAlign | null
    dir: TextDirection
    result: string
    explicit: string | null
  }[]
  isolate: { text: string; dir?: TextDirection; runs: [string, TextDirection | null][] }[]
  lines: { text: string; fallback?: TextDirection; lines: { dir: TextDirection; lang: 'dv' | 'en' }[] }[]
}

const vectors = JSON.parse(
  readFileSync(path.resolve(__dirname, '../../../spec/direction/vectors.json'), 'utf8'),
) as Vectors

describe('textDirection / textLang (shared vectors)', () => {
  for (const v of vectors.direction)
    it(JSON.stringify(v.text), () => {
      expect(textDirection(v.text, v.fallback)).toBe(v.dir)
      expect(textLang(v.text)).toBe(v.lang)
    })
})

describe('resolveAlign (shared vectors)', () => {
  for (const v of vectors.align)
    it(`${v.align} / ${v.default} / ${v.dir}`, () => {
      expect(resolveAlign(v.align, v.default, v.dir)).toBe(v.result)
      expect(explicitAlign(v.align, v.default)).toBe(v.explicit)
    })
})

describe('isolateRuns (shared vectors)', () => {
  for (const v of vectors.isolate)
    it(JSON.stringify(v.text), () => {
      expect(isolateRuns(v.text, v.dir ?? textDirection(v.text)).map((r) => [r.text, r.dir])).toEqual(v.runs)
    })
})

describe('textLines (shared vectors)', () => {
  for (const v of vectors.lines)
    it(JSON.stringify(v.text), () => {
      expect(textLines(v.text, v.fallback).map(({ dir, lang }) => ({ dir, lang }))).toEqual(v.lines)
    })
})

describe('alignClass', () => {
  it('maps physical sides to logical classes for the block direction', () => {
    expect(alignClass('left', null, 'rtl')).toBe('text-end')
    expect(alignClass('right', null, 'rtl')).toBe('text-start')
    expect(alignClass(null, 'auto', 'rtl')).toBe('text-start')
    expect(alignClass('center', null, 'ltr')).toBe('text-center')
  })
})

describe('schemaVersion 2', () => {
  it('has no form language: a bilingual form with alignment parses', () => {
    const result = parseForm({
      schemaVersion: '2',
      settings: { title: 'Application / ހުށަހެޅުން', align: 'auto', titleAlign: 'center' },
      pages: [
        {
          id: 'page_1',
          align: 'right',
          elements: [{ kind: 'field', id: 'name', type: 'short_text', label: 'Name / ނަން', align: 'left' }],
        },
      ],
    })
    expect(result.ok).toBe(true)
    expect(parseForm({ schemaVersion: '2', settings: { title: 'T', language: 'dv' }, pages: [{ id: 'p' }] }).ok).toBe(
      false,
    )
  })

  it('lays the sheet out in the title direction', () => {
    expect(formDirection({ settings: { title: 'ފޯމު' } })).toBe('rtl')
    expect(formDirection({ settings: { title: 'Form / ފޯމު' } })).toBe('ltr')
  })
})
