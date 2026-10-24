/** "Webhooks" (PHASE-4-SCREENS 1.4): list, add, and the delivery log in a sheet. */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDownIcon,
  CircleCheckIcon,
  CircleOffIcon,
  ClockIcon,
  EllipsisIcon,
  PlusIcon,
  WebhookIcon,
  XIcon,
} from 'lucide-react'
import { Fragment, useRef, useState } from 'react'
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
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldLabel } from '@/components/ui/field'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, type FormSummary, type Webhook, type WebhookDelivery } from '@/lib/api'
import { formatDateTimeSeconds } from '@/lib/format'

import { SecretStep, WebhookDialog } from './webhook-dialog'
import { EVENT_LABELS } from './webhook-text'

function StateBadge({ hook }: { hook: Webhook }) {
  if (hook.enabled)
    return (
      <Badge variant="outline">
        <CircleCheckIcon data-icon="inline-start" />
        On
      </Badge>
    )
  if (hook.disabledReason === 'failures')
    return (
      <Badge variant="destructive">
        <XIcon data-icon="inline-start" />
        Turned off after failures
      </Badge>
    )
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <CircleOffIcon data-icon="inline-start" />
      Off
    </Badge>
  )
}

function ResultBadge({ d }: { d: WebhookDelivery }) {
  if (d.status === 'succeeded')
    return (
      <Badge variant="outline">
        <CircleCheckIcon data-icon="inline-start" />
        {d.responseCode}
      </Badge>
    )
  const what = d.responseCode ? String(d.responseCode) : 'No response'
  if (d.status === 'pending')
    return (
      <Badge variant="outline" className="border-transparent bg-accent text-accent-foreground">
        <ClockIcon data-icon="inline-start" />
        {d.attempt === 0 ? 'Sending' : `${what}, retry ${d.attempt + 1}`}
      </Badge>
    )
  return (
    <Badge variant="destructive">
      <XIcon data-icon="inline-start" />
      {what}
    </Badge>
  )
}

const ERRORS: Record<string, string> = {
  timeout: 'No answer within 10 seconds.',
  connection_failed: "Couldn't connect to the address.",
  private_address: 'The address points to a private network that isn’t allowed.',
  https_required: 'Plain http is only allowed to allowlisted networks.',
  dns_failed: "The host name couldn't be found.",
  webhook_off: 'The webhook was off.',
}

function DeliveryRows({ d, onRedeliver, canManage }: { d: WebhookDelivery; onRedeliver: () => void; canManage: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <Fragment>
      <TableRow>
        <TableCell>{EVENT_LABELS[d.event] ?? d.event}</TableCell>
        <TableCell>
          <ResultBadge d={d} />
        </TableCell>
        <TableCell className="tabular-nums text-muted-foreground">{formatDateTimeSeconds(d.updatedAt)}</TableCell>
        <TableCell className="tabular-nums text-muted-foreground">
          {d.durationMs === null ? '-' : d.durationMs >= 1000 ? `${(d.durationMs / 1000).toFixed(1)} s` : `${d.durationMs} ms`}
        </TableCell>
        <TableCell className="w-10">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Delivery actions">
                <EllipsisIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setOpen((o) => !o)}>{open ? 'Hide details' : 'Show details'}</DropdownMenuItem>
              {canManage && <DropdownMenuItem onSelect={onRedeliver}>Redeliver</DropdownMenuItem>}
            </DropdownMenuContent>
          </DropdownMenu>
        </TableCell>
      </TableRow>
      {open && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={5} className="whitespace-normal">
            <div className="flex flex-col gap-3 py-1 text-sm">
              <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1">
                <dt className="text-muted-foreground">Event id</dt>
                <dd className="font-mono text-xs">{d.eventId}</dd>
                <dt className="text-muted-foreground">Attempts</dt>
                <dd>{d.attempt}</dd>
                {d.nextAttemptAt && d.status === 'pending' && (
                  <>
                    <dt className="text-muted-foreground">Next attempt</dt>
                    <dd className="tabular-nums">{formatDateTimeSeconds(d.nextAttemptAt)}</dd>
                  </>
                )}
                {d.error && !d.error.startsWith('http_') && (
                  <>
                    <dt className="text-muted-foreground">Problem</dt>
                    <dd>{ERRORS[d.error] ?? d.error}</dd>
                  </>
                )}
              </dl>
              <div className="flex flex-col gap-1">
                <span className="text-muted-foreground">Request body</span>
                <pre dir="ltr" className="max-h-64 overflow-auto rounded-md border bg-muted p-3 font-mono text-xs">
                  {JSON.stringify(d.payload, null, 2)}
                </pre>
              </div>
              {d.responseSnippet && (
                <div className="flex flex-col gap-1">
                  <span className="text-muted-foreground">Response (first 1 KB)</span>
                  <pre dir="ltr" className="max-h-40 overflow-auto rounded-md border bg-muted p-3 font-mono text-xs whitespace-pre-wrap">
                    {d.responseSnippet}
                  </pre>
                </div>
              )}
            </div>
          </TableCell>
        </TableRow>
      )}
    </Fragment>
  )
}

