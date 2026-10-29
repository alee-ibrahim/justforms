/** Organisation settings › Branding (docs/ux/BRANDING-SCREENS.md section 3). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { InfoIcon, UploadIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { BrandPreview } from '@/components/branding/brand-preview'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ConfirmDialog } from '@/components/layout/confirm-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldContent, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import {
  api,
  ApiError,
  type BrandImageKind,
  type Branding,
  type BrandingSettings,
  type PaletteReport,
} from '@/lib/api'
import type { Brand } from '@/lib/branding'
import { brandingQuery } from '@/lib/queries'
import { useDelayed } from '@/lib/use-delayed'
import { cn } from '@/lib/utils'

const HEX = /^#[0-9a-fA-F]{6}$/
const LINK = /^(https:\/\/\S{3,}|mailto:\S{3,})$/

const IMAGE_ERRORS: Record<string, string> = {
  bad_type: "That file isn't a PNG or SVG.",
  too_large: 'The file is larger than 512 KB.',
  too_large_pixels: 'The image is larger than 4096 pixels on a side.',
  not_square: 'The icon must be square.',
  icon_size: 'A PNG icon must be 64 to 1024 pixels wide.',
  svg_unsafe: "This SVG contains scripts or external content and can't be used.",
  svg_no_size: 'This SVG has no size. Give it a viewBox.',
}

const IMAGE_ROWS: { kind: BrandImageKind; label: string; hint: string }[] = [
  { kind: 'logo', label: 'Logo', hint: 'PNG or SVG, up to 512 KB. Shown up to 32 px tall. Upload a PNG to show it in emails.' },
  { kind: 'logo_dark', label: 'Logo for dark mode', hint: 'Optional. A light version of your logo for dark backgrounds.' },
  { kind: 'icon', label: 'Icon', hint: 'Square PNG (64 to 1024 px) or SVG. Used as the browser tab icon and app icon.' },
]

function fromBranding(b: Branding): BrandingSettings {
  return {
    displayName: b.displayName,
    primaryColor: b.primaryColor,
    supportUrl: b.supportUrl,
    hidePoweredBy: b.hidePoweredBy,
  }
}

function errorCode(err: unknown): string {
  return err instanceof ApiError && typeof err.detail === 'string' ? err.detail : ''
}

function ImageRow({
  orgId,
  branding,
  kind,
  label,
  hint,
}: {
  orgId: string
  branding: Branding
  kind: BrandImageKind
  label: string
  hint: string
}) {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [confirming, setConfirming] = useState(false)
  const image = branding.images[kind]
  const done = (next: Branding, message: string) => {
    queryClient.setQueryData(brandingQuery(orgId).queryKey, next)
    void queryClient.invalidateQueries({ queryKey: ['brand'] })
    toast(message)
  }
  const upload = useMutation({
    mutationFn: (file: File) => api.uploadBrandImage(orgId, kind, file),
    onSuccess: (next) => done(next, `${label} uploaded`),
  })
  const remove = useMutation({
    mutationFn: () => api.deleteBrandImage(orgId, kind),
    onSuccess: (next) => done(next, `${label} removed`),
  })
  const err = upload.error ?? remove.error
  const id = `brand-${kind}`
  return (
    <Field data-invalid={err ? true : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <div className="flex flex-wrap items-center gap-2">
        {/* The dark logo is shown on the dark desk so it can be judged. */}
        <div
          className={cn(
            'flex h-12 min-w-24 items-center justify-center rounded-md border px-3',
            kind === 'logo_dark' ? 'dark bg-background' : 'bg-muted',
          )}
        >
          {image ? (
            <img src={image.url} alt="" className="max-h-8 max-w-40 object-contain" />
          ) : (
            <span className="text-sm text-muted-foreground">None</span>
          )}
        </div>
        <input
          ref={input}
          id={id}
          type="file"
          accept="image/png,image/svg+xml"
          className="sr-only"
          disabled={!branding.canEdit}
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) upload.mutate(file)
          }}
        />
        <Button
          variant="outline"
          disabled={!branding.canEdit || upload.isPending}
          onClick={() => input.current?.click()}
          aria-describedby={`${id}-hint`}
        >
          {upload.isPending ? <Spinner /> : <UploadIcon />}
          {image?.own ? 'Replace' : `Upload ${label.toLowerCase()}`}
        </Button>
        {image?.own && (
          <Button variant="ghost" disabled={!branding.canEdit || remove.isPending} onClick={() => setConfirming(true)}>
            Remove
          </Button>
        )}
        <ConfirmDialog
          open={confirming}
          onOpenChange={setConfirming}
          title={`Remove the ${label.toLowerCase()}?`}
          description="The uploaded file is deleted for the whole organisation. To use it again, upload it again."
          action="Remove"
          onConfirm={() => remove.mutate()}
        />
      </div>
      <FieldDescription id={`${id}-hint`}>
        {hint}
        {image && !image.own && ' Using this server’s default.'}
      </FieldDescription>
      {err && <FieldError>{IMAGE_ERRORS[errorCode(err)] ?? "Couldn't upload the file. Try again."}</FieldError>}
    </Field>
  )
}

