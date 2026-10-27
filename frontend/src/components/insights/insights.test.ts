import { describe, expect, it } from 'vitest'

import { validateSubmissionsSearch } from '@/components/submissions/search'
import { filterParams } from '@/lib/api'

import type { Form } from '@/schema'

import { askErrorText, plain, type ChartSpec } from './api'
import { askExamples, fieldLabels } from './ask-examples'
import { isSubmissionsPath } from './ask-state'
import { listCsv, listTsv, sortRows } from './list-data'
import { fileName } from './png'

describe('conditions in the Submissions URL', () => {
  it('keeps valid conditions and drops anything else', () => {
    const s = validateSubmissionsSearch({
      where: [
        { field: 'areas', op: 'includes_any', values: ['disability'] },
        { field: '_status', op: 'eq', value: 'new' },
        { field: 'Bad Key', op: 'eq', value: 1 },
        { field: 'x', op: 'eq', value: { nested: true } },
        'nope',
      ],
      whereLabel: 'Topics: Disability rights',
    })
    expect(s.where).toEqual([
      { field: 'areas', op: 'includes_any', values: ['disability'] },
      { field: '_status', op: 'eq', value: 'new' },
    ])
    expect(s.whereLabel).toBe('Topics: Disability rights')
    expect(validateSubmissionsSearch({ where: [] }).where).toBeUndefined()
  })

  it('sends them to the API as one JSON parameter', () => {
    const qs = filterParams({ status: 'new', where: [{ field: 'staff', op: 'gte', value: 5 }] })
    expect(qs.get('status')).toBe('new')
    expect(JSON.parse(qs.get('where') ?? '')).toEqual({ where: [{ field: 'staff', op: 'gte', value: 5 }], whereAny: [] })
    expect(filterParams({}).has('where')).toBe(false)
  })
})

describe('Insights helpers', () => {
  it('names PNG files after the question', () => {
    expect(fileName('How useful was the last workshop?')).toBe('how-useful-was-the-last-workshop.png')
    expect(fileName('ތާނަ')).toBe('chart.png')
  })

  it('shows replies as plain text', () => {
    expect(plain('**14 of 42** ticked it\n## Notes\n- a')).toBe('14 of 42 ticked it\nNotes\n- a')
  })

  it('explains errors in plain words', () => {
    expect(askErrorText('ai_budget_exceeded')).toMatch(/allowance/)
    expect(askErrorText('something_else')).toBe("Couldn't get an answer. Try again.")
  })
})

describe('Ask your submissions', () => {
  const schema = {
    schemaVersion: '1',
    settings: { title: 'CSO registration' },
    pages: [
      {
        id: 'p1',
        elements: [
          { kind: 'field', id: 'org_name', type: 'short_text', label: 'Organisation name' },
          {
            kind: 'field',
            id: 'areas',
            type: 'multi_choice',
            label: 'Tick the policy areas your organisation works on, as many as apply',
            options: [
              { value: 'human_rights', label: 'HUMAN RIGHTS AND GENDER' },
              { value: 'climate', label: 'Climate' },
            ],
          },
          { kind: 'field', id: 'staff', type: 'number', label: 'Staff' },
        ],
      },
    ],
  } as unknown as Form

  it('suggests questions built from the form’s choice questions', () => {
    expect(askExamples(schema)).toEqual([
      'How many ticked “HUMAN RIGHTS AND GENDER”?',
      'Who ticked “Climate”?',
      'Breakdown by “Tick the policy areas your organisation works…”',
      'What is the average “Staff”?',
    ])
    expect(askExamples(undefined)).toEqual(['How many submissions came in each month?'])
    expect(fieldLabels(schema).get('areas')).toMatch(/^Tick the policy areas/)
  })

  it('suggests listing contact details when the form asks for them', () => {
    const withPhone = {
      ...schema,
      pages: [
        {
          id: 'p1',
          elements: [
            ...(schema.pages[0].elements as unknown[]),
            { kind: 'field', id: 'phone', type: 'phone', label: 'Contact number' },
          ],
        },
      ],
    } as unknown as Form
    expect(askExamples(withPhone)[1]).toBe('List the contact details of every submission')
  })

  it('opens from the Submissions pages only', () => {
    expect(isSubmissionsPath('/forms/abc/submissions')).toBe(true)
    expect(isSubmissionsPath('/forms/abc/submissions/insights')).toBe(true)
    expect(isSubmissionsPath('/forms/abc/submissions/12')).toBe(true)
    expect(isSubmissionsPath('/forms/abc/submissions/import')).toBe(false)
    expect(isSubmissionsPath('/forms/abc/edit')).toBe(false)
  })

  it('explains an unexpected failure', () => {
    expect(askErrorText('internal')).toMatch(/Try again/)
  })
})

describe('Listed submissions', () => {
  const chart: ChartSpec = {
    queryId: 'q1',
    display: 'list',
    title: 'CSO contacts',
    unit: 'submissions',
    columns: ['org', 'phone'],
    columnLabels: { org: 'Organisation, name', phone: 'Phone' },
    rows: [
      { label: '#3', ref: 3, values: { org: 'beta "B"', phone: '+9607771234' } },
      { label: '#12', ref: 12, values: { org: 'Alpha', phone: null } },
      { label: '#7', ref: 7, values: { org: '=HYPERLINK("x")', phone: '+960 333 4444' } },
    ],
    total: 3,
    truncated: false,
  }

  it('sorts by a column, unanswered last, numbers by value', () => {
    expect(sortRows(chart.rows, { col: 'org', dir: 'asc' }).map((r) => r.ref)).toEqual([7, 12, 3])
    expect(sortRows(chart.rows, { col: 'phone', dir: 'desc' }).map((r) => r.ref)).toEqual([3, 7, 12])
    expect(sortRows(chart.rows, { col: '_ref', dir: 'asc' }).map((r) => r.ref)).toEqual([3, 7, 12])
    expect(sortRows(chart.rows, null)).toBe(chart.rows)
  })

  it('copies tab-separated and downloads safe CSV with the exact values', () => {
    expect(listTsv(chart, chart.rows).split('\n')[1]).toBe('#3\tbeta "B"\t+9607771234')
    const csv = listCsv(chart, chart.rows)
    expect(csv.startsWith('\ufeffNumber,"Organisation, name",Phone\r\n')).toBe(true)
    expect(csv).toContain('#3,"beta ""B""",+9607771234\r\n')
    expect(csv).toContain('#12,Alpha,\r\n')
    // A formula is defused; a phone number is left as it is.
    expect(csv).toContain(`#7,"'=HYPERLINK(""x"")",+960 333 4444`)
  })

  it('defuses formulas in the tab-separated copy too', () => {
    const tsv = listTsv(chart, chart.rows).split('\n')
    expect(tsv[3]).toBe(`#7\t'=HYPERLINK("x")\t+960 333 4444`)
    const evil: ChartSpec = {
      ...chart,
      rows: [{ label: '#1', ref: 1, values: { org: '@SUM(A1)', phone: '-2+3' } }],
    }
    expect(listTsv(evil, evil.rows).split('\n')[1]).toBe(`#1\t'@SUM(A1)\t'-2+3`)
  })
})
