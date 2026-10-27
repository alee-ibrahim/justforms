/**
 * The "Ask your submissions" panel's two homes (INSIGHTS-SCREENS 4.1): docked at the end of
 * the page under the form bar from 1024px (the page stays usable beside it, so "Show these
 * submissions" filters the list while the chat stays open), a full-height sheet below that.
 */
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'

import { AskPanel } from './ask-panel'

export default function AskDock({ docked, onClose }: { docked: boolean; onClose: () => void }) {
  if (docked)
    return (
      <aside
        aria-label="Ask your submissions"
        className="sticky top-(--studio-top) h-[calc(100dvh-var(--studio-top))] w-[26rem] shrink-0 border-s xl:w-[28rem] print:hidden"
      >
        <AskPanel
          onClose={onClose}
          title={<h2 className="truncate text-base font-medium">Ask your submissions</h2>}
        />
      </aside>
    )
  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" showCloseButton={false} className="h-dvh gap-0 p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-md">
        <SheetDescription className="sr-only">
          Ask questions about this form's submissions. Answers are counted from the submissions.
        </SheetDescription>
        <AskPanel
          onClose={onClose}
          onNavigate={onClose}
          title={<SheetTitle className="truncate text-base font-medium">Ask your submissions</SheetTitle>}
        />
      </SheetContent>
    </Sheet>
  )
}
