/**
 * Import a form from Jotform (JOTFORM-IMPORT-SCREENS 2): read a public link, pasted source,
 * an .html file or a form through the API, check the converted form and its report, then
 * create an unpublished draft.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { MonitorIcon, SmartphoneIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { FormImportReport } from '@/components/imports/form-import-report'
import { PageContainer } from '@/components/layout/page'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Item, ItemContent, ItemDescription, ItemTitle } from '@/components/ui/item'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Spinner } from '@/components/ui/spinner'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ApiError } from '@/lib/api'
import {
  importErrorText,
  importsApi,
  type FormImport,
  type JotformForm,
  type JotformRegion,
} from '@/lib/imports'
import { brandQuery, meQuery, orgThemeQuery } from '@/lib/queries'
import { canCreateForms } from '@/lib/roles'
import { canvasMode, themeScope, useFontLinks } from '@/lib/theme'
import { toggleGroupOn } from '@/lib/toggle'
import { cn } from '@/lib/utils'
import type { Uploader } from '@/renderer/context'
import { FormRenderer } from '@/renderer/form-view'
import { contentProps, isFormLanguage, type FormLanguage } from '@/schema'
import { FORM_LANGUAGES } from '@/schema/language'

type Source = 'link' | 'source' | 'file' | 'api'
const MAX_HTML = 5 * 1024 * 1024

/** Files picked in the preview stay in the browser. */
const previewUploader: Uploader = async (file) => ({
  fileId: `preview-${file.name}`,
  name: file.name,
  size: file.size,
  mime: file.type,
})

