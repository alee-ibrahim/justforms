/** Live preview of the branding draft (docs/ux/BRANDING-SCREENS.md section 3): a miniature
 * studio header and public form sheet, themed by CSS variables on the preview only. */
import { MonitorIcon, SmartphoneIcon } from 'lucide-react'
import { useState, type CSSProperties } from 'react'

import { BrandFooter, BrandLogo } from '@/components/brand/brand-parts'
import { JustFormsLogo } from '@/components/brand/logo'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { PaletteReport } from '@/lib/api'
import type { Brand } from '@/lib/branding'
import { cn } from '@/lib/utils'

export function BrandPreview({ brand, palette }: { brand: Brand; palette: PaletteReport | null }) {
  const [mode, setMode] = useState<'light' | 'dark'>('light')
  const [device, setDevice] = useState<'phone' | 'desktop'>('phone')
  const tokens = palette ? (mode === 'dark' ? palette.darkTokens : palette.lightTokens) : undefined

  return (
    <Card className="rounded-md border shadow-none ring-0 lg:sticky lg:top-16">
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle>Preview</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <Tabs value={mode} onValueChange={(v) => setMode(v as 'light' | 'dark')}>
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
        </div>
      </CardHeader>
      <CardContent>
        <p className="sr-only">Preview of your studio and forms with these settings.</p>
        <div
          aria-hidden
          inert
          data-testid="brand-preview"
          className={cn('overflow-hidden rounded-md border text-foreground', mode === 'dark' && 'dark')}
          style={tokens as CSSProperties | undefined}
        >
          <div className="bg-background">
            <div className="flex h-11 items-center gap-2 border-b bg-card px-3">
              {brand.logoUrl ? (
                <BrandLogo brand={brand} className="h-6 max-w-32" />
              ) : brand.custom && brand.name ? (
                <span className="flex items-center gap-2 text-sm font-semibold">
                  {brand.iconUrl && <img src={brand.iconUrl} alt="" className="size-5 rounded-sm" />}
                  <bdi dir="auto" className="max-w-40 truncate">
                    {brand.name}
                  </bdi>
                </span>
              ) : (
                <JustFormsLogo />
              )}
              <span className="ms-auto text-sm text-muted-foreground">Forms</span>
            </div>
            <div className={cn('mx-auto py-4', device === 'phone' ? 'max-w-[22.5rem]' : 'px-4')}>
              <div className="flex flex-col gap-4 bg-card p-5 sm:rounded-md sm:border">
                {brand.logoUrl ? (
                  <BrandLogo brand={brand} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    <bdi dir="auto">{brand.name}</bdi>
                  </p>
                )}
                <p className="text-xl font-bold tracking-tight">Application form</p>
                <p className="text-sm text-muted-foreground">
                  It takes about 5 minutes. <span className="text-primary underline underline-offset-4">Read the guidance</span>
                </p>
                <div className="flex flex-col gap-2">
                  <Label>Full name</Label>
                  <Input tabIndex={-1} readOnly value="" className="h-11" />
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
                  <div className="h-full w-1/2 bg-primary" />
                </div>
                <Button tabIndex={-1} className="h-11 w-full sm:w-auto">
                  Next
                </Button>
              </div>
              <BrandFooter brand={brand} madeWith="Made with JustForms" />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
