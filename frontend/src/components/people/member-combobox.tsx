/** Type a name or email, pick an existing member, or keep a full address (PEOPLE-SCREENS 6.2).
 * The official combobox pattern: Popover + Command (cmdk gives the combobox / listbox roles,
 * arrow keys and Enter). The server filters, so cmdk's own filtering is off. */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { MailPlusIcon } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { Spinner } from '@/components/ui/spinner'
import { api, type MemberMatch } from '@/lib/api'

import { cleanEmail, isEmail, MIN_QUERY } from './member-search-lib'

/** What to offer for a typed full address that isn't a member: an action row, or a note. */
export type FreeEntry = { label: ReactNode; onSelect: () => void } | { note: ReactNode } | null

const FREE = '__free__'

function useDebounced<T>(value: T, ms: number): T {
  const [out, setOut] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setOut(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return out
}

export function MemberCombobox({
  label,
  labelId,
  orgId,
  formId,
  value,
  onValueChange,
  onPick,
  unavailable,
  freeEntry,
  onEnter,
  onKeyDown,
  placeholder = 'Name or email address',
  invalid,
  describedBy,
  autoFocus,
  debounceMs = 200,
}: {
  /** The field's accessible name, when there is no visible label (`labelId`). */
  label: string
  /** The id of the caller's visible <label>: it names the input and focuses it when clicked. */
  labelId?: string
  orgId?: string | null
  /** Search for a form's owners: matches say what access they already have. */
  formId?: string
  value: string
  onValueChange: (value: string) => void
  /** A member chosen from the list. */
  onPick: (member: MemberMatch) => void
  /** Why a member can't be chosen ("Already has access (Editor)"), shown in their row. */
  unavailable: (member: MemberMatch) => string | null
  freeEntry: (email: string) => FreeEntry
  /** Enter with nothing to choose in the list (e.g. submit the form). */
  onEnter?: () => void
  onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void
  placeholder?: string
  invalid?: boolean
  describedBy?: string
  autoFocus?: boolean
  debounceMs?: number
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const anchorRef = useRef<HTMLDivElement>(null)
  const [focused, setFocused] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const typed = value.trim()
  const term = useDebounced(typed, debounceMs)
  const searching = !!orgId && term.length >= MIN_QUERY
  const search = useQuery({
    queryKey: ['member-search', orgId, formId ?? null, term.toLowerCase()],
    queryFn: () => api.searchMembers(orgId!, term, formId),
    enabled: searching,
    staleTime: 30_000,
    retry: false,
    placeholderData: keepPreviousData,
  })

  const open = focused && !dismissed && typed.length >= MIN_QUERY
  const waiting = typed !== term || search.isFetching
  const matches = searching && typed.length >= MIN_QUERY ? (search.data ?? []) : []
  const email = cleanEmail(typed)
  const exact = matches.some((m) => m.email.toLowerCase() === email)
  const free = isEmail(typed) && !exact && !waiting ? freeEntry(email) : null
  const freeAction = free && 'onSelect' in free ? free : null
  const choosable = matches.filter((m) => !unavailable(m)).length + (freeAction ? 1 : 0)

  // cmdk always says aria-expanded="true" and names the input with its own hidden label (and
  // sets the input's id): say whether the list is really shown, and use the visible label.
  useLayoutEffect(() => {
    const input = inputRef.current
    if (!input) return
    input.setAttribute('aria-expanded', String(open))
    const visible = labelId ? document.getElementById(labelId) : null
    if (visible instanceof HTMLLabelElement) {
      input.setAttribute('aria-labelledby', labelId!)
      visible.htmlFor = input.id
    }
  })

  const pick = (m: MemberMatch) => {
    setDismissed(true)
    onPick(m)
  }

  return (
    <Command
      shouldFilter={false}
      loop
      label={label}
      // The field looks like the other inputs: no palette padding, a regular border.
      className="overflow-visible rounded-none! bg-transparent p-0 **:data-[slot=command-input-wrapper]:p-0 **:data-[slot=input-group]:border-input **:data-[slot=input-group]:bg-transparent dark:**:data-[slot=input-group]:bg-input/30"
    >
      <Popover
        open={open}
        onOpenChange={(next) => {
          if (!next) setDismissed(true)
        }}
      >
        <PopoverAnchor asChild>
          <div ref={anchorRef}>
            <CommandInput
              ref={inputRef}
              value={value}
              onValueChange={(v) => {
                setDismissed(false)
                onValueChange(v)
              }}
              placeholder={placeholder}
              inputMode="email"
              autoCapitalize="none"
              dir="auto"
              autoFocus={autoFocus}
              aria-invalid={invalid ? true : undefined}
              aria-describedby={describedBy}
              onFocus={(e) => {
                setFocused(true)
                // Phones: bring the field to the top so the list has room above the keyboard.
                if (window.matchMedia?.('(pointer: coarse)').matches)
                  e.currentTarget.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
              }}
              onBlur={() => setFocused(false)}
              onKeyDown={(e) => {
                onKeyDown?.(e)
                if (e.defaultPrevented) return e.stopPropagation()
                if (e.key === 'ArrowDown' && !open) {
                  setDismissed(false)
                  return e.stopPropagation()
                }
                if (e.key === 'Enter' && !e.nativeEvent.isComposing && !(open && choosable > 0)) {
                  // Nothing to choose: Enter is the field's own (Add, or a new chip).
                  e.preventDefault()
                  e.stopPropagation()
                  onEnter?.()
                }
              }}
            />
          </div>
        </PopoverAnchor>
        <PopoverContent
          align="start"
          // Stay clear of the sticky studio bar; the list shrinks to the room there is.
          collisionPadding={{ top: 72, bottom: 8 }}
          className="w-(--radix-popover-trigger-width) min-w-64 p-0"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          // Keep the focus (and the phone keyboard) in the input while choosing.
          onMouseDown={(e) => e.preventDefault()}
          onInteractOutside={(e) => {
            if (anchorRef.current?.contains(e.target as Node)) e.preventDefault()
          }}
        >
          <CommandList className="max-h-[min(18rem,var(--radix-popover-content-available-height))] p-1">
            {matches.length > 0 && (
              <CommandGroup heading="People in your organisation">
                {matches.map((m) => {
                  const note = unavailable(m)
                  return (
                    <CommandItem
                      key={m.userId}
                      value={m.userId}
                      disabled={!!note}
                      onSelect={() => pick(m)}
                      className="items-start gap-3 py-2 data-[disabled=true]:opacity-100"
                    >
                      <Avatar size="sm" className="mt-0.5" aria-hidden>
                        <AvatarFallback>{m.initials}</AvatarFallback>
                      </Avatar>
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate font-medium">
                          <bdi dir="auto">{m.displayName || m.email}</bdi>
                        </span>
                        {m.displayName && (
                          <span className="truncate text-muted-foreground">
                            <bdi dir="ltr">{m.email}</bdi>
                          </span>
                        )}
                        {note && <span className="text-xs text-muted-foreground">{note}</span>}
                      </span>
                    </CommandItem>
                  )
                })}
              </CommandGroup>
            )}
            {freeAction && (
              <CommandGroup>
                <CommandItem
                  value={FREE}
                  onSelect={() => {
                    setDismissed(true)
                    freeAction.onSelect()
                  }}
                  className="gap-3 py-2"
                >
                  <MailPlusIcon className="ms-1" aria-hidden />
                  <span className="min-w-0 break-words">{freeAction.label}</span>
                </CommandItem>
              </CommandGroup>
            )}
            {free && 'note' in free && <p className="px-2 py-2.5 text-sm text-muted-foreground">{free.note}</p>}
            {waiting && matches.length === 0 && (
              <p className="flex items-center gap-2 px-2 py-2.5 text-sm text-muted-foreground" role="status">
                <Spinner />
                Searching…
              </p>
            )}
            {!waiting && search.isError && (
              <p className="px-2 py-2.5 text-sm text-muted-foreground" role="status">
                Couldn't look up people. You can still type a full email address.
              </p>
            )}
            {!waiting && !search.isError && matches.length === 0 && !free && (
              <p className="px-2 py-2.5 text-sm text-muted-foreground" role="status">
                No one in your organisation matches. Type their full email address.
              </p>
            )}
          </CommandList>
        </PopoverContent>
      </Popover>
    </Command>
  )
}