function WebhookSheet({
  form,
  hook,
  canManage,
  onOpenChange,
  onEdit,
}: {
  form: FormSummary
  hook: Webhook | null
  canManage: boolean
  onOpenChange: (open: boolean) => void
  onEdit: (hook: Webhook) => void
}) {
  const queryClient = useQueryClient()
  const [confirm, setConfirm] = useState<'rotate' | 'delete' | null>(null)
  const [secret, setSecret] = useState<string | null>(null)
  const deliveries = useInfiniteQuery({
    queryKey: ['deliveries', hook?.id],
    enabled: !!hook && canManage,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.listDeliveries(form.id, hook!.id, pageParam),
    getNextPageParam: (last) => (last.length === 25 ? last[last.length - 1].createdAt : undefined),
    refetchInterval: (q) =>
      q.state.data?.pages.some((p) => p.some((d) => d.status === 'pending' && d.attempt === 0)) ? 2000 : false,
  })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['webhooks', form.id] })
    void queryClient.invalidateQueries({ queryKey: ['deliveries', hook?.id] })
  }
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.patchWebhook(form.id, hook!.id, { enabled }),
    onSuccess: (h) => {
      refresh()
      toast(h.enabled ? 'Webhook turned on' : 'Webhook turned off')
    },
  })
  const test = useMutation({
    mutationFn: () => api.testWebhook(form.id, hook!.id),
    onSuccess: () => {
      refresh()
      toast('Test event sent')
    },
    onError: () => toast.error("Couldn't send the test event. Try again."),
  })
  const redeliver = useMutation({
    mutationFn: (id: string) => api.redeliver(form.id, hook!.id, id),
    onSuccess: () => {
      refresh()
      toast('Redelivery queued')
    },
    onError: () => toast.error("Couldn't redeliver. Turn the webhook on first."),
  })
  const rotate = useMutation({
    mutationFn: () => api.rotateWebhookSecret(form.id, hook!.id),
    onSuccess: (r) => {
      refresh()
      setSecret(r.secret)
    },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteWebhook(form.id, hook!.id),
    onSuccess: () => {
      refresh()
      onOpenChange(false)
      toast('Webhook deleted')
    },
  })
  const rows = deliveries.data?.pages.flat() ?? []
  return (
    <Sheet open={!!hook} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
        {hook && (
          <>
            <SheetHeader className="gap-3 border-b">
              <SheetTitle className="pe-8">Webhook</SheetTitle>
              <SheetDescription className="font-mono text-xs break-all text-foreground" dir="ltr">
                {hook.url}
              </SheetDescription>
              <div className="flex flex-wrap items-center gap-3">
                <Field orientation="horizontal" className="w-auto">
                  <Switch
                    id="webhook-enabled"
                    checked={hook.enabled}
                    disabled={!canManage || toggle.isPending}
                    onCheckedChange={(on) => toggle.mutate(on)}
                  />
                  <FieldLabel htmlFor="webhook-enabled" className="font-normal">
                    {hook.enabled ? 'On' : 'Off'}
                  </FieldLabel>
                </Field>
                <span className="text-sm text-muted-foreground">{hook.events.map((e) => EVENT_LABELS[e]).join(', ')}</span>
              </div>
              {canManage && (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" disabled={!hook.enabled || test.isPending} onClick={() => test.mutate()}>
                    Send test event
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setConfirm('rotate')}>
                    Rotate secret
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => onEdit(hook)}>
                    Edit
                  </Button>
                  <Button size="sm" variant="outline" className="text-destructive" onClick={() => setConfirm('delete')}>
                    Delete
                  </Button>
                </div>
              )}
            </SheetHeader>
            <div className="flex flex-col gap-4 p-4">
              {hook.disabledReason === 'failures' && (
                <Alert variant="destructive">
                  <XIcon />
                  <AlertTitle>Turned off after 20 failed deliveries in a row</AlertTitle>
                  <AlertDescription>Fix your endpoint, then turn the webhook back on.</AlertDescription>
                </Alert>
              )}
              {hook.rotatingUntil && (
                <p className="text-sm text-muted-foreground">
                  Requests are signed with the old and the new secret until {formatDateTimeSeconds(hook.rotatingUntil)}.
                </p>
              )}
              <h3 className="text-base font-medium">Deliveries</h3>
              {!canManage ? (
                <p className="text-sm text-muted-foreground">Only owners can see the delivery log.</p>
              ) : deliveries.isPending ? (
                <Skeleton className="h-32" />
              ) : rows.length === 0 ? (
                <p className="text-sm text-muted-foreground">No deliveries yet. Send a test event to check your endpoint.</p>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Event</TableHead>
                        <TableHead>Result</TableHead>
                        <TableHead>Time</TableHead>
                        <TableHead>Duration</TableHead>
                        <TableHead>
                          <span className="sr-only">Actions</span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.map((d) => (
                        <DeliveryRows key={d.id} d={d} canManage={canManage} onRedeliver={() => redeliver.mutate(d.id)} />
                      ))}
                    </TableBody>
                  </Table>
                  {deliveries.hasNextPage && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="self-start"
                      disabled={deliveries.isFetchingNextPage}
                      onClick={() => void deliveries.fetchNextPage()}
                    >
                      <ChevronDownIcon />
                      Load more
                    </Button>
                  )}
                </>
              )}
            </div>
          </>
        )}
      </SheetContent>
      <AlertDialog open={confirm !== null} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm === 'rotate' ? 'Rotate the signing secret?' : 'Delete this webhook?'}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirm === 'rotate'
                ? 'Requests are signed with both the old and the new secret for 24 hours, so you can update your system without missing any.'
                : 'JustForms stops sending to it at once. Its delivery log is deleted too.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant={confirm === 'delete' ? 'destructive' : 'default'}
              onClick={() => (confirm === 'rotate' ? rotate.mutate() : remove.mutate())}
            >
              {confirm === 'rotate' ? 'Rotate secret' : 'Delete webhook'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog open={secret !== null} onOpenChange={(o) => !o && setSecret(null)}>
        <DialogContent className="sm:max-w-lg">{secret && <SecretStep secret={secret} onDone={() => setSecret(null)} />}</DialogContent>
      </Dialog>
    </Sheet>
  )
}

