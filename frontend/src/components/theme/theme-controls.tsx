/**
 * The form theme editor (docs/ux/FORM-THEME-SCREENS.md 3.2-3.3), shared by Organisation settings
 * (defaults for every form) and a form's Settings (overrides). Each control shows the effective
 * value; a value the draft doesn't set is inherited, and "Reset" / "Use organisation setting"
 * removes the draft's value again. Composed from official shadcn components only.
 */
import { ImageIcon, InfoIcon, Undo2Icon, UploadIcon } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSeparator,
  FieldSet,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
  api,
  ApiError,
  type FormTheme,
  type ResolvedTheme,
  type ThemeAdjustment,
  type ThemeColors,
  type ThemeFont,
} from '@/lib/api'
import { useFontLinks, type ThemeBase } from '@/lib/theme'
import { toggleGroupOn } from '@/lib/toggle'
import { cn } from '@/lib/utils'

type Key = Exclude<keyof FormTheme, 'colors'>

/** JustForms' own light palette (DESIGN-SYSTEM 3.1), shown as placeholders. */
const PALETTE: Required<ThemeColors> = {
  primary: '#3B3FC1',
  background: '#F3F5F9',
  surface: '#FFFFFF',
  text: '#18203A',
  mutedText: '#5A6380',
  border: '#DCE0EA',
  error: '#C0362C',
}

const COLOR_ROWS: { key: keyof ThemeColors; label: string; hint: string }[] = [
  { key: 'primary', label: 'Primary', hint: 'Buttons, links, focus and progress.' },
  { key: 'background', label: 'Page background', hint: 'Behind the form.' },
  { key: 'surface', label: 'Sheet', hint: 'The form itself.' },
  { key: 'text', label: 'Text', hint: 'Questions and answers.' },
  { key: 'mutedText', label: 'Muted text', hint: 'Descriptions and help text.' },
  { key: 'border', label: 'Borders', hint: 'Dividers and edges. Input outlines are made darker when needed.' },
  { key: 'error', label: 'Errors', hint: 'Error messages and their markers.' },
]

const COLOR_NAMES: Record<keyof ThemeColors, string> = {
  primary: 'Primary',
  background: 'Page background',
  surface: 'Sheet',
  text: 'Text',
  mutedText: 'Muted text',
  border: 'Borders',
  error: 'Errors',
}

const HEX = /^#[0-9a-fA-F]{6}$/

const IMAGE_ERRORS: Record<string, string> = {
  bad_type: "That file isn't a PNG, JPEG or WebP image.",
  too_large: 'The image is larger than 2 MB.',
  too_large_pixels: 'The image is larger than 4096 pixels on a side.',
}

type Choice<V extends string> = { value: V; label: string }

const CHOICES = {
  textSize: [
    { value: 's', label: 'Small' },
    { value: 'm', label: 'Medium' },
    { value: 'l', label: 'Large' },
    { value: 'xl', label: 'Extra large' },
  ],
  headingScale: [
    { value: 'compact', label: 'Compact' },
    { value: 'standard', label: 'Standard' },
    { value: 'large', label: 'Large' },
  ],
  radius: [
    { value: 'none', label: 'Square' },
    { value: 'small', label: 'Small' },
    { value: 'medium', label: 'Medium' },
    { value: 'large', label: 'Large' },
  ],
  density: [
    { value: 'compact', label: 'Compact' },
    { value: 'comfortable', label: 'Comfortable' },
    { value: 'roomy', label: 'Roomy' },
  ],
  pageWidth: [
    { value: 'narrow', label: 'Narrow' },
    { value: 'standard', label: 'Standard' },
    { value: 'wide', label: 'Wide' },
  ],
  buttonStyle: [
    { value: 'filled', label: 'Filled' },
    { value: 'outline', label: 'Outline' },
  ],
  inputStyle: [
    { value: 'outlined', label: 'Outlined' },
    { value: 'filled', label: 'Filled' },
    { value: 'underlined', label: 'Underlined' },
  ],
  progressStyle: [
    { value: 'bar', label: 'Bar' },
    { value: 'steps', label: 'Steps text' },
    { value: 'none', label: 'Hidden' },
  ],
  logoPlacement: [
    { value: 'start', label: 'Start' },
    { value: 'center', label: 'Centre' },
    { value: 'end', label: 'End' },
    { value: 'hidden', label: 'Hidden' },
  ],
  logoSize: [
    { value: 's', label: 'Small' },
    { value: 'm', label: 'Medium' },
    { value: 'l', label: 'Large' },
  ],
} satisfies Partial<Record<Key, Choice<string>[]>>

