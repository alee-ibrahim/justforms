import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** Settings-width page on the desk (lists, share, settings). The builder is full-bleed. */
export function PageContainer({
  children,
  className,
  width = 'wide',
}: {
  children: ReactNode
  className?: string
  width?: 'wide' | 'narrow'
}) {
  return (
    <main
      className={cn(
        'mx-auto flex w-full flex-col gap-6 px-4 py-8 sm:px-6',
        width === 'wide' ? 'max-w-6xl' : 'max-w-3xl',
        className,
      )}
    >
      {children}
    </main>
  )
}
