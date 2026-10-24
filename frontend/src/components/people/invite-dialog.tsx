/** "Invite people" (PEOPLE-SCREENS 3.1): several addresses at once, one role. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailPlusIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

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
import { Textarea } from '@/components/ui/textarea'
import { api, ApiError, type InviteResult, type OrgRole } from '@/lib/api'
import { metaQuery } from '@/lib/queries'

import { MAX_INVITES as MAX, parseEmails } from './parse-emails'

export function InviteDialog({ orgId, orgName, inviteDays }: { orgId: string; orgName: string; inviteDays: number }) {
  const queryClient = useQueryClient()
  const meta = useQuery(metaQuery)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [role, setRole] = useState<OrgRole>('member')
  const [error, setError] = useState<string | null>(null)
  const [skipped, setSkipped] = useState<string[]>([])
  const { valid, invalid } = parseEmails(text)

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
    if (!text.trim()) return setError('Enter at least one email address.')
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
              <FieldLabel htmlFor="invite-emails">Email addresses</FieldLabel>
              <Textarea
                id="invite-emails"
                dir="ltr"
                rows={3}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                inputMode="email"
                placeholder="name@example.org, another@example.org"
                value={text}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? 'invite-emails-error invite-emails-help' : 'invite-emails-help'}
                onChange={(e) => {
                  setText(e.target.value)
                  if (error) setError(null)
                }}
                autoFocus
              />
              <FieldDescription id="invite-emails-help">
                Separate addresses with commas, spaces or new lines. Up to {MAX} at a time.
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
            <Button type="submit" disabled={send.isPending || (!!text.trim() && count === 0 && invalid.length === 0)}>
              {send.isPending && <Spinner />}
              {count > 1 ? `Send ${count} invites` : 'Send invite'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
