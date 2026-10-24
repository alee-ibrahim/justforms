/** "Suggested changes" (PHASE-5-SCREENS 3.3): the change list, things to check, Apply / Discard. */
import {
  FileIcon,
  LanguagesIcon,
  MinusIcon,
  MoveIcon,
  PencilIcon,
  PlusIcon,
  SettingsIcon,
  SmartphoneIcon,
  TriangleAlertIcon,
} from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Item, ItemActions, ItemContent, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Spinner } from '@/components/ui/spinner'

import type { Change, ChangeKind, Proposal } from './api'
import { type AiController, useAi } from './controller'
import { textLang } from './files'

const BADGE: Record<ChangeKind, { word: string; icon: typeof PlusIcon; variant: 'secondary' | 'outline' }> = {
  added: { word: 'Added', icon: PlusIcon, variant: 'secondary' },
  changed: { word: 'Changed', icon: PencilIcon, variant: 'outline' },
  removed: { word: 'Removed', icon: MinusIcon, variant: 'outline' },
  moved: { word: 'Moved', icon: MoveIcon, variant: 'outline' },
}

function ChangeBadge({ change }: { change: ChangeKind }) {
  const { word, icon: Icon, variant } = BADGE[change]
  return (
    <Badge variant={variant} className="shrink-0">
      <Icon className={change === 'removed' ? 'text-destructive' : undefined} />
      {word}
    </Badge>
  )
}

function ChangeLabel({ change, language }: { change: Change; language: string }) {
  if (change.kind === 'settings') return <>Form title and settings</>
  const label = change.label.trim()
  return (
    <span className="min-w-0 truncate">
      {change.kind === 'page' && <span className="text-muted-foreground">Page: </span>}
      {label ? (
        <bdi dir="auto" lang={textLang(label, language)}>
          {label}
        </bdi>
      ) : (
        <span className="text-muted-foreground">Untitled</span>
      )}
    </span>
  )
}

export function SuggestionCard({
  ai,
  proposal,
  onPreview,
}: {
  ai: AiController
  proposal: Proposal
  /** Phones: close the drawer and show the suggestion on the canvas. */
  onPreview?: () => void
}) {
  const busy = useAi(ai, (s) => s.busy)
  const stale = useAi(ai, (s) => s.stale)
  const { changes, flags, language } = proposal
  return (
    <section aria-label="Suggested changes" className="flex flex-col gap-3 rounded-md border bg-card p-3">
      <h3 className="text-sm font-medium">Suggested changes</h3>
      {changes.length === 0 ? (
        <p className="text-sm text-muted-foreground">No changes to the form.</p>
      ) : (
        <ItemGroup className="-mx-3 gap-0">
          {changes.map((c, i) => {
            const clickable = c.change !== 'removed' && (c.kind === 'element' || c.kind === 'page')
            const body = (
              <>
                {c.kind !== 'element' && (
                  <ItemMedia>{c.kind === 'page' ? <FileIcon className="size-4" /> : <SettingsIcon className="size-4" />}</ItemMedia>
                )}
                <ItemContent className="min-w-0">
                  <ItemTitle className="w-full min-w-0 font-normal">
                    <ChangeLabel change={c} language={language} />
                  </ItemTitle>
                </ItemContent>
                <ItemActions>
                  <ChangeBadge change={c.change} />
                </ItemActions>
              </>
            )
            return clickable ? (
              <Item key={`${c.id}-${i}`} size="sm" asChild className="py-1.5 hover:bg-muted/60">
                <button type="button" onClick={() => ai.reveal(c.kind === 'element' ? c.id : null, c.pageId)}>
                  {body}
                </button>
              </Item>
            ) : (
              <Item key={`${c.id}-${i}`} size="sm" className="py-1.5">
                {body}
              </Item>
            )
          })}
        </ItemGroup>
      )}
      {flags.length > 0 && (
        <Alert>
          <TriangleAlertIcon />
          <AlertTitle>Check these</AlertTitle>
          <AlertDescription>
            <ul className="list-disc ps-4">
              {flags.map((f) => (
                <li key={f.targetId}>
                  <bdi dir="auto" lang={textLang(f.label ?? '', language)}>
                    {f.label ?? f.targetId}
                  </bdi>
                  : {f.note}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {language === 'dv' && (
        <Alert>
          <LanguagesIcon />
          <AlertDescription>
            Check the Dhivehi wording before you publish. The AI's Dhivehi is a draft.
          </AlertDescription>
        </Alert>
      )}
      {stale && (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertDescription className="flex flex-col items-start gap-2">
            The form changed while the AI was working, in the same places. Ask again to get a fresh suggestion.
            <Button size="sm" variant="outline" onClick={() => void ai.askAgain()}>
              Ask again
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={!!busy} onClick={() => void ai.apply()}>
          {busy === 'applying' && <Spinner data-icon="inline-start" />}
          {busy === 'applying' ? 'Applying…' : 'Apply changes'}
        </Button>
        {onPreview && (
          <Button size="sm" variant="outline" disabled={!!busy} onClick={onPreview}>
            <SmartphoneIcon />
            Preview on the form
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void ai.discard()}>
          Discard
        </Button>
      </div>
    </section>
  )
}
