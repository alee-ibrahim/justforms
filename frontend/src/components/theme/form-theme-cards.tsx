/**
 * Organisation settings › Form theme and a form's Settings › Appearance
 * (docs/ux/FORM-THEME-SCREENS.md 3.2-3.3).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ImageIcon, Undo2Icon, UploadIcon } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { ConfirmDialog } from '@/components/layout/confirm-dialog'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { api, ApiError, type FormSummary, type FormTheme, type ThemeOut } from '@/lib/api'
import { brandingQuery, formThemeQuery, meQuery, orgThemeQuery } from '@/lib/queries'
import { JUSTFORMS_DEFAULTS, useThemePreview, type ThemeBase } from '@/lib/theme'
import { isOrgAdmin } from '@/lib/roles'
import { useDelayed } from '@/lib/use-delayed'

import { ThemeControls } from './theme-controls'
import { ThemePreview } from './theme-preview'


const clean = (t: FormTheme): FormTheme => ({ ...t, colors: { ...t.colors } })

function Loading({ error, retry }: { error: boolean; retry: () => void }) {
  const show = useDelayed(!error)
  if (error)
    return (
      <Alert>
        <AlertDescription className="flex flex-wrap items-center gap-2">
          Couldn't load the form theme. Reload the page.
          <Button variant="outline" size="sm" onClick={retry}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    )
  return show ? <Skeleton className="h-96 w-full" /> : null
}

export function OrgFormThemeCard({ orgId }: { orgId: string }) {
  const query = useQuery(orgThemeQuery(orgId))
  if (!query.data) return <Loading error={query.isError} retry={() => void query.refetch()} />
  return <OrgFormTheme orgId={orgId} data={query.data} />
}

function OrgFormTheme({ orgId, data }: { orgId: string; data: ThemeOut }) {
  const queryClient = useQueryClient()
  const branding = useQuery(brandingQuery(orgId))
  const [draft, setDraft] = useState<FormTheme>(() => clean(data.theme))
  const report = useThemePreview(orgId, draft, undefined, data.preview)
  const dirty = JSON.stringify(draft) !== JSON.stringify(data.theme)
  const brandPrimary = branding.data?.primaryColor ?? branding.data?.instance.primaryColor ?? undefined
  const base: ThemeBase = { ...JUSTFORMS_DEFAULTS, colors: brandPrimary ? { primary: brandPrimary } : {} }
  const save = useMutation({
    mutationFn: () => api.saveOrgTheme(orgId, draft),
    onSuccess: (next) => {
      queryClient.setQueryData(orgThemeQuery(orgId).queryKey, next)
      void queryClient.invalidateQueries({ queryKey: ['form-theme'] })
      setDraft(clean(next.theme))
      toast('Form theme saved')
    },
    onError: () => toast.error("Couldn't save the form theme. Try again."),
  })
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
      <Card className="rounded-md border shadow-none ring-0">
        <CardHeader>
          <CardTitle>Form theme</CardTitle>
          <CardDescription>
            How your forms look to the people filling them in. Every form uses these unless its own settings change
            them.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {!data.canEdit && (
            <Alert>
              <AlertDescription>Only organisation admins can change the form theme.</AlertDescription>
            </Alert>
          )}
          <ThemeControls
            value={draft}
            onChange={setDraft}
            base={base}
            scope="organisation"
            fonts={data.fonts}
            fontSource={data.fontSource}
            adjustments={report?.adjustments ?? []}
            orgId={orgId}
            disabled={!data.canEdit}
          />
        </CardContent>
        {data.canEdit && (
          <CardFooter className="flex justify-end gap-2 border-t">
            <Button variant="outline" disabled={!dirty || save.isPending} onClick={() => setDraft(clean(data.theme))}>
              Discard
            </Button>
            <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending && <Spinner />}
              Save theme
            </Button>
          </CardFooter>
        )}
      </Card>
      <ThemePreview report={report} className="lg:sticky lg:top-[calc(var(--studio-top)+1rem)]" />
    </div>
  )
}

export function FormAppearanceCard({ form }: { form: FormSummary }) {
  const query = useQuery(formThemeQuery(form.id))
  if (!query.data) return <Loading error={query.isError} retry={() => void query.refetch()} />
  return <FormAppearance form={form} data={query.data} />
}

function FormAppearance({ form, data }: { form: FormSummary; data: ThemeOut }) {
  const queryClient = useQueryClient()
  const me = useQuery(meQuery)
  const [draft, setDraft] = useState<FormTheme>(() => clean(data.theme))
  const branding = useQuery(brandingQuery(form.orgId))
  const org = {
    ...(data.organisation ?? { theme: { colors: {} }, resolved: JUSTFORMS_DEFAULTS.resolved }),
    logoUrl: branding.data?.images.logo?.url ?? null,
  }
  const report = useThemePreview(form.orgId, org.theme, draft, data.preview, form.id)
  const dirty = JSON.stringify(draft) !== JSON.stringify(data.theme)
  const admin = isOrgAdmin(me.data, form.orgId)
  const save = useMutation({
    mutationFn: () => api.saveFormTheme(form.id, draft),
    onSuccess: (next) => {
      queryClient.setQueryData(formThemeQuery(form.id).queryKey, next)
      setDraft(clean(next.theme))
      toast('Appearance saved')
    },
    onError: () => toast.error("Couldn't save the appearance. Try again."),
  })
  const language = /[ހ-޿]/.test(form.title) ? 'dv' : 'en'
  // Controls and preview side by side, the preview sticky, as on Organisation settings (REVIEW P2-12).
  return (
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
      <Card className="rounded-md border shadow-none ring-0">
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>
            Applies to this form only; everything else follows the organisation's form theme. Changes save when you
            choose Save appearance.
            {admin && (
              <>
                {' '}
                <Link to="/settings/form-theme" search={{ org: form.orgId }} className="text-primary underline underline-offset-4">
                  Edit the organisation theme
                </Link>
              </>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ThemeControls
            value={draft}
            onChange={setDraft}
            base={{ resolved: org.resolved, colors: org.theme.colors }}
            scope="form"
            fonts={data.fonts}
            fontSource={data.fontSource}
            adjustments={report?.adjustments ?? []}
            orgId={form.orgId}
            disabled={!data.canEdit}
            logo={<FormLogoRow form={form} data={data} orgLogoUrl={org.logoUrl ?? null} />}
          />
        </CardContent>
        {data.canEdit && (
          <CardFooter className="flex justify-end gap-2 border-t">
            <Button variant="outline" disabled={!dirty || save.isPending} onClick={() => setDraft(clean(data.theme))}>
              Discard
            </Button>
            <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending && <Spinner />}
              Save appearance
            </Button>
          </CardFooter>
        )}
      </Card>
      <ThemePreview report={report} language={language} className="xl:sticky xl:top-[calc(var(--studio-top)+1rem)]" />
    </div>
  )
}

const LOGO_ERRORS: Record<string, string> = {
  bad_type: "That file isn't a PNG or SVG.",
  too_large: 'The file is larger than 512 KB.',
  too_large_pixels: 'The image is larger than 4096 pixels on a side.',
  svg_unsafe: "This SVG contains scripts or external content and can't be used.",
  svg_no_size: 'This SVG has no size. Add a viewBox and try again.',
}

/** Form › Settings › Appearance: the form's own logo, saved on upload
 * (docs/ux/INLINE-EDIT-AND-LOGO-SCREENS.md 2.2). */
