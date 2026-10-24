/** Live preview of a form theme (docs/ux/FORM-THEME-SCREENS.md 3.4): the real renderer with a
 * sample form, themed by the draft values' tokens on this container only. */
import { useQuery } from '@tanstack/react-query'
import { MonitorIcon, SmartphoneIcon } from 'lucide-react'
import { useState } from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { ThemeReport } from '@/lib/api'
import { brandQuery, meQuery } from '@/lib/queries'
import { themeScope, useFontLinks, type ThemeMode } from '@/lib/theme'
import { toggleGroupOn } from '@/lib/toggle'
import { cn } from '@/lib/utils'
import { FormRenderer } from '@/renderer/form-view'

import { SAMPLE_DV, SAMPLE_EN } from './samples'

export function ThemePreview({
  report,
  language: initialLanguage = 'en',
  className,
}: {
  report: ThemeReport | undefined
  language?: 'en' | 'dv'
  className?: string
}) {
  const [mode, setMode] = useState<ThemeMode>('light')
  const [device, setDevice] = useState<'phone' | 'desktop'>('phone')
  const [language, setLanguage] = useState<'en' | 'dv'>(initialLanguage)
  const me = useQuery(meQuery)
  const brand = useQuery(brandQuery(me.data?.orgs[0]?.slug ?? '_'))
  useFontLinks(report?.fonts)
  const scope = themeScope(report, mode)

  return (
    <Card className={cn('rounded-md border shadow-none ring-0', className)}>
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle>Preview</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <Tabs value={mode} onValueChange={(v) => setMode(v as ThemeMode)}>
            <TabsList aria-label="Colour mode">
              <TabsTrigger value="light">Light</TabsTrigger>
              <TabsTrigger value="dark">Dark</TabsTrigger>
            </TabsList>
          </Tabs>
          <ToggleGroup
            type="single"
            variant="outline"
            value={device}
            onValueChange={(v) => v && setDevice(v as 'phone' | 'desktop')}
            aria-label="Device"
            className={toggleGroupOn}
          >
            <ToggleGroupItem value="phone" className="px-3">
              <SmartphoneIcon />
              Phone
            </ToggleGroupItem>
            <ToggleGroupItem value="desktop" className="px-3">
              <MonitorIcon />
              Desktop
            </ToggleGroupItem>
          </ToggleGroup>
          <ToggleGroup
            type="single"
            variant="outline"
            value={language}
            onValueChange={(v) => v && setLanguage(v as 'en' | 'dv')}
            aria-label="Sample language"
            className={toggleGroupOn}
          >
            <ToggleGroupItem value="en" className="px-3">
              English
            </ToggleGroupItem>
            <ToggleGroupItem value="dv" className="px-3">
              Dhivehi
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      </CardHeader>
      <CardContent>
        <p className="sr-only">Preview of a sample form with these settings.</p>
        <div
          aria-hidden
          inert
          data-testid="theme-preview"
          {...scope}
          data-df-frame="page"
          className={cn(
            scope.className,
            'overflow-hidden rounded-md border bg-background text-foreground',
            device === 'desktop' ? 'px-4 py-6' : 'py-0',
          )}
        >
          <div className={cn('mx-auto', device === 'phone' && 'max-w-[22.5rem] border-x')}>
            <FormRenderer
              key={language}
              form={language === 'dv' ? SAMPLE_DV : SAMPLE_EN}
              mode="preview"
              frame="bare"
              brand={brand.data}
              orgName={brand.data?.name}
              theme={report?.options}
              uploader={() => Promise.reject(new Error('preview'))}
              onSubmit={async () => ({ ok: true, reference: 'Preview' })}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
