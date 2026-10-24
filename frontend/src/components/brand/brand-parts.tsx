import { JustFormsMark } from '@/components/brand/mark'
import type { Brand } from '@/lib/branding'
import { cn } from '@/lib/utils'

/**
 * An organisation's logo: the light file, swapped for the dark one in dark mode when there is
 * one. `null` without a logo, so callers fall back to the name or JustForms' wordmark. Kept
 * small: it ships in the public form bundle.
 */
export function BrandLogo({ brand, className }: { brand: Brand | null | undefined; className?: string }) {
  if (!brand?.logoUrl) return null
  const img = 'block h-8 w-auto max-w-48 object-contain'
  return (
    <>
      <img src={brand.logoUrl} alt={brand.name} className={cn(img, brand.logoDarkUrl && 'dark:hidden', className)} />
      {brand.logoDarkUrl && (
        <img src={brand.logoDarkUrl} alt={brand.name} className={cn(img, 'hidden dark:block', className)} />
      )}
    </>
  )
}

/** Under the sheet: the organisation's support link and "Powered by JustForms" (or JustForms' own
 * "Made with JustForms" when nothing is branded). English and left to right on every form. */
export function BrandFooter({ brand, madeWith }: { brand: Brand | null | undefined; madeWith: string }) {
  const powered = brand ? brand.poweredBy : true
  if (!powered && !brand?.supportUrl) return null
  return (
    <footer
      className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1 py-6 text-xs text-muted-foreground"
      lang="en"
      dir="ltr"
    >
      {brand?.supportUrl && (
        <a
          href={brand.supportUrl}
          className="inline-flex min-h-11 items-center underline underline-offset-4 hover:text-foreground"
          rel="noopener noreferrer"
          target="_blank"
        >
          Get help
        </a>
      )}
      {powered && (
        <span className="inline-flex items-center gap-1.5">
          <JustFormsMark className="size-3" />
          {brand?.custom ? 'Powered by JustForms' : madeWith}
        </span>
      )}
    </footer>
  )
}
