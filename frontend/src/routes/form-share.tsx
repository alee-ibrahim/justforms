/** Share (PHASE-2-SCREENS 3.2): link, open/closed, short address, embed code, versions. */
import { useQuery } from '@tanstack/react-query'
import { CheckIcon, CopyIcon, ExternalLinkIcon, Link2Icon } from 'lucide-react'
import { useContext, useState } from 'react'
import { toast } from 'sonner'

import { useFormSummary } from '@/components/builder/form-context'
import { BuilderContext } from '@/components/builder/store'
import { usePublish } from '@/components/builder/use-publish'
import { AccessCard } from '@/components/forms/access-card'
import { hostPrefix, normalizeSlug, useSlugCheck } from '@/components/forms/slug'
import { SlugStatus } from '@/components/forms/slug-field'
import { usePatchForm } from '@/components/forms/use-patch-form'
import { PageContainer } from '@/components/layout/page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput, InputGroupText } from '@/components/ui/input-group'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, type FormSummary } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { meQuery, versionsQuery } from '@/lib/queries'

function useCopy() {
  const [copied, setCopied] = useState<string | null>(null)
  return {
    copied,
    copy: (key: string, text: string) =>
      void navigator.clipboard?.writeText(text).then(() => {
        setCopied(key)
        window.setTimeout(() => setCopied((c) => (c === key ? null : c)), 2000)
      }),
  }
}

function PublishFirst() {
  const form = useFormSummary()
  const store = useContext(BuilderContext)
  return (
    <Empty className="border bg-card">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Link2Icon />
        </EmptyMedia>
        <EmptyTitle>Publish to get a link</EmptyTitle>
        <EmptyDescription>Your form isn't live yet. Publish it to share a link or embed it.</EmptyDescription>
      </EmptyHeader>
      {store && form.role !== 'viewer' && (
        <EmptyContent>
          <PublishNow form={form} />
        </EmptyContent>
      )}
    </Empty>
  )
}

function PublishNow({ form }: { form: FormSummary }) {
  const { start } = usePublish(form)
  return <Button onClick={() => start()}>Publish</Button>
}