/** Contrast-checked tokens for the draft colour, for the preview and the "adjusted" note. */
function usePalette(color: string | null): PaletteReport | null {
  const [value, setValue] = useState<string | null>(color)
  useEffect(() => {
    const t = setTimeout(() => setValue(color), 250)
    return () => clearTimeout(t)
  }, [color])
  const q = useQuery({
    queryKey: ['palette', value],
    queryFn: () => api.palette(value!),
    enabled: !!value && HEX.test(value),
    staleTime: Infinity,
  })
  return value && HEX.test(value) ? (q.data ?? null) : null
}

export function BrandingCard({ orgId }: { orgId: string }) {
  const branding = useQuery(brandingQuery(orgId))
  const showSkeleton = useDelayed(branding.isPending)
  if (branding.isError)
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn't load branding</AlertTitle>
        <AlertDescription>
          Reload the page.
          <Button variant="outline" className="mt-2 w-fit" onClick={() => void branding.refetch()}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    )
  if (!branding.data)
    return showSkeleton ? (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    ) : null
  return <BrandingForm orgId={orgId} b={branding.data} />
}

function BrandingForm({ orgId, b }: { orgId: string; b: Branding }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<BrandingSettings>(() => fromBranding(b))
  const [errors, setErrors] = useState<{ color?: string; link?: string }>({})

  const save = useMutation({
    mutationFn: (body: BrandingSettings) => api.saveBranding(orgId, body),
    onSuccess: (next) => {
      queryClient.setQueryData(brandingQuery(orgId).queryKey, next)
      void queryClient.invalidateQueries({ queryKey: ['brand'] })
      setDraft(fromBranding(next))
      toast('Branding saved')
    },
    onError: () => toast.error("Couldn't save branding. Try again."),
  })

  const colorValid = !!draft.primaryColor && HEX.test(draft.primaryColor)
  // The draft colour, else the instance default (what the forms will use).
  const pal = usePalette(colorValid ? draft.primaryColor : b.instance.primaryColor)

  const canEdit = b.canEdit
  const dirty = JSON.stringify(draft) !== JSON.stringify(fromBranding(b))
  const set = (patch: Partial<BrandingSettings>) => setDraft({ ...draft, ...patch })
  const submit = () => {
    const next: typeof errors = {}
    if (draft.primaryColor && !HEX.test(draft.primaryColor)) next.color = 'Enter a colour like #0F766E.'
    if (draft.supportUrl && !LINK.test(draft.supportUrl.trim()))
      next.link = 'Enter a link starting with https:// or mailto:.'
    setErrors(next)
    if (Object.keys(next).length) return
    save.mutate({ ...draft, supportUrl: draft.supportUrl.trim(), primaryColor: draft.primaryColor || null })
  }

  const preview: Brand = {
    ...b.effective,
    name: draft.displayName.trim() || b.instance.name,
    custom: true,
    supportUrl: draft.supportUrl.trim() || b.instance.supportUrl || null,
    poweredBy: !b.canHidePoweredBy || !draft.hidePoweredBy,
  }

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
      <Card className="rounded-md border shadow-none ring-0">
        <CardHeader>
          <CardTitle>Branding</CardTitle>
          <CardDescription>
            Your name, logo and colour on the studio, your forms, emails and PDFs. Empty fields use the defaults.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup className="gap-6">
            <Field>
              <FieldLabel htmlFor="brand-name">Display name</FieldLabel>
              <Input
                id="brand-name"
                dir="auto"
                maxLength={80}
                placeholder={b.instance.name}
                value={draft.displayName}
                disabled={!canEdit}
                onChange={(e) => set({ displayName: e.target.value })}
              />
              <FieldDescription>Shown on your forms, the approver and verify pages, emails and PDFs.</FieldDescription>
            </Field>
            {IMAGE_ROWS.map((row) => (
              <ImageRow key={row.kind} orgId={orgId} branding={b} {...row} />
            ))}
            <Field data-invalid={errors.color ? true : undefined}>
              <FieldLabel htmlFor="brand-color">Primary colour</FieldLabel>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  aria-label="Pick a colour"
                  className="h-11 w-14 shrink-0 cursor-pointer rounded-md border bg-transparent p-1 disabled:cursor-not-allowed"
                  value={colorValid ? draft.primaryColor!.toLowerCase() : '#3b3fc1'}
                  disabled={!canEdit}
                  onChange={(e) => set({ primaryColor: e.target.value.toUpperCase() })}
                />
                <Input
                  id="brand-color"
                  dir="ltr"
                  className="w-32 min-w-0 font-mono uppercase"
                  placeholder={b.instance.primaryColor ?? '#3B3FC1'}
                  maxLength={7}
                  value={draft.primaryColor ?? ''}
                  disabled={!canEdit}
                  aria-invalid={errors.color ? true : undefined}
                  onChange={(e) => set({ primaryColor: e.target.value.trim() || null })}
                />
                {draft.primaryColor && canEdit && (
                  <Button variant="ghost" onClick={() => set({ primaryColor: null })}>
                    Use the default
                  </Button>
                )}
              </div>
              <FieldDescription>Buttons, links, focus rings and progress. Checked for readable contrast.</FieldDescription>
              {errors.color && <FieldError>{errors.color}</FieldError>}
              {colorValid && pal?.adjusted && (
                <Alert>
                  <InfoIcon />
                  <AlertTitle>Adjusted for contrast</AlertTitle>
                  <AlertDescription>
                    <p>
                      Adjusted to <bdi className="font-mono">{pal.light.primary}</bdi> so text stays readable (contrast{' '}
                      {pal.light.contrast.toFixed(1)}:1).
                    </p>
                    <div className="mt-1 flex items-center gap-3 text-xs" aria-hidden>
                      <span className="flex items-center gap-1.5">
                        <span className="size-4 rounded-sm border" style={{ background: pal.chosen }} /> Chosen
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="size-4 rounded-sm border" style={{ background: pal.light.primary }} /> Used
                      </span>
                    </div>
                  </AlertDescription>
                </Alert>
              )}
            </Field>
            <Field data-invalid={errors.link ? true : undefined}>
              <FieldLabel htmlFor="brand-support">Support link</FieldLabel>
              <Input
                id="brand-support"
                type="url"
                dir="ltr"
                inputMode="url"
                placeholder={b.instance.supportUrl ?? 'https://example.org/help'}
                value={draft.supportUrl}
                disabled={!canEdit}
                aria-invalid={errors.link ? true : undefined}
                onChange={(e) => set({ supportUrl: e.target.value })}
              />
              <FieldDescription>Shown at the bottom of your forms and emails.</FieldDescription>
              {errors.link && <FieldError>{errors.link}</FieldError>}
            </Field>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="brand-powered">Hide &ldquo;Powered by JustForms&rdquo;</FieldLabel>
                <FieldDescription>
                  {b.canHidePoweredBy ? 'Removes the line under your forms and emails.' : 'This server always shows it.'}
                </FieldDescription>
              </FieldContent>
              <Switch
                id="brand-powered"
                checked={b.canHidePoweredBy && draft.hidePoweredBy}
                disabled={!canEdit || !b.canHidePoweredBy}
                onCheckedChange={(v) => set({ hidePoweredBy: v })}
              />
            </Field>
          </FieldGroup>
        </CardContent>
        {canEdit && (
          <CardFooter className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" disabled={!dirty || save.isPending} onClick={() => setDraft(fromBranding(b))}>
              Discard
            </Button>
            <Button disabled={!dirty || save.isPending} onClick={submit}>
              {save.isPending && <Spinner />}
              Save branding
            </Button>
          </CardFooter>
        )}
      </Card>
      <BrandPreview brand={preview} palette={draft.primaryColor && !colorValid ? null : pal} />
    </div>
  )
}
