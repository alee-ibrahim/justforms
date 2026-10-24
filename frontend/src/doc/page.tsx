import type { ReactNode } from 'react'

import { BrandFooter, BrandLogo } from '@/components/brand/brand-parts'
import { Skeleton } from '@/components/ui/skeleton'
import type { Brand } from '@/lib/branding'
import { useDelayed } from '@/lib/use-delayed'
import { cn } from '@/lib/utils'
import { themeAttrs } from '@/renderer/theme'

const SIZE = { s: 'h-6 max-w-32', m: 'h-8 max-w-48', l: 'h-14 max-w-80' } as const

/** The form's logo (or the organisation's) at the form theme's size, position and link. */
function PageLogo({ brand }: { brand: Brand }) {
  const t = brand.theme
  const logo = <BrandLogo brand={brand} className={SIZE[t?.logoSize ?? 'm']} />
  return (
    <div className={cn('flex', t?.logoPlacement === 'center' && 'justify-center', t?.logoPlacement === 'end' && 'justify-end')}>
      {t?.logoLink ? (
        <a
          href={t.logoLink}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`${brand.name}, opens in a new tab`}
          className="inline-flex min-h-11 items-center rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {logo}
        </a>
      ) : (
        logo
      )}
    </div>
  )
}

/**
 * The sheet on the desk, like the public form: full-bleed on phones, 40rem on wider screens.
 * English and left to right for every form (system text); blocks of form content inside set
 * their own `lang`/`dir`.
 */
export function Page({ children, brand }: { children?: ReactNode; brand?: Brand | null }) {
  const loading = children === undefined
  const show = useDelayed(loading)
  return (
    <div className="min-h-svh bg-background md:px-6 md:py-12" {...themeAttrs(brand?.theme)} data-df-frame="page">
      <main
        className="mx-auto flex max-w-[var(--df-page-width,40rem)] flex-col gap-6 bg-card p-5 max-md:min-h-svh md:rounded-md md:border md:p-10"
      >
        {brand?.logoUrl && brand.theme?.logoPlacement !== 'hidden' && <PageLogo brand={brand} />}
        {loading ? show && <Skeleton className="h-40 w-full" /> : children}
      </main>
      {!loading && <BrandFooter brand={brand} madeWith="Made with JustForms" />}
    </div>
  )
}
