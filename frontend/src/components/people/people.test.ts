import { describe, expect, it } from 'vitest'

import type { Me } from '@/lib/api'
import { canCreateForms, isOrgAdmin, orgRole } from '@/lib/roles'

import { parseEmails } from './parse-emails'

describe('parseEmails', () => {
  it('splits on commas, spaces and new lines, lower-cases and drops duplicates', () => {
    expect(parseEmails('Ana@Example.org, ben@example.org\nana@example.org;  <cy@example.org>')).toEqual({
      valid: ['ana@example.org', 'ben@example.org', 'cy@example.org'],
      invalid: [],
    })
  })

  it('reports what is not an address', () => {
    expect(parseEmails('ok@example.org nope@ x')).toEqual({ valid: ['ok@example.org'], invalid: ['nope@', 'x'] })
  })
})

describe('organisation roles', () => {
  const me = (role: 'admin' | 'creator' | 'member', isSuperadmin = false): Me => ({
    id: 'u',
    email: 'u@example.org',
    displayName: '',
    isSuperadmin,
    appearance: 'light',
    orgs: [{ id: 'o', name: 'O', slug: 'o', role }],
  })

  it('lets creators and admins create forms, not members', () => {
    expect(canCreateForms(me('admin'), 'o')).toBe(true)
    expect(canCreateForms(me('creator'), 'o')).toBe(true)
    expect(canCreateForms(me('member'), 'o')).toBe(false)
    expect(canCreateForms(me('creator'), 'other')).toBe(false)
  })

  it('treats superadmins as admins of every organisation', () => {
    expect(orgRole(me('member', true), 'anywhere')).toBe('admin')
    expect(isOrgAdmin(me('member', true), 'anywhere')).toBe(true)
    expect(isOrgAdmin(me('creator'), 'o')).toBe(false)
  })
})