export interface ThemeControlsProps {
  value: FormTheme
  onChange: (next: FormTheme) => void
  base: ThemeBase
  scope: 'organisation' | 'form'
  fonts: { latin: ThemeFont[]; thaana: ThemeFont[] }
  fontSource: string | null
  adjustments: ThemeAdjustment[]
  orgId: string
  disabled?: boolean
  /** The form's own logo row (form settings only). */
  logo?: ReactNode
}

/** http or https, no spaces, ≤ 500 characters (the API checks the same). */
const LINK = /^https?:\/\/[^\s<>"']+$/i

export function ThemeControls(props: ThemeControlsProps) {
  const { value, onChange, base, scope, fonts, disabled } = props
  useFontLinks([...fonts.latin, ...fonts.thaana].map((f) => f.cssUrl).filter((u): u is string => !!u))

  const set = <K extends Key>(key: K, v: FormTheme[K] | undefined) => {
    const next = { ...value }
    if (v === undefined) delete next[key]
    else next[key] = v
    onChange(next)
  }
  const setColor = (key: keyof ThemeColors, v: string | undefined) => {
    const colors = { ...value.colors }
    if (v === undefined) delete colors[key]
    else colors[key] = v
    onChange({ ...value, colors })
  }
  const effective = <K extends Key>(key: K) => (value[key] ?? base.resolved[key as keyof ResolvedTheme]) as NonNullable<FormTheme[K]>

  const row = (key: Key, label: string, control: ReactNode, description?: ReactNode) => (
    <OptionRow
      key={key}
      label={label}
      id={`theme-${key}`}
      set={value[key] !== undefined}
      scope={scope}
      disabled={disabled}
      onReset={() => set(key, undefined)}
      description={description}
    >
      {control}
    </OptionRow>
  )

  const toggles = <K extends keyof typeof CHOICES>(key: K, label: string, description?: string) =>
    row(
      key,
      label,
      <ToggleGroup
        type="single"
        variant="outline"
        id={`theme-${key}`}
        disabled={disabled}
        value={String(effective(key))}
        onValueChange={(v) => v && set(key, v as FormTheme[K])}
        className={cn("flex-wrap", toggleGroupOn)}
        aria-label={label}
      >
        {CHOICES[key].map((c) => (
          <ToggleGroupItem key={c.value} value={c.value} className="px-3">
            {c.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>,
      description,
    )

  return (
    <FieldGroup className="gap-6">
      <FieldSet>
        <FieldLegend>Colours</FieldLegend>
        <FieldDescription>
          Pick colours for light mode. Dark mode is generated from them, and every colour is checked so text stays
          readable.
        </FieldDescription>
        <FieldGroup className="gap-4">
          {COLOR_ROWS.map((c) => (
            <ColorRow
              key={c.key}
              id={`theme-color-${c.key}`}
              label={c.label}
              hint={c.hint}
              value={value.colors[c.key]}
              inherited={base.colors[c.key]}
              placeholder={base.colors[c.key] ?? PALETTE[c.key]}
              scope={scope}
              disabled={disabled}
              onChange={(v) => setColor(c.key, v)}
            />
          ))}
        </FieldGroup>
        {props.adjustments.length > 0 && (
          <Alert>
            <InfoIcon />
            <AlertTitle>Some colours were adjusted so text stays readable</AlertTitle>
            <AlertDescription>
              <ul className="flex flex-col gap-1">
                {props.adjustments.map((a) => (
                  <li key={a.color} className="flex flex-wrap items-center gap-2">
                    <Swatch color={a.chosen} />
                    <Swatch color={a.used} />
                    <span>
                      {COLOR_NAMES[a.color]} adjusted to <bdi dir="ltr" className="font-mono">{a.used}</bdi> (
                      {a.contrast.toFixed(1)}:1, needs {a.needed}:1).
                    </span>
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
      </FieldSet>

      <FieldSeparator />
      <FieldSet>
        <FieldLegend>Text</FieldLegend>
        <FieldGroup className="gap-4">
          {row(
            'latinFont',
            'Latin font',
            <FontSelect id="theme-latinFont" fonts={fonts.latin} value={effective('latinFont')} disabled={disabled} onChange={(v) => set('latinFont', v as FormTheme['latinFont'])} />,
          )}
          {row(
            'thaanaFont',
            'Thaana font',
            <FontSelect id="theme-thaanaFont" fonts={fonts.thaana} thaana value={effective('thaanaFont')} disabled={disabled} onChange={(v) => set('thaanaFont', v)} />,
            props.fontSource ? <>Fonts come from <bdi dir="ltr">{props.fontSource}</bdi>.</> : 'Fonts are served by this site.',
          )}
          {toggles('textSize', 'Text size')}
          {toggles('headingScale', 'Headings')}
        </FieldGroup>
      </FieldSet>

      <FieldSeparator />
      <FieldSet>
        <FieldLegend>Shape and spacing</FieldLegend>
        <FieldGroup className="gap-4">
          {toggles('radius', 'Corners')}
          {toggles('density', 'Spacing', 'Space between questions.')}
          {toggles('pageWidth', 'Page width', 'How wide the form is on larger screens.')}
        </FieldGroup>
      </FieldSet>

      <FieldSeparator />
      <FieldSet>
        <FieldLegend>Controls</FieldLegend>
        <FieldGroup className="gap-4">
          {toggles('buttonStyle', 'Buttons')}
          {row(
            'buttonFullWidth',
            'Full-width buttons on phones',
            <Switch
              id="theme-buttonFullWidth"
              disabled={disabled}
              checked={effective('buttonFullWidth')}
              onCheckedChange={(on) => set('buttonFullWidth', on)}
            />,
          )}
          {toggles('inputStyle', 'Inputs')}
          {toggles('progressStyle', 'Progress', 'On forms with more than one page.')}
        </FieldGroup>
      </FieldSet>

      <FieldSeparator />
      <FieldSet>
        <FieldLegend>Page</FieldLegend>
        <FieldGroup className="gap-4">
          {row(
            'colorScheme',
            'Colour mode for people filling it in',
            <RadioGroup
              id="theme-colorScheme"
              disabled={disabled}
              value={effective('colorScheme')}
              onValueChange={(v) => set('colorScheme', v as FormTheme['colorScheme'])}
              className="gap-2"
            >
              {(
                [
                  ['light', 'Light'],
                  ['dark', 'Dark'],
                  ['auto', 'Match their device'],
                ] as const
              ).map(([v, label]) => (
                <Field key={v} orientation="horizontal">
                  <RadioGroupItem value={v} id={`theme-scheme-${v}`} />
                  <FieldLabel htmlFor={`theme-scheme-${v}`} className="font-normal">
                    {label}
                  </FieldLabel>
                </Field>
              ))}
            </RadioGroup>,
          )}
          {props.logo}
          {toggles('logoSize', 'Logo size')}
          {toggles(
            'logoPlacement',
            'Logo position',
            scope === 'form' ? 'Where the logo sits above the title. Start is on the right in a Dhivehi form.' : 'Where the logo sits above the title of every form. Start is on the right in a Dhivehi form.',
          )}
          <LinkRow
            value={value.logoLink}
            inherited={base.resolved.logoLink ?? null}
            scope={scope}
            disabled={disabled}
            onChange={(v) => set('logoLink', v)}
          />
          <ImageRow
            label="Header image"
            hint="A wide image across the top of the form. PNG, JPEG or WebP, up to 2 MB."
            id="theme-headerImage"
            value={value.headerImage}
            inheritedUrl={base.resolved.headerImage}
            orgId={props.orgId}
            scope={scope}
            disabled={disabled}
            onChange={(v) => set('headerImage', v)}
          />
          <ImageRow
            label="Background image"
            hint="Behind the form on larger screens. Keep it quiet so the form stays readable."
            id="theme-backgroundImage"
            value={value.backgroundImage}
            inheritedUrl={base.resolved.backgroundImage}
            orgId={props.orgId}
            scope={scope}
            disabled={disabled}
            onChange={(v) => set('backgroundImage', v)}
          />
        </FieldGroup>
      </FieldSet>
    </FieldGroup>
  )
}

function OptionRow({
  label,
  id,
  set,
  scope,
  disabled,
  onReset,
  description,
  children,
}: {
  label: string
  id: string
  set: boolean
  scope: 'organisation' | 'form'
  disabled?: boolean
  onReset: () => void
  description?: ReactNode
  children: ReactNode
}) {
  return (
    <Field>
      <div className="flex flex-wrap items-center gap-2">
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
        {scope === 'form' && !set && <Badge variant="outline">Organisation</Badge>}
        {set && !disabled && (
          <Button type="button" variant="ghost" size="sm" className="ms-auto" onClick={onReset}>
            <Undo2Icon />
            {scope === 'form' ? 'Use organisation setting' : 'Reset'}
          </Button>
        )}
      </div>
      {children}
      {description && <FieldDescription>{description}</FieldDescription>}
    </Field>
  )
}

function LinkRow({
  value,
  inherited,
  scope,
  disabled,
  onChange,
}: {
  value: string | undefined
  inherited: string | null
  scope: 'organisation' | 'form'
  disabled?: boolean
  onChange: (v: string | undefined) => void
}) {
  const [text, setText] = useState(value ?? '')
  const [shownFor, setShownFor] = useState(value)
  if (shownFor !== value) {
    setShownFor(value)
    setText(value ?? '')
  }
  const invalid = text !== '' && (!LINK.test(text) || text.length > 500)
  return (
    <OptionRow
      label="Logo link"
      id="theme-logoLink"
      set={value !== undefined}
      scope={scope}
      disabled={disabled}
      onReset={() => onChange(undefined)}
      description="Opens in a new tab when someone taps the logo. Leave empty for no link."
    >
      <Input
        id="theme-logoLink"
        type="url"
        inputMode="url"
        dir="ltr"
        autoCapitalize="none"
        spellCheck={false}
        disabled={disabled}
        placeholder={inherited ?? 'https://example.org'}
        value={text}
        aria-invalid={invalid ? true : undefined}
        onChange={(e) => {
          const v = e.target.value.trim()
          setText(v)
          if (v === '') onChange(undefined)
          else if (LINK.test(v) && v.length <= 500) onChange(v)
        }}
      />
      {invalid && <FieldError>Enter a link starting with https:// or http://.</FieldError>}
    </OptionRow>
  )
}

function Swatch({ color }: { color: string }) {
  return <span aria-hidden className="inline-block size-4 rounded-sm border" style={{ background: color }} />
}

function ColorRow({
  id,
  label,
  hint,
  value,
  inherited,
  placeholder,
  scope,
  disabled,
  onChange,
}: {
  id: string
  label: string
  hint: string
  value: string | undefined
  inherited: string | undefined
  placeholder: string
  scope: 'organisation' | 'form'
  disabled?: boolean
  onChange: (v: string | undefined) => void
}) {
  const [text, setText] = useState(value ?? '')
  const [shownFor, setShownFor] = useState(value)
  if (shownFor !== value) {
    setShownFor(value)
    setText(value ?? '')
  }
  const invalid = text !== '' && !HEX.test(text)
  const shown = value ?? inherited ?? placeholder
  return (
    <Field orientation="responsive" data-invalid={invalid ? true : undefined}>
      <FieldContent>
        <div className="flex flex-wrap items-center gap-2">
          <FieldLabel htmlFor={id}>{label}</FieldLabel>
          {scope === 'form' && value === undefined && <Badge variant="outline">Organisation</Badge>}
        </div>
        <FieldDescription>{hint}</FieldDescription>
        {invalid && <FieldError>Enter a colour like #0F766E.</FieldError>}
      </FieldContent>
      <div className="flex items-center gap-2">
        <Input
          type="color"
          aria-label={`${label} colour picker`}
          className="h-9 w-11 shrink-0 cursor-pointer p-1"
          disabled={disabled}
          value={shown.toLowerCase()}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
        />
        <Input
          id={id}
          dir="ltr"
          className="w-28 font-mono"
          disabled={disabled}
          placeholder={(inherited ?? placeholder).toUpperCase()}
          value={text}
          aria-invalid={invalid ? true : undefined}
          onChange={(e) => {
            const v = e.target.value.trim()
            setText(v)
            if (v === '') onChange(undefined)
            else if (HEX.test(v)) onChange(v.toUpperCase())
          }}
        />
        {value !== undefined && !disabled && (
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(undefined)}>
            <Undo2Icon />
            {scope === 'form' ? 'Use organisation' : 'Reset'}
          </Button>
        )}
      </div>
    </Field>
  )
}

function FontSelect({
  id,
  fonts,
  value,
  thaana = false,
  disabled,
  onChange,
}: {
  id: string
  fonts: { id: string; name: string; family: string }[]
  value: string
  thaana?: boolean
  disabled?: boolean
  onChange: (v: string) => void
}) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger id={id} className="w-full sm:w-72">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {fonts.map((f) => (
          <SelectItem key={f.id} value={f.id}>
            <span style={{ fontFamily: thaana ? undefined : f.family }}>{f.name}</span>
            {thaana && (
              <span lang="dv" dir="rtl" className="text-muted-foreground" style={{ fontFamily: `${f.family}, 'Noto Sans Thaana'` }}>
                ހަކުރު
              </span>
            )}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function ImageRow({
  label,
  hint,
  id,
  value,
  inheritedUrl,
  orgId,
  scope,
  disabled,
  onChange,
}: {
  label: string
  hint: string
  id: string
  value: string | undefined
  inheritedUrl: string | null
  orgId: string
  scope: 'organisation' | 'form'
  disabled?: boolean
  onChange: (ref: string | undefined) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploaded, setUploaded] = useState<Record<string, string>>({})
  const url =
    value === 'none' ? null : value ? (uploaded[value] ?? `/api/v1/public/theme-images/${orgId}/${value}`) : inheritedUrl
  const upload = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      const img = await api.uploadThemeImage(orgId, file)
      setUploaded((u) => ({ ...u, [img.ref]: img.url }))
      onChange(img.ref)
    } catch (err) {
      const code = err instanceof ApiError && typeof err.detail === 'string' ? err.detail : ''
      setError(IMAGE_ERRORS[code] ?? "Couldn't upload the image. Try again.")
    } finally {
      setBusy(false)
    }
  }
  return (
    <Field data-invalid={error ? true : undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
        {scope === 'form' && value === undefined && <Badge variant="outline">Organisation</Badge>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex h-12 w-28 items-center justify-center overflow-hidden rounded-md border bg-muted">
          {url ? (
            <img src={url} alt="" className="h-full w-full object-cover" />
          ) : (
            <ImageIcon className="size-4 text-muted-foreground" aria-label="None" />
          )}
        </div>
        <input
          ref={input}
          id={id}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          disabled={disabled || busy}
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) void upload(file)
          }}
        />
        <Button type="button" variant="outline" disabled={disabled || busy} onClick={() => input.current?.click()}>
          {busy ? <Spinner /> : <UploadIcon />}
          {url ? 'Replace' : 'Upload'}
        </Button>
        {url && !disabled && (
          <Button type="button" variant="ghost" onClick={() => onChange(scope === 'form' && inheritedUrl ? 'none' : undefined)}>
            Remove
          </Button>
        )}
        {value !== undefined && scope === 'form' && !disabled && (
          <Button type="button" variant="ghost" onClick={() => onChange(undefined)}>
            <Undo2Icon />
            Use organisation setting
          </Button>
        )}
      </div>
      <FieldDescription>{hint}</FieldDescription>
      {error && <FieldError>{error}</FieldError>}
    </Field>
  )
}
