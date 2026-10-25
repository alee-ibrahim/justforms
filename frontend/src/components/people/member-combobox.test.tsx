// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, useState, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AccessCard } from '@/components/forms/access-card'
import { TooltipProvider } from '@/components/ui/tooltip'
import { api, type AccessList, type MemberMatch } from '@/lib/api'

import { InviteDialog } from './invite-dialog'
import { MemberCombobox } from './member-combobox'
import { accessNote, addChips, splitTyped } from './member-search-lib'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const IBRAHIM: MemberMatch = {
  userId: 'u2',
  email: 'ibrahim@example.org',
  displayName: 'Ibrahim Naseer',
  role: 'member',
  initials: 'IN',
  formRole: 'editor',
}
const IBRAHIMA: MemberMatch = {
  userId: 'u3',
  email: 'ibrahima@example.org',
  displayName: 'Ibrahima Hassan',
  role: 'creator',
  initials: 'IH',
  formRole: null,
}

let root: Root | undefined
let host: HTMLElement | undefined
let search: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  search = vi.spyOn(api, 'searchMembers').mockImplementation(async (_org, q) =>
    [IBRAHIM, IBRAHIMA].filter((m) => m.displayName.toLowerCase().includes(q.toLowerCase()) || m.email.startsWith(q)),
  )
})

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

async function render(node: ReactNode, setup?: (client: QueryClient) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  setup?.(client)
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  await act(async () => {
    root!.render(
      <QueryClientProvider client={client}>
        <TooltipProvider>{node}</TooltipProvider>
      </QueryClientProvider>,
    )
  })
}

const input = () => document.querySelector<HTMLInputElement>('[cmdk-input]')!
const options = () => [...document.querySelectorAll<HTMLElement>('[role="option"]')]
const wait = (ms = 30) => act(async () => new Promise((r) => setTimeout(r, ms)))

async function type(text: string) {
  const el = input()
  await act(async () => {
    el.focus()
    el.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setter.call(el, text)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await wait(250)
  await wait()
}

async function key(k: string) {
  await act(async () => {
    input().dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }))
  })
  await wait()
}

describe('member search helpers', () => {
  it('says what access someone already has', () => {
    expect(accessNote(IBRAHIM)).toBe('Already has access (Editor)')
    expect(accessNote({ role: 'admin', formRole: 'owner' })).toBe('Already has access (Owner, organisation admin)')
    expect(accessNote({ role: 'member', formRole: 'viewer' })).toBe('Already has access (Submissions viewer)')
    expect(accessNote(IBRAHIMA)).toBeNull()
  })

  it('turns finished addresses into chips and keeps the rest', () => {
    expect(splitTyped('a@example.org, B@Example.org ')).toEqual({ done: ['a@example.org', 'b@example.org'], rest: '' })
    expect(splitTyped('a@example.org;<c@example.org>\nibra')).toEqual({
      done: ['a@example.org', 'c@example.org'],
      rest: 'ibra',
    })
    expect(addChips(['a@example.org'], ['a@example.org', 'b@example.org'])).toEqual(['a@example.org', 'b@example.org'])
  })
})

describe('member combobox', () => {
  it('suggests members, skips the ones that cannot be chosen, and picks with Enter', async () => {
    const picked: MemberMatch[] = []
    function Harness() {
      const [value, setValue] = useState('')
      return (
        <MemberCombobox
          label="Add someone by email"
          orgId="o1"
          formId="f1"
          value={value}
          debounceMs={0}
          onValueChange={setValue}
          onPick={(m) => picked.push(m)}
          unavailable={accessNote}
          freeEntry={() => null}
        />
      )
    }
    await render(<Harness />)
    expect(input().getAttribute('role')).toBe('combobox')
    expect(input().getAttribute('aria-expanded')).toBe('false')
    await type('ibra')
    expect(search).toHaveBeenCalledWith('o1', 'ibra', 'f1')
    expect(document.querySelector('[role="listbox"]')).not.toBeNull()
    const [first, second] = options()
    expect(first.textContent).toContain('Ibrahim Naseer')
    expect(first.textContent).toContain('Already has access (Editor)')
    expect(first.getAttribute('aria-disabled')).toBe('true')
    expect(second.textContent).toContain('ibrahima@example.org')
    expect(input().getAttribute('aria-expanded')).toBe('true')
    await key('Enter')
    expect(picked.map((m) => m.email)).toEqual(['ibrahima@example.org'])
  })
})

describe('Share: add someone', () => {
  const owner = { userId: 'u1', email: 'owner@example.org', displayName: 'Aminath Ali', role: 'owner' as const, orgAdmin: false }
  const list = (over: Partial<AccessList> = {}): AccessList => ({
    entries: [owner],
    pending: [],
    canManage: true,
    canInvite: false,
    orgId: 'o1',
    orgName: 'Example',
    smtpEnabled: false,
    ...over,
  })
  const card = (data: AccessList) =>
    render(<AccessCard formId="f1" myEmail="owner@example.org" />, (c) => c.setQueryData(['access', 'f1'], data))

  it('fills the address of the member picked; Enter again adds them', async () => {
    const put = vi.spyOn(api, 'putAccess').mockResolvedValue(list())
    await card(list())
    await type('ibra')
    expect(options().map((o) => o.getAttribute('aria-disabled'))).toEqual(['true', 'false'])
    await key('Enter')
    expect(input().value).toBe('ibrahima@example.org')
    expect(document.querySelector('[role="listbox"]')).toBeNull()
    await key('Enter')
    expect(put).toHaveBeenCalledWith(
      'f1',
      [
        { email: 'owner@example.org', role: 'owner' },
        { email: 'ibrahima@example.org', role: 'viewer' },
      ],
      {},
    )
  })

  it('offers to invite a full address from outside to organisation admins', async () => {
    await card(list({ canInvite: true }))
    await type('new@example.org')
    const [invite] = options()
    expect(invite.textContent).toContain('Invite new@example.org to Example')
    await key('Enter')
    expect(document.body.textContent).toContain("new@example.org isn't in Example yet.")
    expect(document.body.textContent).toContain('Invite and share')
  })

  it('tells other owners to ask an admin', async () => {
    await card(list())
    await type('new@example.org')
    expect(options()).toEqual([])
    expect(document.body.textContent).toContain("new@example.org isn't in Example yet. Ask an organisation admin to invite them.")
  })
})

describe('Invite people', () => {
  it('marks members as already in and collects typed addresses as chips', async () => {
    await render(<InviteDialog orgId="o1" orgName="Example" inviteDays={7} />, (c) =>
      c.setQueryData(['meta'], { features: { email: true, oidc: false } } as never),
    )
    await act(async () => document.querySelector<HTMLButtonElement>('button')!.click())
    await type('ibra')
    expect(search).toHaveBeenCalledWith('o1', 'ibra', undefined)
    expect(options().every((o) => o.textContent?.includes('Already a member'))).toBe(true)
    expect(options().every((o) => o.getAttribute('aria-disabled') === 'true')).toBe(true)
    await type('a@example.org, b@example.org ')
    expect(input().value).toBe('')
    await type('new@example.org')
    const [invite] = options()
    expect(invite.textContent).toContain('Invite new@example.org')
    await key('Enter')
    const chips = [...document.querySelectorAll('[aria-label^="Remove "]')].map((b) => b.getAttribute('aria-label'))
    expect(chips).toEqual(['Remove a@example.org', 'Remove b@example.org', 'Remove new@example.org'])
    expect(document.body.textContent).toContain('Send 3 invites')
  })
})