function SourceStep({ orgId, onRead }: { orgId: string; onRead: (p: FormImport) => void }) {
  const [tab, setTab] = useState<Source>('link')
  const [url, setUrl] = useState('')
  const [html, setHtml] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [region, setRegion] = useState<JotformRegion>('us')
  const [forms, setForms] = useState<JotformForm[] | null>(null)
  const [picked, setPicked] = useState('')

  const read = useMutation({
    mutationFn: async (source: Source): Promise<FormImport> => {
      if (source === 'link') return importsApi.fromHtml(orgId, { url: url.trim() })
      if (source === 'source') return importsApi.fromHtml(orgId, { html })
      if (source === 'file') return importsApi.fromHtml(orgId, { html: await file!.text() })
      return importsApi.fromApi(orgId, apiKey.trim(), region, picked)
    },
    onSuccess: onRead,
  })
  const list = useMutation({
    mutationFn: () => importsApi.listJotformForms(orgId, apiKey.trim(), region),
    onSuccess: (rows) => {
      setForms(rows)
      setPicked(rows[0]?.id ?? '')
    },
  })
  const embedUrl =
    read.error instanceof ApiError && read.error.detail === 'not_a_jotform'
      ? ((read.error.body as { formUrl?: string | null } | null)?.formUrl ?? null)
      : null
  const ready =
    (tab === 'link' && url.trim().length > 0) ||
    (tab === 'source' && html.trim().length > 0) ||
    (tab === 'file' && file !== null && !fileError) ||
    (tab === 'api' && picked !== '')

  return (
    <Card>
      <CardContent>
        <form
          className="flex flex-col gap-6"
          onSubmit={(e) => {
            e.preventDefault()
            if (ready) read.mutate(tab)
          }}
        >
          <Tabs
            value={tab}
            onValueChange={(v) => {
              setTab(v as Source)
              read.reset()
            }}
          >
            <ScrollArea className="w-full">
              <TabsList>
                <TabsTrigger value="link">Link</TabsTrigger>
                <TabsTrigger value="source">Source code</TabsTrigger>
                <TabsTrigger value="file">File</TabsTrigger>
                <TabsTrigger value="api">API key</TabsTrigger>
              </TabsList>
            </ScrollArea>
            <TabsContent value="link" className="pt-4">
              <Field>
                <FieldLabel htmlFor="jf-url">Form link</FieldLabel>
                <Input
                  id="jf-url"
                  type="text"
                  inputMode="url"
                  dir="ltr"
                  autoCapitalize="none"
                  spellCheck={false}
                  placeholder="https://form.jotform.com/…"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
                <FieldDescription>
                  The public link of the form, or just its number. Only links on jotform.com work.
                </FieldDescription>
              </Field>
            </TabsContent>
            <TabsContent value="source" className="pt-4">
              <Field>
                <FieldLabel htmlFor="jf-html">Source code</FieldLabel>
                <Textarea
                  id="jf-html"
                  rows={10}
                  dir="ltr"
                  spellCheck={false}
                  className="max-h-80 font-mono text-xs"
                  value={html}
                  maxLength={MAX_HTML}
                  onChange={(e) => setHtml(e.target.value)}
                />
                <FieldDescription>
                  In Jotform open Publish, then Platforms, then Source code, and copy everything. Saving the
                  form's page from the browser works too.
                </FieldDescription>
              </Field>
            </TabsContent>
            <TabsContent value="file" className="pt-4">
              <Field data-invalid={fileError ? true : undefined}>
                <FieldLabel htmlFor="jf-file">HTML file</FieldLabel>
                <Input
                  id="jf-file"
                  type="file"
                  accept=".html,.htm,.txt,text/html"
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null
                    setFile(f)
                    setFileError(f && f.size > MAX_HTML ? 'The file is larger than 5 MB.' : null)
                  }}
                />
                <FieldDescription>{fileError ?? 'An .html file of the form, up to 5 MB.'}</FieldDescription>
              </Field>
            </TabsContent>
            <TabsContent value="api" className="pt-4">
              <FieldGroup>
                <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_12rem]">
                  <Field>
                    <FieldLabel htmlFor="jf-key">API key</FieldLabel>
                    <Input
                      id="jf-key"
                      type="password"
                      autoComplete="off"
                      dir="ltr"
                      spellCheck={false}
                      value={apiKey}
                      onChange={(e) => {
                        setApiKey(e.target.value)
                        setForms(null)
                        setPicked('')
                      }}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="jf-region">Data region</FieldLabel>
                    <NativeSelect id="jf-region" value={region} onChange={(e) => setRegion(e.target.value as JotformRegion)}>
                      <NativeSelectOption value="us">United States</NativeSelectOption>
                      <NativeSelectOption value="eu">Europe</NativeSelectOption>
                      <NativeSelectOption value="hipaa">HIPAA</NativeSelectOption>
                    </NativeSelect>
                  </Field>
                </div>
                <FieldDescription>
                  Find it in Jotform under Settings, API. JustForms uses it for this import only and never stores it.
                </FieldDescription>
                <div>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={apiKey.trim().length < 16 || list.isPending}
                    onClick={() => list.mutate()}
                  >
                    {list.isPending && <Spinner />}
                    List forms
                  </Button>
                </div>
                {list.isError && (
                  <Alert variant="destructive">
                    <AlertDescription>{importErrorText(list.error)}</AlertDescription>
                  </Alert>
                )}
                {forms && forms.length === 0 && (
                  <p className="text-sm text-muted-foreground">This account has no forms.</p>
                )}
                {forms && forms.length > 0 && (
                  <FieldSet>
                    <FieldLegend variant="label">Form to import</FieldLegend>
                    <ScrollArea className="max-h-80 rounded-md border">
                      <RadioGroup value={picked} onValueChange={setPicked} className="gap-0 p-1">
                        {forms.map((f) => (
                          <Item key={f.id} size="xs" asChild>
                            <label htmlFor={`jf-form-${f.id}`} className="cursor-pointer pointer-coarse:min-h-11">
                              <RadioGroupItem value={f.id} id={`jf-form-${f.id}`} />
                              <ItemContent className="min-w-0">
                                <ItemTitle>
                                  <bdi dir="auto">{f.title || 'Untitled form'}</bdi>
                                </ItemTitle>
                                <ItemDescription>
                                  <span className="tabular-nums">{f.count}</span> {f.count === 1 ? 'submission' : 'submissions'}
                                  {f.status && f.status !== 'ENABLED' ? `, ${f.status.toLowerCase()}` : ''}
                                </ItemDescription>
                              </ItemContent>
                            </label>
                          </Item>
                        ))}
                      </RadioGroup>
                    </ScrollArea>
                  </FieldSet>
                )}
              </FieldGroup>
            </TabsContent>
          </Tabs>
          {read.isError && (
            <Alert variant="destructive">
              <AlertDescription>
                {embedUrl ? (
                  <span>
                    This is the embed code, not the form itself.{' '}
                    <Button
                      type="button"
                      variant="link"
                      className="h-auto p-0 align-baseline"
                      onClick={() => {
                        setUrl(embedUrl)
                        setTab('link')
                        read.reset()
                      }}
                    >
                      Use <bdi dir="ltr">{embedUrl}</bdi> instead
                    </Button>
                  </span>
                ) : (
                  importErrorText(read.error)
                )}
              </AlertDescription>
            </Alert>
          )}
          <div className="flex justify-end">
            <Button type="submit" disabled={!ready || read.isPending}>
              {read.isPending && <Spinner />}
              Read form
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function Preview({ preview, language, orgId, orgSlug }: { preview: FormImport; language: FormLanguage; orgId: string; orgSlug: string }) {
  const [device, setDevice] = useState<'phone' | 'desktop'>('phone')
  const form = { ...preview.schema, settings: { ...preview.schema.settings, language } }
  // The draft gets the organisation's form theme, so the preview wears it too, the same way
  // Settings > Appearance does (REVIEW P2-17). Until it loads, JustForms' own look.
  const theme = useQuery(orgThemeQuery(orgId)).data?.preview
  const brand = useQuery(brandQuery(orgSlug)).data
  useFontLinks(theme?.fonts)
  const scope = themeScope(theme, canvasMode(theme))
  return (
    <Card className="min-w-0">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle>Preview</CardTitle>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={device}
          onValueChange={(v) => v && setDevice(v as typeof device)}
          aria-label="Device"
          className={toggleGroupOn}
        >
          <ToggleGroupItem value="phone">
            <SmartphoneIcon />
            Phone
          </ToggleGroupItem>
          <ToggleGroupItem value="desktop">
            <MonitorIcon />
            Desktop
          </ToggleGroupItem>
        </ToggleGroup>
      </CardHeader>
      <CardContent>
        <div
          {...scope}
          className={cn(
            scope.className,
            'mx-auto w-full overflow-hidden bg-background text-foreground',
            device === 'phone' ? 'max-w-[390px] rounded-xl border' : 'rounded-md',
          )}
        >
          <FormRenderer
            key={`${device}-${language}`}
            form={form}
            mode="preview"
            frame={device === 'phone' ? 'bare' : 'page'}
            brand={brand}
            orgName={brand?.name}
            theme={theme?.options}
            uploader={previewUploader}
            onSubmit={async () => ({ ok: true, reference: 'Preview' })}
          />
        </div>
      </CardContent>
    </Card>
  )
}