function FormLogoRow({ form, data, orgLogoUrl }: { form: FormSummary; data: ThemeOut; orgLogoUrl: string | null }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const own = data.logo ?? null
  const shown = own?.url ?? orgLogoUrl
  const done = (next: ThemeOut, message: string) => {
    queryClient.setQueryData(formThemeQuery(form.id).queryKey, next)
    void queryClient.invalidateQueries({ queryKey: ['theme-preview'] })
    toast(message)
  }
  const upload = useMutation({
    mutationFn: (file: File) => api.uploadFormLogo(form.id, file),
    onMutate: () => setError(null),
    onSuccess: (next) => done(next, 'Logo uploaded'),
    onError: (err) => {
      const code = err instanceof ApiError && typeof err.detail === 'string' ? err.detail : ''
      setError(LOGO_ERRORS[code] ?? "Couldn't upload the logo. Try again.")
    },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteFormLogo(form.id),
    onSuccess: (next) => done(next, 'Using the organisation logo'),
    onError: () => toast.error("Couldn't remove the logo. Try again."),
  })
  const busy = upload.isPending || remove.isPending
  return (
    <Field data-invalid={error ? true : undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <FieldLabel htmlFor="theme-logo">Logo</FieldLabel>
        {!own && <Badge variant="outline">Organisation</Badge>}
        {own && data.canEdit && (
          <Button type="button" variant="ghost" size="sm" className="ms-auto" disabled={busy} onClick={() => setConfirming(true)}>
            {remove.isPending ? <Spinner /> : <Undo2Icon />}
            Use organisation logo
          </Button>
        )}
        <ConfirmDialog
          open={confirming}
          onOpenChange={setConfirming}
          title="Remove this form's logo?"
          description="The uploaded logo is deleted and the form shows the organisation logo. To use it again, upload it again."
          action="Remove logo"
          onConfirm={() => remove.mutate()}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex h-10 min-w-20 max-w-48 items-center justify-center overflow-hidden rounded-md border bg-muted px-2">
          {shown ? (
            <img src={shown} alt="" className="h-8 w-auto max-w-44 object-contain" />
          ) : (
            <ImageIcon className="size-4 text-muted-foreground" aria-label="No logo" />
          )}
        </div>
        <input
          ref={input}
          id="theme-logo"
          type="file"
          accept="image/png,image/svg+xml"
          className="sr-only"
          disabled={!data.canEdit || busy}
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) upload.mutate(file)
          }}
        />
        {data.canEdit && (
          <Button type="button" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
            {upload.isPending ? <Spinner /> : <UploadIcon />}
            {own ? 'Replace' : 'Upload logo'}
          </Button>
        )}
      </div>
      <FieldDescription>PNG or SVG, up to 512 KB. Shown above the form title, on its emails and PDFs.</FieldDescription>
      {own?.mime === 'image/svg+xml' && (
        <FieldDescription>
          Emails show the organisation logo: mail apps can't show SVG. Upload a PNG to use this logo in emails too.
        </FieldDescription>
      )}
      {error && <FieldError>{error}</FieldError>}
    </Field>
  )
}
