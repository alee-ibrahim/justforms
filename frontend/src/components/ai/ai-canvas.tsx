/**
 * The canvas while an AI suggestion is pending (PHASE-5-SCREENS 4): a banner with the
 * Suggestion / Current form toggle, and the suggested form drawn by the normal canvas from a
 * read-only builder store, with added and changed questions washed with the marker.
 */
import { InfoIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { BuilderDnd } from '@/components/builder/dnd'
import { BuilderContext } from '@/components/builder/store'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { toggleGroupOn } from '@/lib/toggle'

import { type AiController, type AiState, useAi } from './controller'

export function SuggestionBanner({ ai, showing }: { ai: AiController; showing: AiState['showing'] }) {
  return (
    <Alert className="mx-auto w-full max-w-[40rem] py-2" onClick={(e) => e.stopPropagation()}>
      <InfoIcon />
      <AlertDescription className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="min-w-0 flex-1 basis-56">
          {showing === 'suggestion'
            ? "Showing the AI's suggestion. Changed questions are marked. Apply or discard it to keep editing."
            : "Showing your current form. Apply or discard the AI's suggestion to keep editing."}
        </span>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={showing}
          onValueChange={(v) => v && ai.setShowing(v as AiState['showing'])}
          aria-label="Show"
          className={toggleGroupOn}
        >
          <ToggleGroupItem value="suggestion">Suggestion</ToggleGroupItem>
          <ToggleGroupItem value="current">Current form</ToggleGroupItem>
        </ToggleGroup>
      </AlertDescription>
    </Alert>
  )
}

/** Renders ``children`` (page strip + canvas) against the suggestion instead of the draft. */
export function SuggestionScope({ preview, children }: { preview: NonNullable<AiState['preview']>; children: ReactNode }) {
  return (
    <BuilderContext.Provider value={preview}>
      <BuilderDnd>
        <div data-ai-preview className="contents">
          {children}
        </div>
      </BuilderDnd>
    </BuilderContext.Provider>
  )
}

/** Phones: sticky actions under the canvas while the suggestion is shown. */
export function SuggestionBar({ ai, onBack }: { ai: AiController; onBack: () => void }) {
  const busy = useAi(ai, (s) => s.busy)
  return (
    <div className="sticky bottom-0 z-10 flex flex-wrap justify-end gap-2 border-t bg-card px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
      <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void ai.discard()}>
        Discard
      </Button>
      <Button size="sm" variant="outline" onClick={onBack}>
        Back to chat
      </Button>
      <Button size="sm" disabled={!!busy} onClick={() => void ai.apply()}>
        {busy === 'applying' && <Spinner data-icon="inline-start" />}
        Apply changes
      </Button>
    </div>
  )
}