function LinkCard({ form, url }: { form: FormSummary; url: string }) {
  const patch = usePatchForm(form)
  const { copied, copy } = useCopy()
  const [slug, setSlug] = useState<string | null>(null)
  const [slugError, setSlugError] = useState<string | null>(null)
  const owner = form.role === 'owner'
  const open = form.status === 'live'
  const editing = slug !== null && slug !== form.slug
  const check = useSlugCheck(slug ?? '', form.id, editing)
  return (
    <Card className="rounded-md shadow-none ring-0 border">
      <CardHeader>
        <CardTitle>Link</CardTitle>
        <CardDescription>Anyone with the link can fill in the form.</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-5">
          <Field orientation="horizontal">
            <div className="flex flex-1 flex-col gap-1">
              <FieldLabel htmlFor="accepting">Accepting responses</FieldLabel>
              {!open && <FieldDescription>People who open the link see “This form is closed”.</FieldDescription>}
              {!owner && <FieldDescription>Only owners can open or close the form.</FieldDescription>}
            </div>
            <Switch
              id="accepting"
              checked={open}
              disabled={!owner || patch.isPending}
              onCheckedChange={(on) =>
                patch.mutate(
                  { status: on ? 'live' : 'closed' },
                  { onSuccess: () => toast(on ? 'The form is open' : 'The form is closed') },
                )
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="share-link">Link</FieldLabel>
            <InputGroup className="max-sm:h-auto max-sm:flex-wrap">
              <InputGroupInput id="share-link" readOnly dir="ltr" value={url} onFocus={(e) => e.target.select()} />
              <InputGroupAddon align="inline-end" className="max-sm:hidden">
                <InputGroupButton size="xs" onClick={() => copy('link', url)}>
                  {copied === 'link' ? <CheckIcon /> : <CopyIcon />}
                  {copied === 'link' ? 'Copied' : 'Copy'}
                </InputGroupButton>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <InputGroupButton size="icon-xs" asChild aria-label="Open the form">
                      <a href={url} target="_blank" rel="noreferrer">
                        <ExternalLinkIcon />
                      </a>
                    </InputGroupButton>
                  </TooltipTrigger>
                  <TooltipContent>Open the form</TooltipContent>
                </Tooltip>
              </InputGroupAddon>
            </InputGroup>
            <div className="flex gap-2 sm:hidden">
              <Button variant="outline" className="flex-1" onClick={() => copy('link', url)}>
                {copied === 'link' ? <CheckIcon /> : <CopyIcon />}
                {copied === 'link' ? 'Copied' : 'Copy'}
              </Button>
              <Button variant="outline" className="flex-1" asChild>
                <a href={url} target="_blank" rel="noreferrer">
                  <ExternalLinkIcon />
                  Open
                </a>
              </Button>
            </div>
            <span className="sr-only" aria-live="polite">
              {copied === 'link' ? 'Link copied' : ''}
            </span>
          </Field>
          <Field data-invalid={slugError || check.result?.problem ? true : undefined}>
            <FieldLabel htmlFor="form-address">Address</FieldLabel>
            <div className="flex flex-wrap items-center gap-2">
              <InputGroup className="min-w-0 flex-1 basis-64">
                <InputGroupAddon>
                  <InputGroupText dir="ltr">/</InputGroupText>
                </InputGroupAddon>
                <InputGroupInput
                  id="form-address"
                  dir="ltr"
                  className="font-mono"
                  autoCapitalize="none"
                  autoComplete="off"
                  spellCheck={false}
                  value={slug ?? form.slug}
                  readOnly={slug === null}
                  aria-invalid={slugError || check.result?.problem ? true : undefined}
                  onChange={(e) => {
                    setSlug(normalizeSlug(e.target.value))
                    setSlugError(null)
                  }}
                />
              </InputGroup>
              {slug === null ? (
                <Button variant="outline" disabled={form.role === 'viewer'} onClick={() => setSlug(form.slug)}>
                  Change
                </Button>
              ) : (
                <>
                  <Button
                    disabled={!check.result?.available || patch.isPending}
                    onClick={() => {
                      patch.mutate(
                        { slug },
                        {
                          onSuccess: () => {
                            setSlug(null)
                            setSlugError(null)
                            toast('Changed the address')
                          },
                          onError: (err) =>
                            setSlugError(
                              err instanceof ApiError && err.status === 409
                                ? 'Another form already uses this address.'
                                : err instanceof ApiError && err.status === 422
                                  ? 'This address is used by JustForms itself. Try another.'
                                  : "Couldn't change the address. Try again.",
                            ),
                        },
                      )
                    }}
                  >
                    {patch.isPending && <Spinner />}
                    Save
                  </Button>
                  <Button variant="ghost" onClick={() => (setSlug(null), setSlugError(null))}>
                    Cancel
                  </Button>
                </>
              )}
            </div>
            {/* The Link field above already shows the current URL; repeat it only for a new address. */}
            {slug !== null && slug !== form.slug && (
              <FieldDescription className="break-all">
                New link: <bdi dir="ltr">{hostPrefix(form.url) + slug}</bdi>
              </FieldDescription>
            )}
            {editing && !slugError && <SlugStatus {...check} onSuggestion={setSlug} />}
            <FieldDescription>Changing it breaks links you already shared.</FieldDescription>
            {slugError && <FieldError>{slugError}</FieldError>}
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}

function EmbedCard({ form, url }: { form: FormSummary; url: string }) {
  const patch = usePatchForm(form)
  const { copied, copy } = useCopy()
  const [mode, setMode] = useState<'inline' | 'full'>('inline')
  const [sites, setSites] = useState(form.embedOrigins.join(', '))
  const [sitesError, setSitesError] = useState<string | null>(null)
  const code =
    mode === 'inline'
      ? `<iframe src="${url}?embed=1" title="${form.title.replace(/"/g, '&quot;')}" style="width:100%;border:0" height="800" loading="lazy"></iframe>\n<script>window.addEventListener('message',function(e){if(e.data&&e.data.type==='justforms:resize'){document.querySelectorAll('iframe[src^="${url}"]').forEach(function(f){f.style.height=e.data.height+'px'})}})</script>`
      : `<iframe src="${url}?embed=1" title="${form.title.replace(/"/g, '&quot;')}" style="position:fixed;inset:0;width:100%;height:100%;border:0"></iframe>`
  return (
    <Card className="rounded-md shadow-none ring-0 border">
      <CardHeader>
        <CardTitle>Embed on a website</CardTitle>
        <CardDescription>Paste this code into a page on your website.</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-5">
          <RadioGroup value={mode} onValueChange={(v) => setMode(v as typeof mode)} className="flex gap-6" aria-label="Embed mode">
            <Field orientation="horizontal" className="w-auto">
              <RadioGroupItem value="inline" id="embed-inline" />
              <FieldLabel htmlFor="embed-inline" className="font-normal">
                Inline
              </FieldLabel>
            </Field>
            <Field orientation="horizontal" className="w-auto">
              <RadioGroupItem value="full" id="embed-full" />
              <FieldLabel htmlFor="embed-full" className="font-normal">
                Full page
              </FieldLabel>
            </Field>
          </RadioGroup>
          <Field>
            <FieldLabel htmlFor="embed-code">Embed code</FieldLabel>
            <Textarea id="embed-code" readOnly dir="ltr" rows={5} className="font-mono text-xs" value={code} onFocus={(e) => e.target.select()} />
            <Button variant="outline" className="self-start" onClick={() => copy('embed', code)}>
              {copied === 'embed' ? <CheckIcon /> : <CopyIcon />}
              {copied === 'embed' ? 'Copied' : 'Copy'}
            </Button>
            <span className="sr-only" aria-live="polite">
              {copied === 'embed' ? 'Embed code copied' : ''}
            </span>
          </Field>
          <Field data-invalid={sitesError ? true : undefined}>
            <FieldLabel htmlFor="embed-sites">Allowed websites</FieldLabel>
            <Input
              id="embed-sites"
              dir="ltr"
              placeholder="https://example.org, https://intranet.example"
              value={sites}
              disabled={form.role === 'viewer'}
              onChange={(e) => setSites(e.target.value)}
              onBlur={() => {
                const list = sites.split(',').map((s) => s.trim().replace(/\/$/, '')).filter(Boolean)
                if (list.some((s) => !/^https?:\/\/[A-Za-z0-9.-]+(:\d{1,5})?$/.test(s)))
                  return setSitesError('Enter addresses like https://example.org, separated by commas')
                setSitesError(null)
                if (list.join(',') !== form.embedOrigins.join(','))
                  patch.mutate({ embedOrigins: list }, { onSuccess: () => toast('Saved allowed websites') })
              }}
            />
            <FieldDescription>Only these websites may show the form in a frame. Leave empty to allow any.</FieldDescription>
            {sitesError && <FieldError>{sitesError}</FieldError>}
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}

function VersionsCard({ form }: { form: FormSummary }) {
  const versions = useQuery(versionsQuery(form.id))
  return (
    <Card className="rounded-md shadow-none ring-0 border">
      <CardHeader>
        <CardTitle>Versions</CardTitle>
        <CardDescription>Each publish makes a new version. Submissions keep the version they were filled in.</CardDescription>
      </CardHeader>
      <CardContent>
        {versions.isPending ? (
          <Skeleton className="h-16" />
        ) : versions.isError ? (
          <p className="text-sm text-destructive">Couldn't load versions. Reload the page to try again.</p>
        ) : (
          <ItemGroup className="gap-1">
            {versions.data.map((v) => (
              <Item key={v.id} size="sm" variant="outline">
                <ItemContent>
                  <ItemTitle>
                    Version {v.version}
                    {v.version === form.currentVersion && <Badge>Live</Badge>}
                  </ItemTitle>
                  <ItemDescription className="tabular-nums">
                    <span>{formatDateTime(v.publishedAt)}</span>
                    {v.publishedByName && (
                      <span>
                        , by <bdi dir="ltr">{v.publishedByName}</bdi>
                      </span>
                    )}
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <span className="font-mono text-xs text-muted-foreground" title="Schema hash">
                    {v.schemaHash.slice(0, 8)}
                  </span>
                </ItemActions>
              </Item>
            ))}
          </ItemGroup>
        )}
      </CardContent>
    </Card>
  )
}

export function FormSharePage() {
  const form = useFormSummary()
  const me = useQuery(meQuery)
  const url = form.url
  return (
    <PageContainer width="narrow">
      <h1 className="text-xl font-semibold tracking-tight">Share</h1>
      {form.currentVersion === null ? (
        <PublishFirst />
      ) : (
        <>
          <LinkCard form={form} url={url} />
          <EmbedCard form={form} url={url} />
          <VersionsCard form={form} />
        </>
      )}
      <AccessCard formId={form.id} myEmail={me.data?.email} />
    </PageContainer>
  )
}
