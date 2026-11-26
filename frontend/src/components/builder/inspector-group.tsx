import type { ComponentProps } from 'react'

import { AccordionContent } from '@/components/ui/accordion'
import { cn } from '@/lib/utils'

/**
 * Body of an inspector group. Groups grow while open (a new logic rule, an added option), but
 * the generated AccordionContent pins its body to the height measured when the group opened, so
 * anything added later was clipped until the group was closed and reopened. Let the body follow
 * its content; the open/close animation still runs on the outer panel.
 */
export function GroupContent({ className, ...props }: ComponentProps<typeof AccordionContent>) {
  return <AccordionContent className={cn('h-auto', className)} {...props} />
}