export function WebhooksCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const queryClient = useQueryClient()
  const hooks = useQuery({ queryKey: ['webhooks', form.id], queryFn: () => api.listWebhooks(form.id) })
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<Webhook | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const addButton = useRef<HTMLButtonElement>(null)
  const open = hooks.data?.find((h) => h.id === openId) ?? null
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['webhooks', form.id] })
  return (
    <Card className="rounded-md border shadow-none ring-0">
      <CardHeader>
        <CardTitle>Webhooks</CardTitle>
        <CardDescription>
          Send each new response to another system as it arrives. Requests are signed; see the webhook documentation for
          how to check them. Each webhook saves from its own dialog; switching one on or off applies right away.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {hooks.isPending ? (
          <Skeleton className="h-16" />
        ) : hooks.isError ? (
          <p className="text-sm text-destructive">Couldn't load webhooks. Reload the page to try again.</p>
        ) : hooks.data.length === 0 ? (
          <Empty className="border border-dashed p-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <WebhookIcon />
              </EmptyMedia>
              <EmptyTitle>No webhooks yet</EmptyTitle>
              <EmptyDescription>Add one to send new responses to another system.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ItemGroup className="gap-2">
            {hooks.data.map((h) => (
              <Item key={h.id} variant="outline" size="sm" className="flex-wrap">
                <ItemContent className="min-w-0 basis-60">
                  <ItemTitle className="w-full">
                    <bdi dir="ltr" className="truncate font-mono text-xs" title={h.url}>
                      {h.url}
                    </bdi>
                  </ItemTitle>
                  <ItemDescription className="flex flex-wrap items-center gap-2">
                    <StateBadge hook={h} />
                    <span>
                      {h.events.length} {h.events.length === 1 ? 'event' : 'events'}
                    </span>
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Button variant="outline" size="sm" onClick={() => setOpenId(h.id)}>
                    Open
                  </Button>
                </ItemActions>
              </Item>
            ))}
          </ItemGroup>
        )}
        {canManage && (
          <Button ref={addButton} variant="outline" className="self-start" onClick={() => setAdding(true)}>
            <PlusIcon />
            Add webhook
          </Button>
        )}
      </CardContent>
      <WebhookDialog
        open={adding || editing !== null}
        initial={editing ?? undefined}
        onOpenChange={(o) => {
          if (!o) {
            setAdding(false)
            setEditing(null)
          }
        }}
        onSave={async (body) => {
          if (editing) {
            await api.patchWebhook(form.id, editing.id, body)
            refresh()
            toast('Webhook saved')
            return null
          }
          const created = await api.createWebhook(form.id, body)
          refresh()
          toast('Webhook added')
          return created.secret
        }}
      />
      <WebhookSheet
        form={form}
        hook={open}
        canManage={canManage}
        onOpenChange={(o) => !o && setOpenId(null)}
        onEdit={(h) => setEditing(h)}
      />
    </Card>
  )
}
