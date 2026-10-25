/** "Invite people" (PEOPLE-SCREENS 3.1): several addresses at once (chips), one role. Typing
 * suggests matching members, marked "Already a member" (PEOPLE-SCREENS 6.2). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailPlusIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { MemberCombobox } from '@/components/people/member-combobox'
import { RolePicker } from '@/components/people/role-picker'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel, FieldSet, FieldLegend } from '@/components/ui/field'
import { Spinner } from '@/components/ui/spinner'
import { api, ApiError, type InviteResult, type OrgRole } from '@/lib/api'
import { metaQuery } from '@/lib/queries'

import { addChips, isEmail, splitTyped } from './member-search-lib'
import { MAX_INVITES as MAX, parseEmails } from './parse-emails'

export function InviteDialog({ orgId, orgName, inviteDays }: { orgId: string; orgName: string; inviteDays: number }) {
  const queryClient = useQueryClient()
  const meta = useQuery(metaQuery)
  const [open, setOpen] = useState(false)
  const [chips, setChips] = useState<string[]>([])
  const [text, setText] = useState('')
  const [role, setRole] = useState<OrgRole>('member')
  const [error, setError] = useState<string | null>(null)
  const [skipped, setSkipped] = useState<string[]>([])
  // The chips plus whatever is still being typed.
  const { valid, invalid } = parseEmails([...chips, text].join(' '))
  const type = (value: string) => {
    const { done, rest } = splitTyped(value)
    if (done.length) setChips((c) => addChips(c, done))
    setText(rest)
    if (error) setError(null)
  }
  const commit = () => {
    const { done } = splitTyped(`${text} `)
    if (done.length) setChips((c) => addChips(c, done))
    setText('')
  }

  const send = useMutation({
    mutationFn: () => api.invite(orgId, valid, role),
    onSuccess: async ({ results }) => {
      await queryClient.invalidateQueries({ queryKey: ['people', orgId] })
      const invited = results.filter((r: InviteResult) => r.outcome === 'invited').map((r) => r.email)
      const already = results.filter((r: InviteResult) => r.outcome === 'already_member').map((r) => r.email)
      if (already.length === 0) {
        setOpen(false)
        toast(invited.length === 1 ? `Invited ${invited[0]}` : `Invited ${invited.length} people`)
        return
      }
      setSkipped(already)
      setChips([])
      setText('')
      if (invited.length) toast(invited.length === 1 ? `Invited ${invited[0]}` : `Invited ${invited.length} people`)
    },
    onError: (err) =>
      setError(
        err instanceof ApiError && err.status === 429
          ? "You've sent a lot of invitations. Try again in an hour."
          : err instanceof ApiError && err.status === 422
            ? 'Check the addresses and try again.'
            : "Couldn't send the invitations. Try again.",
      ),
  })

  const submit = () => {
    setSkipped([])
    commit()
    if (!valid.length && !invalid.length) return setError('Enter at least one email address.')
    if (invalid.length) return setError(`Check these addresses: ${invalid.join(', ')}.`)
    if (valid.length > MAX) return setError(`Invite up to ${MAX} people at a time.`)
    setError(null)
    send.mutate()
  }

  const noEmail = meta.data && !meta.data.features.email
  const sso = !!meta.data?.features.oidc
  const count = valid.length
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) {
          setChips([])
          setText('')
          setRole('member')
          setError(null)
          setSkipped([])
          send.reset()
        }
      }}
    >
      <DialogTrigger asChild>
        <Button className="max-sm:w-full">
          <MailPlusIcon />
          Invite people
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto">
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <DialogHeader>
            <DialogTitle>Invite people</DialogTitle>
            <DialogDescription>
              They get an email with a link to join <bdi dir="auto">{orgName}</bdi>. The link works for {inviteDays} days.
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field data-invalid={error ? true : undefined}>
              <FieldLabel id="invite-emails-label">Email addresses</FieldLabel>
              {chips.length > 0 && (
                <ul className="flex flex-wrap gap-1.5" aria-label="To invite">
                  {chips.map((address) => (
                    <li key={address}>
                      <Button
                        type="button"
                        size="sm"
                        variant={isEmail(address) ? 'secondary' : 'destructive'}
                        className="max-w-full"
                        aria-label={`Remove ${address}`}
                        onClick={() => setChips((c) => c.filter((x) => x !== address))}
                      >
                        <bdi dir="ltr" className="truncate">
                          {address}
                        </bdi>
                        <XIcon data-icon="inline-end" aria-hidden />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <MemberCombobox
                label="Email addresses"
                labelId="invite-emails-label"
                orgId={orgId}
                value={text}
                placeholder={chips.length ? 'Add another' : 'Name or name@example.org'}
                invalid={!!error}
                describedBy={error ? 'invite-emails-error invite-emails-help' : 'invite-emails-help'}
                autoFocus
                onValueChange={type}
                // Members are already in: their rows only say so.
                onPick={() => {}}
                unavailable={() => 'Already a member'}
                freeEntry={(address) =>
                  chips.includes(address)
                    ? { note: 'Already in the list.' }
                    : {
                        label: (
                          <>
                            Invite <bdi dir="ltr">{address}</bdi>
                          </>
                        ),
                        onSelect: () => {
                          setChips((c) => addChips(c, [address]))
                          setText('')
                        },
                      }
                }
                onEnter={() => (text.trim() ? commit() : submit())}
                onKeyDown={(e) => {
                  if (e.key === 'Backspace' && !text && chips.length) {
                    e.preventDefault()
                    setChips((c) => c.slice(0, -1))
                  }
                }}
              />
              <FieldDescription id="invite-emails-help">
                Type a name to find people already here, or paste addresses separated by commas,
                spaces or new lines. Up to {MAX} at a time.
              </FieldDescription>
              {error && <FieldError id="invite-emails-error">{error}</FieldError>}
            </Field>
            <FieldSet>
              <FieldLegend variant="label" id="invite-role-label">
                Role
              </FieldLegend>
              <RolePicker id="invite-role" value={role} onChange={setRole} labelledBy="invite-role-label" />
            </FieldSet>
          </FieldGroup>
          {skipped.length > 0 && (
            <Alert>
              <AlertDescription>
                <p>
                  Already in <bdi dir="auto">{orgName}</bdi>: <bdi dir="ltr">{skipped.join(', ')}</bdi>.
                </p>
              </AlertDescription>
            </Alert>
          )}
          {noEmail && (
            <Alert>
              <AlertDescription>
                {sso
                  ? "Email isn't set up on this server, so no invitation email goes out. Invited people can still join by signing in with this address."
                  : "Email isn't set up on this server, so no invitation email goes out and invited people can't get a sign-in code. Ask your server administrator to set up email."}
              </AlertDescription>
            </Alert>
          )}
          <DialogFooter className="sticky -bottom-4 z-10 bg-muted">
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {skipped.length ? 'Done' : 'Cancel'}
              </Button>
            </DialogClose>
            <Button type="submit" disabled={send.isPending}>
              {send.isPending && <Spinner />}
              {count > 1 ? `Send ${count} invites` : 'Send invite'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
