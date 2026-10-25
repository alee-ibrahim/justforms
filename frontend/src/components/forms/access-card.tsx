/** "People with access" on the Share page (PHASE-3-SCREENS 10): per-form roles, plus people
 * invited to the organisation with this form (PEOPLE-SCREENS 6). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api, ApiError, type AccessEntry, type AccessList, type FormRole } from '@/lib/api'
import { FORM_ROLE_LABELS } from '@/lib/labels'

const ROLES = FORM_ROLE_LABELS

function initials(e: { displayName?: string; email: string }): string {
  const source = e.displayName?.trim() || e.email
  const parts = source.split(/[\s@._-]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?'
}

export function AccessCard({ formId, myEmail }: { formId: string; myEmail?: string }) {
  const queryClient = useQueryClient()
  const access = useQuery({ queryKey: ['access', formId], queryFn: () => api.getAccess(formId) })
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<FormRole>('viewer')
  const [error, setError] = useState<string | null>(null)
  const [confirmSelf, setConfirmSelf] = useState<(() => void) | null>(null)
  // An address outside the organisation, offered "Invite and share" (admins only).
  const [outsider, setOutsider] = useState<{ email: string; role: FormRole } | null>(null)

  const updated = (next: AccessList, message: string) => {
    queryClient.setQueryData(['access', formId], next)
    void queryClient.invalidateQueries({ queryKey: ['form', formId] })
    setEmail('')
    setError(null)
    setOutsider(null)
    toast(message)
  }
  const inviteShare = useMutation({
    mutationFn: (who: { email: string; role: FormRole }) => api.inviteAndShare(formId, who.email, who.role),
    onSuccess: (next, who) => updated(next, `Invited ${who.email}. They get access when they accept.`),
    onError: (err) =>
      toast.error(
        err instanceof ApiError && err.status === 429
          ? "You've sent a lot of invitations. Try again later."
          : "Couldn't send the invitation. Try again.",
      ),
  })
  const dropPending = useMutation({
    mutationFn: (invitationId: string) => api.removePendingAccess(formId, invitationId),
    onSuccess: (next) => {
      queryClient.setQueryData(['access', formId], next)
      toast('Removed the invited access')
    },
    onError: () => toast.error("Couldn't remove it. Try again."),
  })

  const save = useMutation({
    mutationFn: (grants: { email: string; role: FormRole }[]) => api.putAccess(formId, grants),
    onSuccess: (next) => updated(next, 'Access updated'),
    onError: (err, grants) => {
      const code = err instanceof ApiError ? (err.detail as { code?: string } | null)?.code : null
      const org = access.data?.orgName || 'your organisation'
      if (code === 'not_a_member') {
        const added = grants[grants.length - 1]
        if (access.data?.canInvite && added) setOutsider(added)
        else setError(`${added?.email ?? 'That person'} isn't in ${org} yet. Ask an organisation admin to invite them.`)
      }
      else if (code === 'owner_required') toast.error('A form needs at least one owner.')
      else toast.error("Couldn't update access. Try again.")
    },
  })

  const entries = access.data?.entries ?? []
  const pending = access.data?.pending ?? []
  const manage = access.data?.canManage ?? false
  const grants = entries.filter((e) => !e.orgAdmin)
  const hasAdmin = entries.some((e) => e.orgAdmin)
  const owners = grants.filter((e) => e.role === 'owner')
  const asGrants = (list: AccessEntry[]) => list.map((e) => ({ email: e.email, role: e.role }))
  const isSelf = (e: AccessEntry) => !!myEmail && e.email === myEmail.toLowerCase()
  const lastOwner = (e: AccessEntry) => !hasAdmin && e.role === 'owner' && owners.length === 1

  const change = (target: AccessEntry, next: FormRole | null) => {
    const list = next === null ? grants.filter((g) => g !== target) : grants.map((g) => (g === target ? { ...g, role: next } : g))
    const run = () => save.mutate(asGrants(list))
    if (isSelf(target) && target.role === 'owner' && next !== 'owner') setConfirmSelf(() => run)
    else run()
  }

  return (
    <Card className="rounded-md border shadow-none ring-0">
      <CardHeader>
        <CardTitle>People with access</CardTitle>
        <CardDescription>Who can open this form in JustForms. Organisation admins can always open every form.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {access.isPending ? (
          <Skeleton className="h-24" />
        ) : (
          <ItemGroup className="gap-1">
            {entries.map((e) => (
              <Item key={e.userId} size="sm" className="px-0">
                <ItemMedia>
                  <Avatar className="size-8">
                    <AvatarFallback className="text-xs">{initials(e)}</AvatarFallback>
                  </Avatar>
                </ItemMedia>
                <ItemContent className="min-w-0">
                  <ItemTitle className="max-w-full truncate">{e.displayName || e.email}</ItemTitle>
                  {e.displayName && <ItemDescription className="truncate">{e.email}</ItemDescription>}
                </ItemContent>
                <ItemActions>
                  {e.orgAdmin ? (
                    <span className="text-sm text-muted-foreground">Owner (organisation admin)</span>
                  ) : manage ? (
                    <>
                      <Select value={e.role} onValueChange={(v) => change(e, v as FormRole)} disabled={lastOwner(e) || save.isPending}>
                        <SelectTrigger size="sm" className="w-44" aria-label={`Role of ${e.displayName || e.email}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(Object.keys(ROLES) as FormRole[]).map((r) => (
                            <SelectItem key={r} value={r}>
                              {ROLES[r]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span tabIndex={lastOwner(e) ? 0 : -1}>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label={`Remove ${e.displayName || e.email}`}
                              disabled={lastOwner(e) || save.isPending}
                              onClick={() => change(e, null)}
                            >
                              <XIcon />
                            </Button>
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>{lastOwner(e) ? 'A form needs at least one owner' : `Remove ${e.displayName || e.email}`}</TooltipContent>
                      </Tooltip>
                    </>
                  ) : (
                    <span className="text-sm">{ROLES[e.role]}</span>
                  )}
                </ItemActions>
              </Item>
            ))}
            {pending.map((p) => (
              <Item key={p.invitationId} size="sm" className="px-0">
                <ItemMedia>
                  <Avatar className="size-8">
                    <AvatarFallback className="text-xs">{initials(p)}</AvatarFallback>
                  </Avatar>
                </ItemMedia>
                <ItemContent className="min-w-0">
                  <ItemTitle className="max-w-full truncate">
                    <bdi dir="ltr">{p.email}</bdi>
                  </ItemTitle>
                  <ItemDescription>
                    <Badge variant="outline">
                      <MailIcon data-icon="inline-start" />
                      {p.expired ? 'Invite expired' : 'Invited'}
                    </Badge>
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <span className="text-sm">{ROLES[p.role]}</span>
                  {manage && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Remove the invited access for ${p.email}`}
                          disabled={dropPending.isPending}
                          onClick={() => dropPending.mutate(p.invitationId)}
                        >
                          <XIcon />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Remove the invited access for {p.email}</TooltipContent>
                    </Tooltip>
                  )}
                </ItemActions>
              </Item>
            ))}
          </ItemGroup>
        )}
        {manage ? (
          <form
            className="flex flex-col gap-2"
            onSubmit={(ev) => {
              ev.preventDefault()
              const value = email.trim().toLowerCase()
              if (!value) return setError('Enter an email address like name@example.org')
              const others = grants.filter((g) => g.email !== value)
              save.mutate([...asGrants(others), { email: value, role }])
            }}
          >
            <Field>
              <FieldLabel htmlFor="access-email">Add someone by email</FieldLabel>
              <div className="flex flex-wrap gap-2">
                {/* Only the email input is marked invalid; the role select keeps its colours. */}
                <Field data-invalid={error ? true : undefined} className="min-w-48 flex-1">
                  <Input
                    id="access-email"
                    type="email"
                    autoComplete="off"
                    placeholder="name@example.org"
                    value={email}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={error ? 'access-email-error' : undefined}
                    onChange={(ev) => {
                      setEmail(ev.target.value)
                      setError(null)
                      setOutsider(null)
                    }}
                  />
                </Field>
                <Select value={role} onValueChange={(v) => setRole(v as FormRole)}>
                  <SelectTrigger className="w-44" aria-label="Role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(ROLES) as FormRole[]).map((r) => (
                      <SelectItem key={r} value={r}>
                        {ROLES[r]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button type="submit" variant="outline" disabled={save.isPending}>
                  Add
                </Button>
              </div>
              {error && <FieldError id="access-email-error">{error}</FieldError>}
              {outsider && (
                <Alert>
                  <AlertDescription className="flex flex-col gap-2">
                    <p>
                      <bdi dir="ltr">{outsider.email}</bdi> isn't in <bdi dir="auto">{access.data?.orgName}</bdi> yet.
                      They join as a member and get {ROLES[outsider.role].toLowerCase()} access to this form when
                      they accept.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button type="button" size="sm" disabled={inviteShare.isPending} onClick={() => inviteShare.mutate(outsider)}>
                        {inviteShare.isPending && <Spinner />}
                        Invite and share
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setOutsider(null)}>
                        Cancel
                      </Button>
                    </div>
                  </AlertDescription>
                </Alert>
              )}
              <FieldDescription>
                A submissions viewer can view and export submissions, but can't edit the form. Editors also edit the
                form and change status. Owners also manage access and delete.
              </FieldDescription>
            </Field>
          </form>
        ) : (
          access.data && <p className="text-sm text-muted-foreground">Only owners can change who has access.</p>
        )}
      </CardContent>
      <AlertDialog open={confirmSelf !== null} onOpenChange={(o) => !o && setConfirmSelf(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove your own access?</AlertDialogTitle>
            <AlertDialogDescription>
              You will no longer be an owner of this form. Another owner or an admin can give it back.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                confirmSelf?.()
                setConfirmSelf(null)
              }}
            >
              Remove my access
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
