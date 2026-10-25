/**
 * Form › Settings › Sharing preview (docs/ux/SHARING-PREVIEW-SCREENS.md 3): the title,
 * description and image that chat apps and social sites show for the form's link, with a live
 * preview of the link card.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Undo2Icon, UploadIcon } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { api, ApiError, type FormSummary, type SharingOut } from '@/lib/api'
import { sharingQuery } from '@/lib/queries'
import { useDelayed } from '@/lib/use-delayed'
import { contentProps } from '@/schema'

const TITLE_MAX = 120
const DESCRIPTION_MAX = 300

const IMAGE_ERRORS: Record<string, string> = {
  bad_type: "That file isn't a PNG, JPEG or WebP image.",
  too_large: 'The file is larger than 5 MB.',
  too_large_pixels: 'The image is larger than 8000 pixels on a side.',
  too_small: 'The image is too small. Use one of 1200 × 630 pixels.',
}

export function SharingCard({ form }: { form: FormSummary }) {
  const query = useQuery(sharingQuery(form.id))
  const show = useDelayed(!query.isError)
  if (query.data) return <Sharing form={form} data={query.data} />
  if (query.isError)
    return (
      <Alert>
        <AlertDescription className="flex flex-wrap items-center gap-2">
          Couldn't load the sharing preview.
          <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    )
  return show ? <Skeleton className="h-96 w-full" /> : null
}

function Sharing({ form, data }: { form: FormSummary; data: SharingOut }) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(data.title ?? '')
  const [description, setDescription] = useState(data.description ?? '')
  const dirty = title.trim() !== (data.title ?? '') || description.trim() !== (data.description ?? '')
  const content = contentProps(data.language)
  const save = useMutation({
    mutationFn: () => api.saveSharing(form.id, { title: title.trim() || null, description: description.trim() || null }),
    onSuccess: (next) => {
      queryClient.setQueryData(sharingQuery(form.id).queryKey, next)
      setTitle(next.title ?? '')
      setDescription(next.description ?? '')
      toast('Sharing preview saved')
    },
    onError: () => toast.error("Couldn't save the sharing preview. Try again."),
  })
  const shown = {
    title: title.trim() || data.defaultTitle || 'Untitled form',
    description: description.trim() || data.defaultDescription,
  }
  return (
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
      <Card className="rounded-md border shadow-none ring-0">
        <CardHeader>
          <CardTitle>Sharing preview</CardTitle>
          <CardDescription>
            What chat apps and social sites show when someone shares this form's link. Text changes save when you
            choose Save; images save on upload.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {!data.published && (
            <Alert>
              <AlertDescription>
                This form isn't published yet. Until it is, its link shows only the site's name.
              </AlertDescription>
            </Alert>
          )}
          {!data.canEdit && (
            <Alert>
              <AlertDescription>Only editors and owners can change the sharing preview.</AlertDescription>
            </Alert>
          )}
          <FieldGroup className="gap-5">
            <Field>
              <FieldLabel htmlFor="share-title">Title</FieldLabel>
              <Input
                id="share-title"
                {...content}
                value={title}
                maxLength={TITLE_MAX}
                placeholder={data.defaultTitle}
                disabled={!data.canEdit}
                onChange={(e) => setTitle(e.target.value)}
              />
              <FieldDescription>Leave empty to use the form title.</FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="share-description">Description</FieldLabel>
              <Textarea
                id="share-description"
                {...content}
                value={description}
                rows={3}
                maxLength={DESCRIPTION_MAX}
                placeholder={data.defaultDescription || 'A sentence about what the form is for'}
                disabled={!data.canEdit}
                onChange={(e) => setDescription(e.target.value)}
              />
              <FieldDescription>
                Leave empty to use the form's description. Most apps show the first one or two lines.
              </FieldDescription>
            </Field>
            <ImageRow form={form} data={data} />
          </FieldGroup>
        </CardContent>
        {data.canEdit && (
          <CardFooter className="flex justify-end gap-2 border-t">
            <Button
              variant="outline"
              disabled={!dirty || save.isPending}
              onClick={() => {
                setTitle(data.title ?? '')
                setDescription(data.description ?? '')
              }}
            >
              Discard
            </Button>
            <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending && <Spinner />}
              Save
            </Button>
          </CardFooter>
        )}
      </Card>
      <LinkPreview data={data} title={shown.title} description={shown.description} />
    </div>
  )
}

function ImageRow({ form, data }: { form: FormSummary; data: SharingOut }) {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const done = (next: SharingOut, message: string) => {
    queryClient.setQueryData(sharingQuery(form.id).queryKey, next)
    toast(message)
  }
  const upload = useMutation({
    mutationFn: (file: File) => api.uploadSharingImage(form.id, file),
    onMutate: () => setError(null),
    onSuccess: (next) => done(next, 'Image uploaded'),
    onError: (err) => {
      const code = err instanceof ApiError && typeof err.detail === 'string' ? err.detail : ''
      setError(IMAGE_ERRORS[code] ?? "Couldn't upload the image. Try again.")
    },
  })
  const reset = useMutation({
    mutationFn: () => api.deleteSharingImage(form.id),
    onSuccess: (next) => done(next, 'Using the generated image'),
    onError: () => toast.error("Couldn't change the image. Try again."),
  })
  const busy = upload.isPending || reset.isPending
  const custom = data.customImage
  return (
    <Field data-invalid={error ? true : undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <FieldLabel htmlFor="share-image">Image</FieldLabel>
        <Badge variant="outline">{custom ? 'Uploaded' : 'Generated'}</Badge>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <img
          src={data.imageUrl}
          alt=""
          width={1200}
          height={630}
          className="aspect-[1200/630] w-40 rounded-md border bg-muted object-cover"
        />
        <input
          ref={input}
          id="share-image"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          disabled={!data.canEdit || busy}
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) upload.mutate(file)
          }}
        />
        {data.canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
              {upload.isPending ? <Spinner /> : <UploadIcon />}
              {custom ? 'Replace' : 'Upload image'}
            </Button>
            {custom && (
              <Button type="button" variant="ghost" disabled={busy} onClick={() => reset.mutate()}>
                {reset.isPending ? <Spinner /> : <Undo2Icon />}
                Use generated image
              </Button>
            )}
          </div>
        )}
      </div>
      <FieldDescription>
        {custom
          ? `Your image, ${custom.width} × ${custom.height} pixels.`
          : "Made from the title, description, logo and the form's theme colours. It updates when you save."}{' '}
        PNG, JPEG or WebP up to 5 MB; 1200 × 630 pixels works best, other shapes are cropped from the centre.
      </FieldDescription>
      {error && <FieldError>{error}</FieldError>}
    </Field>
  )
}

const host = (url: string) => url.replace(/^https?:\/\//, '').split('/')[0]

/** The link card as three common apps show it. Composition of tokens only; not interactive. */
function LinkPreview({ data, title, description }: { data: SharingOut; title: string; description: string }) {
  const content = contentProps(data.language)
  const image = (
    <img src={data.imageUrl} alt="" width={1200} height={630} className="aspect-[1200/630] w-full bg-muted object-cover" />
  )
  const site = <bdi dir="ltr">{host(data.url)}</bdi>
  return (
    <Card className="rounded-md border shadow-none ring-0 xl:sticky xl:top-16">
      <CardHeader>
        <CardTitle>Preview</CardTitle>
        <CardDescription>Each app draws the card its own way; these are close to what people see.</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="chat">
          <TabsList aria-label="App" className="w-full">
            <TabsTrigger value="chat">Chat app</TabsTrigger>
            <TabsTrigger value="social">Social feed</TabsTrigger>
            <TabsTrigger value="post">Short post</TabsTrigger>
          </TabsList>
          <TabsContent value="chat" className="pt-3">
            <div aria-hidden className="ms-auto max-w-80 rounded-lg bg-secondary p-1.5" data-testid="share-preview-chat">
              <div className="overflow-hidden rounded-md bg-card">
                {image}
                <div className="flex flex-col gap-0.5 px-3 py-2">
                  <p {...content} className="line-clamp-2 text-sm font-semibold">
                    {title}
                  </p>
                  {description && (
                    <p {...content} className="line-clamp-2 text-xs text-muted-foreground">
                      {description}
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">{site}</p>
                </div>
              </div>
              <p className="px-1.5 pt-1.5 text-sm text-primary">
                <bdi dir="ltr" className="break-all">
                  {data.url}
                </bdi>
              </p>
            </div>
          </TabsContent>
          <TabsContent value="social" className="pt-3">
            <div aria-hidden className="overflow-hidden rounded-md border bg-card" data-testid="share-preview-social">
              {image}
              <div className="flex flex-col gap-0.5 border-t bg-muted px-3 py-2">
                <p className="text-xs text-muted-foreground">{site}</p>
                <p {...content} className="line-clamp-2 font-semibold">
                  {title}
                </p>
                {description && (
                  <p {...content} className="line-clamp-1 text-sm text-muted-foreground">
                    {description}
                  </p>
                )}
              </div>
            </div>
          </TabsContent>
          <TabsContent value="post" className="pt-3">
            <div aria-hidden className="flex flex-col gap-1" data-testid="share-preview-post">
              <div className="relative overflow-hidden rounded-xl border">
                {image}
                <p
                  {...content}
                  className="absolute bottom-2 start-2 max-w-[85%] truncate rounded-sm bg-foreground/75 px-1.5 py-0.5 text-xs text-background"
                >
                  {title}
                </p>
              </div>
              <p className="text-xs text-muted-foreground">From {site}</p>
            </div>
          </TabsContent>
        </Tabs>
        <p className="sr-only">
          Shared links show the image, the title "{title}"{description ? `, the description "${description}"` : ''} and
          the address {data.url}.
        </p>
      </CardContent>
    </Card>
  )
}