function ResultStep({
  preview,
  orgId,
  orgSlug,
  onRestart,
}: {
  preview: FormImport
  orgId: string
  orgSlug: string
  onRestart: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(preview.schema.settings.title)
  const [language, setLanguage] = useState<FormLanguage>(preview.language)
  const [view, setView] = useState<'report' | 'preview'>('report')
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => heading.current?.focus(), [])
  const create = useMutation({
    mutationFn: () => importsApi.createForm(preview.id, { title: title.trim(), language }),
    onSuccess: async ({ formId }) => {
      await queryClient.invalidateQueries({ queryKey: ['forms'] })
      toast.success('Draft created. Check it, then publish.')
      await navigate({ to: '/forms/$formId/edit', params: { formId } })
    },
  })
  const detected = FORM_LANGUAGES[preview.detectedLanguage].label

  const createCard = (
    <Card>
      <CardHeader>
        <CardTitle>Create the draft</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (title.trim()) create.mutate()
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="jf-title">Title</FieldLabel>
              <Input
                id="jf-title"
                required
                maxLength={500}
                {...contentProps(language)}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </Field>
            <FieldSet>
              <FieldLegend variant="label">Form language</FieldLegend>
              <RadioGroup
                value={language}
                onValueChange={(v) => isFormLanguage(v) && setLanguage(v)}
                className="flex gap-6"
              >
                {(['en', 'dv'] as const).map((l) => (
                  <Field key={l} orientation="horizontal" className="w-auto">
                    <RadioGroupItem value={l} id={`jf-lang-${l}`} />
                    <FieldLabel htmlFor={`jf-lang-${l}`} className="font-normal">
                      {FORM_LANGUAGES[l].label}
                    </FieldLabel>
                  </Field>
                ))}
              </RadioGroup>
              <FieldDescription>
                {language === preview.detectedLanguage
                  ? `Detected from the text: ${detected}.`
                  : `Most of the text is in ${detected}.`}
              </FieldDescription>
            </FieldSet>
          </FieldGroup>
          {create.isError && (
            <Alert variant="destructive">
              <AlertDescription>Couldn't create the draft. Try again.</AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={!title.trim() || create.isPending}>
              {create.isPending && <Spinner />}
              Create draft
            </Button>
            <Button type="button" variant="ghost" onClick={onRestart}>
              Start over
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )

  return (
    <>
      <div className="flex flex-col gap-1">
        <h2 ref={heading} tabIndex={-1} className="text-lg font-semibold tracking-tight outline-none">
          Check the result
        </h2>
        <p className="text-sm text-muted-foreground">
          Nothing is created until you choose Create draft. You can change everything in the builder afterwards.
        </p>
      </div>
      <Tabs value={view} onValueChange={(v) => setView(v as typeof view)} className="lg:hidden">
        <TabsList>
          <TabsTrigger value="report">Report</TabsTrigger>
          <TabsTrigger value="preview">Preview</TabsTrigger>
        </TabsList>
      </Tabs>
      <div className="grid items-start gap-6 lg:grid-cols-[24rem_minmax(0,1fr)]">
        <div className={cn('flex min-w-0 flex-col gap-6', view !== 'report' && 'max-lg:hidden')}>
          {createCard}
          <FormImportReport preview={preview} language={language} />
        </div>
        <div className={cn('min-w-0', view !== 'preview' && 'max-lg:hidden')}>
          <Preview preview={preview} language={language} orgId={orgId} orgSlug={orgSlug} />
        </div>
      </div>
    </>
  )
}

export function JotformImportPage() {
  const { data: me } = useQuery(meQuery)
  const org = me?.orgs[0]
  const [preview, setPreview] = useState<FormImport | null>(null)
  return (
    <PageContainer>
      <div className="flex flex-col gap-2">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/forms">Forms</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>Import from Jotform</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <h1 className="text-xl font-semibold tracking-tight">Import from Jotform</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Bring a Jotform form into JustForms as an unpublished draft. Nothing is created until you check the result.
        </p>
      </div>
      {!org ? (
        <Alert>
          <AlertDescription>You aren't a member of any organisation yet. Ask an administrator to add you.</AlertDescription>
        </Alert>
      ) : !canCreateForms(me, org.id) ? (
        <Alert>
          <AlertDescription>Only form creators and admins can import forms.</AlertDescription>
        </Alert>
      ) : (
        <>
          {/* Kept mounted so "Start over" returns to what was typed. */}
          <div hidden={preview !== null} className="w-full max-w-3xl">
            <SourceStep orgId={org.id} onRead={setPreview} />
          </div>
          {preview && <ResultStep key={preview.id} preview={preview} orgId={org.id} orgSlug={org.slug} onRestart={() => setPreview(null)} />}
        </>
      )}
    </PageContainer>
  )
}
