import { describe, expect, it } from 'vitest'

import { activeNav } from './form-nav'

describe('activeNav', () => {
  it.each([
    ['/forms/abc/edit', 'Edit'],
    ['/forms/abc/preview', 'Preview'],
    ['/forms/abc/share', 'Share'],
    ['/forms/abc/settings', 'Settings'],
    ['/forms/abc/submissions', 'Submissions'],
    // A submission's own page and the import are still on Submissions (was "Edit").
    ['/forms/abc/submissions/12', 'Submissions'],
    ['/forms/abc/submissions/import', 'Submissions'],
    ['/forms/abc', 'Edit'],
  ])('%s is on %s', (path, label) => {
    expect(activeNav(path).label).toBe(label)
  })
})
