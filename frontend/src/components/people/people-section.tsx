/** Organisation settings › People (PEOPLE-SCREENS 3): members and pending invitations. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CircleCheckIcon,
  CircleDashedIcon,
  ClockIcon,
  EllipsisIcon,
  MailIcon,
  MailXIcon,
  SearchIcon,
} from 'lucide-react'
import { type ReactNode, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { InviteDialog } from '@/components/people/invite-dialog'
import { RolePicker } from '@/components/people/role-picker'
import { useMenuTooltip } from '@/components/layout/use-menu-tooltip'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { FieldDescription, FieldLegend, FieldSet } from '@/components/ui/field'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api, ApiError, type Invitation, type Me, type OrgRole, type People, type Person } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { peopleQuery } from '@/lib/queries'
import { ORG_ROLE_LABEL, ORG_ROLES } from '@/lib/roles'
import { useDelayed } from '@/lib/use-delayed'

type Row =
  | { kind: 'member'; key: string; person: Person; name: string; email: string; role: OrgRole }
  | { kind: 'invite'; key: string; invite: Invitation; name: string; email: string; role: OrgRole }

function initials(name: string, email: string): string {
  const parts = (name.trim() || email).split(/[\s@._-]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?'
}

function rowsOf(people: People): Row[] {
  const invites: Row[] = people.invitations.map((invite) => ({
    kind: 'invite',
    key: `i:${invite.id}`,
    invite,
    name: '',
    email: invite.email,
    role: invite.role,
  }))
  const members: Row[] = [...people.members]
    .sort((a, b) => (a.displayName || a.email).localeCompare(b.displayName || b.email))
    .map((person) => ({
      kind: 'member',
      key: `m:${person.userId}`,
      person,
      name: person.displayName,
      email: person.email,
      role: person.role,
    }))
  return [...invites, ...members]
}

function StatusBadge({ row }: { row: Row }) {
  if (row.kind === 'member')
    return row.person.status === 'active' ? (
      <Badge variant="secondary">
        <CircleCheckIcon data-icon="inline-start" />
        Active
      </Badge>
    ) : (
      <Badge variant="outline">
        <CircleDashedIcon data-icon="inline-start" />
        Never signed in
      </Badge>
    )
  const { state, emailError } = row.invite
  if (state === 'email_failed')
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="destructive" tabIndex={0}>
            <MailXIcon data-icon="inline-start" />
            Email not sent
          </Badge>
        </TooltipTrigger>
        <TooltipContent>{emailError ?? "The invitation email couldn't be sent."}</TooltipContent>
      </Tooltip>
    )
  return state === 'expired' ? (
    <Badge variant="outline">
      <ClockIcon data-icon="inline-start" />
      Invite expired
    </Badge>
  ) : (
    <Badge variant="outline">
      <MailIcon data-icon="inline-start" />
      Invited
    </Badge>
  )
}

function lastSignIn(row: Row): string {
  if (row.kind === 'member') return row.person.lastLoginAt ? formatDate(row.person.lastLoginAt) : '-'
  const when = formatDate(row.invite.expiresAt)
  return row.invite.state === 'expired' ? `Expired ${when}` : `Expires ${when}`
}

type Pending =
  | { action: 'role'; row: Row }
  | { action: 'remove'; row: Extract<Row, { kind: 'member' }> }
  | { action: 'cancel'; row: Extract<Row, { kind: 'invite' }> }
  | null

function RowActions({
  row,
  me,
  lastAdmin,
  orgName,
  onPick,
  onResend,
}: {
  row: Row
  me: Me
  lastAdmin: boolean
  orgName: string
  onPick: (p: Pending) => void
  onResend: (invite: Invitation) => void
}) {
  const menuTip = useMenuTooltip()
  const who = row.name || row.email
  const self = row.kind === 'member' && row.person.userId === me.id
  return (
    <DropdownMenu>
      <Tooltip {...menuTip.tooltip}>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${who}`}>
              <EllipsisIcon />
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>Actions for {who}</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" className="min-w-52" {...menuTip.content}>
        {/* Phones fold the last sign-in column into the menu. */}
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground sm:hidden">
          {row.kind === 'member' ? `Last sign-in: ${lastSignIn(row)}` : lastSignIn(row)}
        </DropdownMenuLabel>
        <DropdownMenuSeparator className="sm:hidden" />
        <DropdownMenuItem onSelect={() => onPick({ action: 'role', row })}>Change role</DropdownMenuItem>
        {row.kind === 'invite' && (
          <DropdownMenuItem onSelect={() => onResend(row.invite)}>Resend invite</DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        {row.kind === 'invite' ? (
          <DropdownMenuItem variant="destructive" onSelect={() => onPick({ action: 'cancel', row })}>
            Cancel invite
          </DropdownMenuItem>
        ) : lastAdmin ? (
          <DropdownMenuItem disabled>
            <span className="flex flex-col">
              {self ? 'Leave organisation' : 'Remove from organisation'}
              <span className="text-xs text-muted-foreground">
                <bdi dir="auto">{orgName}</bdi> needs at least one admin.
              </span>
            </span>
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem variant="destructive" onSelect={() => onPick({ action: 'remove', row })}>
            {self ? 'Leave organisation' : 'Remove from organisation'}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function RoleDialog({
  pending,
  orgId,
  orgName,
  me,
  lastAdmin,
  onClose,
}: {
  pending: Extract<Pending, { action: 'role' }>
  orgId: string
  orgName: string
  me: Me
  lastAdmin: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const { row } = pending
  const [role, setRole] = useState<OrgRole>(row.role)
  const who = row.name || row.email
  const self = row.kind === 'member' && row.person.userId === me.id
  const save = useMutation({
    mutationFn: () =>
      row.kind === 'member'
        ? api.setMemberRole(orgId, row.person.userId, role)
        : api.setInvitationRole(orgId, row.invite.id, role),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['people', orgId] })
      if (self) await queryClient.invalidateQueries({ queryKey: ['me'] })
      toast(`Changed ${who}'s role to ${ORG_ROLE_LABEL[role]}`)
      onClose()
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError && err.detail === 'last_admin'
          ? `${orgName} needs at least one admin. Make someone else an admin first.`
          : "Couldn't change the role. Try again.",
      ),
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto">
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (role !== row.role) save.mutate()
            else onClose()
          }}
        >
          <DialogHeader>
            <DialogTitle>Change role</DialogTitle>
            <DialogDescription>
              {row.name ? (
                <>
                  <bdi dir="auto">{row.name}</bdi> (<bdi dir="ltr">{row.email}</bdi>)
                </>
              ) : (
                <bdi dir="ltr">{row.email}</bdi>
              )}
              {row.kind === 'invite' && ', invited'}
            </DialogDescription>
          </DialogHeader>
          <FieldSet>
            <FieldLegend variant="label" id="role-dialog-label">
              Role
            </FieldLegend>
            <RolePicker
              id="role-dialog"
              value={role}
              onChange={setRole}
              labelledBy="role-dialog-label"
              disabled={(r) => lastAdmin && r !== 'admin'}
            />
            {lastAdmin && (
              <FieldDescription>
                <bdi dir="auto">{orgName}</bdi> needs at least one admin. Make someone else an admin first.
              </FieldDescription>
            )}
          </FieldSet>
          {self && row.role === 'admin' && role !== 'admin' && (
            <Alert>
              <AlertDescription>
                You'll lose access to organisation settings and to forms that aren't shared with you.
              </AlertDescription>
            </Alert>
          )}
          {row.kind === 'member' && row.person.managedByGroups && (
            <Alert>
              <AlertDescription>
                This person's role is set by your sign-in groups. It changes back the next time they sign in.
              </AlertDescription>
            </Alert>
          )}
          <DialogFooter className="sticky -bottom-4 z-10 bg-muted">
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={save.isPending || role === row.role}>
              {save.isPending && <Spinner />}
              Save role
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ConfirmDialog({
  title,
  description,
  action,
  cancel = 'Cancel',
  busy,
  onConfirm,
  onClose,
}: {
  title: ReactNode
  description: ReactNode
  action: string
  cancel?: string
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{cancel}</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={busy}
            onClick={(e) => {
              e.preventDefault()
              onConfirm()
            }}
          >
            {busy && <Spinner />}
            {action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function PersonCell({ row, me }: { row: Row; me: Me }) {
  const self = row.kind === 'member' && row.person.userId === me.id
  return (
    <div className="flex min-w-0 items-center gap-3">
      <Avatar className="size-8 max-sm:self-start">
        <AvatarFallback className="text-xs">{initials(row.name, row.email)}</AvatarFallback>
      </Avatar>
      <div className="flex min-w-0 flex-col">
        <span className="truncate font-medium">
          {row.name ? <bdi dir="auto">{row.name}</bdi> : <bdi dir="ltr">{row.email}</bdi>}
          {self && <span className="font-normal text-muted-foreground"> (you)</span>}
        </span>
        {row.name && (
          <span className="truncate text-muted-foreground">
            <bdi dir="ltr">{row.email}</bdi>
          </span>
        )}
        {/* Phones: role and status under the name instead of their own columns. */}
        <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 sm:hidden">
          <span className="text-muted-foreground">{ORG_ROLE_LABEL[row.role]}</span>
          <StatusBadge row={row} />
        </span>
      </div>
    </div>
  )
}

export function PeopleSection({ orgId, me }: { orgId: string; me: Me }) {
  const queryClient = useQueryClient()
  const people = useQuery(peopleQuery(orgId))
  const showSkeleton = useDelayed(people.isPending)
  const [query, setQuery] = useState('')
  const [pending, setPending] = useState<Pending>(null)
  const orgName = people.data?.orgName ?? ''

  const rows = useMemo(() => (people.data ? rowsOf(people.data) : []), [people.data])
  const q = query.trim().toLowerCase()
  const shown = q ? rows.filter((r) => r.name.toLowerCase().includes(q) || r.email.includes(q)) : rows
  const isLastAdmin = (row: Row) =>
    row.kind === 'member' && row.role === 'admin' && (people.data?.adminCount ?? 0) <= 1

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['people', orgId] })
  const resend = useMutation({
    mutationFn: (invite: Invitation) => api.resendInvitation(orgId, invite.id),
    onSuccess: async (invite) => {
      await refresh()
      toast(`Sent a new invite to ${invite.email}`)
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError && err.status === 429
          ? "You've resent this invite a few times. Try again later."
          : "Couldn't resend the invite. Try again.",
      ),
  })
  const remove = useMutation({
    mutationFn: (person: Person) => api.removeMember(orgId, person.userId),
    onSuccess: async (_, person) => {
      await refresh()
      if (person.userId === me.id) await queryClient.invalidateQueries({ queryKey: ['me'] })
      toast(person.userId === me.id ? `You left ${orgName}` : `Removed ${person.displayName || person.email}`)
      setPending(null)
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError && err.detail === 'last_admin'
          ? `${orgName} needs at least one admin.`
          : "Couldn't remove them. Try again.",
      ),
  })
  const cancel = useMutation({
    mutationFn: (invite: Invitation) => api.cancelInvitation(orgId, invite.id),
    onSuccess: async (_, invite) => {
      await refresh()
      toast(`Cancelled the invite for ${invite.email}`)
      setPending(null)
    },
    onError: () => toast.error("Couldn't cancel the invite. Try again."),
  })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="text-lg font-semibold">People</h2>
          <p className="text-sm text-muted-foreground">
            Who can sign in to {orgName ? <bdi dir="auto">{orgName}</bdi> : 'this organisation'} and what they can do.
          </p>
        </div>
        {people.data && (
          <InviteDialog orgId={orgId} orgName={people.data.orgName} inviteDays={people.data.inviteDays} />
        )}
      </div>

      {people.isError ? (
        <Alert variant="destructive">
          <AlertDescription>
            <p>Couldn't load people. Check your connection and try again.</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={() => void people.refetch()}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      ) : people.isPending ? (
        showSkeleton && (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        )
      ) : (
        <>
          <InputGroup className="sm:max-w-80">
            <InputGroupAddon>
              <SearchIcon />
            </InputGroupAddon>
            <InputGroupInput
              type="search"
              aria-label="Search people"
              placeholder="Search by name or email"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </InputGroup>
          <span className="sr-only" aria-live="polite">
            {q ? `${shown.length} ${shown.length === 1 ? 'person' : 'people'}` : ''}
          </span>
          <div className="rounded-md border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="ps-4">Person</TableHead>
                  <TableHead className="max-sm:hidden">Role</TableHead>
                  <TableHead className="max-sm:hidden">Status</TableHead>
                  <TableHead className="max-md:hidden">Last sign-in</TableHead>
                  <TableHead className="w-12">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((row) => (
                  <TableRow key={row.key}>
                    <TableCell className="max-w-0 ps-4 whitespace-normal sm:max-w-none">
                      <PersonCell row={row} me={me} />
                    </TableCell>
                    <TableCell className="align-top max-sm:hidden sm:align-middle">
                      {ORG_ROLE_LABEL[row.role]}
                      {row.kind === 'member' && row.person.managedByGroups && (
                        <span className="block text-xs text-muted-foreground">Set by sign-in groups</span>
                      )}
                    </TableCell>
                    <TableCell className="max-sm:hidden">
                      <StatusBadge row={row} />
                    </TableCell>
                    <TableCell className="text-muted-foreground tabular-nums max-md:hidden">{lastSignIn(row)}</TableCell>
                    <TableCell className="text-end">
                      <RowActions
                        row={row}
                        me={me}
                        lastAdmin={isLastAdmin(row)}
                        orgName={orgName}
                        onPick={setPending}
                        onResend={(invite) => resend.mutate(invite)}
                      />
                    </TableCell>
                  </TableRow>
                ))}
                {shown.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="ps-4 whitespace-normal text-muted-foreground">
                      No one matches “{query.trim()}”.{' '}
                      <Button variant="link" className="h-auto p-0" onClick={() => setQuery('')}>
                        Clear search
                      </Button>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {!q && rows.length === 1 && (
            <p className="text-sm text-muted-foreground">
              Invite the people you work with. They'll see only what you share with them unless you make them form
              creators or admins.
            </p>
          )}
          <section aria-labelledby="roles-heading" className="flex flex-col gap-2">
            <h3 id="roles-heading" className="text-sm font-semibold">
              Roles
            </h3>
            <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
              {[...ORG_ROLES].reverse().map((r) => (
                <div key={r.value} className="contents">
                  <dt className="font-medium">{r.label}</dt>
                  <dd className="text-muted-foreground max-sm:mb-2">{r.description}</dd>
                </div>
              ))}
            </dl>
          </section>
        </>
      )}

      {pending?.action === 'role' && (
        <RoleDialog
          pending={pending}
          orgId={orgId}
          orgName={orgName}
          me={me}
          lastAdmin={isLastAdmin(pending.row)}
          onClose={() => setPending(null)}
        />
      )}
      {pending?.action === 'remove' &&
        (() => {
          const person = pending.row.person
          const self = person.userId === me.id
          const who = person.displayName || person.email
          const n = person.formCount
          return (
            <ConfirmDialog
              title={
                self ? (
                  <>
                    Leave <bdi dir="auto">{orgName}</bdi>?
                  </>
                ) : (
                  <>
                    Remove <bdi dir="auto">{who}</bdi> from <bdi dir="auto">{orgName}</bdi>?
                  </>
                )
              }
              description={
                <>
                  {self ? 'You' : 'They'} can no longer open <bdi dir="auto">{orgName}</bdi>'s forms.
                  {n > 0 && ` ${self ? 'Your' : 'Their'} access to the ${n === 1 ? 'form' : `${n} forms`} shared with ${self ? 'you' : 'them'} is removed.`}{' '}
                  Forms {self ? 'you' : 'they'} own stay, and admins can still manage them.
                </>
              }
              action={self ? 'Leave organisation' : 'Remove from organisation'}
              busy={remove.isPending}
              onConfirm={() => remove.mutate(person)}
              onClose={() => setPending(null)}
            />
          )
        })()}
      {pending?.action === 'cancel' && (
        <ConfirmDialog
          title={
            <>
              Cancel the invite for <bdi dir="ltr">{pending.row.email}</bdi>?
            </>
          }
          description="The link in their email stops working."
          action="Cancel invite"
          cancel="Keep invite"
          busy={cancel.isPending}
          onConfirm={() => cancel.mutate(pending.row.invite)}
          onClose={() => setPending(null)}
        />
      )}
    </div>
  )
}
