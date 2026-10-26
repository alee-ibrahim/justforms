/**
 * Review changes (docs/ux/REVIEW-CHANGES-SCREENS.md): what publishing would change, grouped by
 * page (added green, removed red, changed before/after), with Publish and Discard changes.
 * The list itself (`ChangeList`) is also shown, compact, in the Publish dialog.
 */
import { ArrowRightIcon, MinusIcon, PlusIcon, Undo2Icon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import {
  ApiError,
  type DiffPiece,
  type DiffStatus,
  type DraftChanges,
  type ElementChange,
  type FormSummary,
  type PageChange,
  type PropertyChange,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { contentProps, type FormLanguage } from '@/schema/language'

import { useBuilder, useStore } from './store'
import { useDraftChanges } from './use-draft-changes'

/** Texts longer than this start clamped to three lines with "Show all". */
const LONG = 140

const STATUS: Record<DiffStatus, { label: string; badge: string; edge: string }> = {
  added: { label: 'Added', badge: 'border-added/40 text-added', edge: 'border-s-added' },
  removed: { label: 'Removed', badge: 'border-destructive/40 text-destructive', edge: 'border-s-destructive' },
  changed: { label: 'Changed', badge: 'border-primary/40 text-primary', edge: 'border-s-primary' },
  moved: { label: 'Moved', badge: 'border-border text-muted-foreground', edge: 'border-s-border' },
}

function StatusBadge({ status }: { status: DiffStatus }) {
  return (
    <Badge variant="outline" className={cn('shrink-0', STATUS[status].badge)}>
      {STATUS[status].label}
    </Badge>
  )
}

/** A change's text: English words plus form-content pieces in the form's direction. */
function Pieces({ pieces, lang }: { pieces: DiffPiece[]; lang: FormLanguage }) {
  return (
    <>
      {pieces.map((p, i) =>
        p.content ? (
          <bdi key={i} {...contentProps(lang)}>
            {p.text}
          </bdi>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  )
}

/** One before/after value, clamped when long. Pure form content takes the form's direction. */
function Value({ pieces, lang, tone }: { pieces: DiffPiece[]; lang: FormLanguage; tone: 'before' | 'after' }) {
  const [open, setOpen] = useState(false)
  const long = pieces.reduce((n, p) => n + p.text.length, 0) > LONG
  const onlyContent = pieces.length === 1 && pieces[0].content
  const Icon = tone === 'before' ? MinusIcon : PlusIcon
  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-md px-2 py-1.5 text-sm',
        tone === 'before' ? 'bg-destructive/8' : 'bg-added/10',
      )}
    >
      <Icon
        className={cn('mt-0.5 size-4 shrink-0', tone === 'before' ? 'text-destructive' : 'text-added')}
        aria-hidden
      />
      <span className="sr-only">{tone === 'before' ? 'Before:' : 'After:'}</span>
      <div className="flex min-w-0 flex-1 flex-col items-start gap-0.5">
        <p
          className={cn('w-full text-start break-words whitespace-pre-line', long && !open && 'line-clamp-3')}
          {...(onlyContent ? contentProps(lang) : {})}
        >
          <Pieces pieces={pieces} lang={lang} />
        </p>
        {long && (
          <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setOpen(!open)}>
            {open ? 'Show less' : 'Show all'}
          </Button>
        )}
      </div>
    </div>
  )
}

function OptionsDetail({ change, lang }: { change: PropertyChange; lang: FormLanguage }) {
  const o = change.options!
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {o.added.map((x) => (
        <li key={`a-${x.value}`} className="flex items-start gap-2 rounded-md bg-added/10 px-2 py-1">
          <PlusIcon className="mt-0.5 size-4 shrink-0 text-added" aria-hidden />
          <span className="sr-only">Added option:</span>
          <span className="min-w-0 flex-1 text-start break-words" {...contentProps(lang)}>
            {x.label}
          </span>
        </li>
      ))}
      {o.removed.map((x) => (
        <li key={`r-${x.value}`} className="flex items-start gap-2 rounded-md bg-destructive/8 px-2 py-1">
          <MinusIcon className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
          <span className="sr-only">Removed option:</span>
          <span className="min-w-0 flex-1 text-start break-words" {...contentProps(lang)}>
            {x.label}
          </span>
        </li>
      ))}
      {o.renamed.map((x) => (
        <li key={`n-${x.value}`} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 px-2 py-1">
          <span className="sr-only">Renamed option:</span>
          <bdi {...contentProps(lang)} className="text-muted-foreground line-through">
            {x.before}
          </bdi>
          <ArrowRightIcon className="size-3.5 shrink-0 text-muted-foreground rtl:rotate-180" aria-label="to" />
          <bdi {...contentProps(lang)}>{x.after}</bdi>
        </li>
      ))}
      {o.reordered && <li className="px-2 py-1 text-muted-foreground">Options reordered</li>}
    </ul>
  )
}

/** Short English values (On/Off, numbers, widths) read best on one line: before → after. */
function isShort(change: PropertyChange): boolean {
  const all = [...(change.before ?? []), ...(change.after ?? [])]
  return all.every((p) => !p.content) && all.reduce((n, p) => n + p.text.length, 0) <= 40
}

function InlineValues({ change }: { change: PropertyChange }) {
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-sm">
      {change.before && (
        <span className="rounded-md bg-destructive/8 px-1.5 py-0.5 text-destructive line-through decoration-destructive/50">
          <span className="sr-only">Before: </span>
          {change.before.map((p) => p.text).join('')}
        </span>
      )}
      {change.before && change.after && (
        <ArrowRightIcon className="size-3.5 shrink-0 text-muted-foreground rtl:rotate-180" aria-hidden />
      )}
      {change.after && (
        <span className="rounded-md bg-added/10 px-1.5 py-0.5 text-added">
          <span className="sr-only">After: </span>
          {change.after.map((p) => p.text).join('')}
        </span>
      )}
    </p>
  )
}

function PropertyRow({ change, lang }: { change: PropertyChange; lang: FormLanguage }) {
  return (
    <li className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{change.name}</span>
      {change.kind === 'options' ? (
        <OptionsDetail change={change} lang={lang} />
      ) : isShort(change) ? (
        <InlineValues change={change} />
      ) : (
        <>
          {change.before && <Value pieces={change.before} lang={lang} tone="before" />}
          {change.after && <Value pieces={change.after} lang={lang} tone="after" />}
        </>
      )}
    </li>
  )
}

function ElementRow({ item, lang, compact }: { item: ElementChange; lang: FormLanguage; compact: boolean }) {
  const label = item.label.trim()
  return (
    <li className={cn('flex flex-col gap-2 rounded-md border border-s-4 bg-card p-3', STATUS[item.status].edge)}>
      <div className="flex items-start gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {label ? (
            <span
              className={cn(
                'text-start text-sm font-medium break-words',
                item.status === 'removed' && 'text-muted-foreground',
                compact && 'line-clamp-2',
              )}
              {...contentProps(lang)}
            >
              {label.length > LONG * 2 ? `${label.slice(0, LONG * 2)}…` : label}
            </span>
          ) : (
            <span className="text-sm font-medium">{item.typeName}</span>
          )}
          <span className="text-xs text-muted-foreground">
            {label ? item.typeName : 'No text'}
            {item.within.length > 0 && (
              <>
                {' in '}
                {item.within.map((w, i) => (
                  <span key={i}>
                    {i > 0 && ', '}
                    <bdi {...contentProps(lang)}>{w}</bdi>
                  </span>
                ))}
              </>
            )}
          </span>
        </div>
        <StatusBadge status={item.status} />
      </div>
      {compact ? (
        item.status !== 'added' && item.status !== 'removed' && <p className="text-xs text-muted-foreground">{item.summary}</p>
      ) : (
        <>
          {item.changes.length > 0 && (
            <ul className="flex flex-col gap-3">
              {item.changes.map((c) => (
                <PropertyRow key={c.property} change={c} lang={lang} />
              ))}
            </ul>
          )}
          {item.moveSummary && (
            <p className="text-xs text-muted-foreground">
              {item.movedFrom ? (
                <>
                  Moved from <Pieces pieces={item.movedFrom} lang={lang} />
                </>
              ) : (
                item.moveSummary
              )}
            </p>
          )}
        </>
      )}
    </li>
  )
}

function PageGroup({ page, lang, compact }: { page: PageChange; lang: FormLanguage; compact: boolean }) {
  const title = page.title.trim()
  return (
    <section className="flex flex-col gap-2" aria-label={`Page ${page.number}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 text-sm font-medium">
          Page {page.number}
          {title && title !== `Page ${page.number}` && (
            <span className="text-muted-foreground">
              ,{' '}
              <bdi {...contentProps(lang)}>{title}</bdi>
            </span>
          )}
        </h3>
        {page.status && <StatusBadge status={page.status} />}
        {page.movedFrom !== null && <span className="text-xs text-muted-foreground">was page {page.movedFrom}</span>}
      </div>
      {!compact && page.changes.length > 0 && (
        <ul className="flex flex-col gap-3 rounded-md border border-s-4 border-s-primary bg-card p-3">
          {page.changes.map((c) => (
            <PropertyRow key={c.property} change={c} lang={lang} />
          ))}
        </ul>
      )}
      {page.elements.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {page.elements.map((e) => (
            <ElementRow key={e.id} item={e} lang={lang} compact={compact} />
          ))}
        </ul>
      ) : (
        page.status === 'added' && <p className="text-xs text-muted-foreground">An empty page.</p>
      )}
    </section>
  )
}

/** Every change, grouped: form settings first, then pages in order. */
export function ChangeList({ changes, compact = false }: { changes: DraftChanges; compact?: boolean }) {
  const lang = changes.language
  return (
    <div className="flex flex-col gap-6">
      {changes.settings.length > 0 && (
        <section className="flex flex-col gap-2" aria-label="Form settings">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium">Form settings</h3>
            <StatusBadge status="changed" />
          </div>
          {compact ? (
            <p className="text-xs text-muted-foreground">{changes.settings.map((c) => c.summary).join(', ')}</p>
          ) : (
            <ul className="flex flex-col gap-3 rounded-md border border-s-4 border-s-primary bg-card p-3">
              {changes.settings.map((c) => (
                <PropertyRow key={c.property} change={c} lang={lang} />
              ))}
            </ul>
          )}
        </section>
      )}
      {changes.pages.map((p) => (
        <PageGroup key={p.pageId} page={p} lang={lang} compact={compact} />
      ))}
    </div>
  )
}

export function ChangesSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading changes">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-16 w-full" />
    </div>
  )
}

/** Discard changes… with its confirmation. */
function DiscardButton({ form, changes, onDone }: { form: FormSummary; changes?: DraftChanges; onDone: () => void }) {
  const store = useStore()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const discard = async () => {
    setBusy(true)
    try {
      await store.discard()
      setOpen(false)
      onDone()
      toast.success(`Changes discarded. The draft matches version ${form.currentVersion}.`, {
        action: { label: 'Undo', onClick: () => void store.undo() },
      })
    } catch (err) {
      const conflict = err instanceof ApiError && err.detail === 'revision_conflict'
      toast.error(conflict ? 'Someone else changed the form. Reload it and try again.' : "Couldn't discard the changes.")
    } finally {
      setBusy(false)
    }
  }
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button variant="destructive" disabled={!changes?.hasChanges}>
          <Undo2Icon />
          Discard changes…
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Discard unpublished changes?</AlertDialogTitle>
          <AlertDialogDescription>
            The draft goes back to version {form.currentVersion}, the live version
            {changes ? ` (${changes.summary.charAt(0).toLowerCase()}${changes.summary.slice(1)} will be undone)` : ''}. You
            can bring the changes back with Undo.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={busy}
            onClick={(e) => {
              e.preventDefault()
              void discard()
            }}
          >
            {busy && <Spinner />}
            Discard changes
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function ReviewChangesSheet({ form, onPublish }: { form: FormSummary; onPublish: () => void }) {
  const store = useStore()
  const open = useBuilder((s) => s.reviewing)
  const query = useDraftChanges(form, open)
  const changes = query.data
  const close = () => store.setReviewing(false)
  return (
    <Sheet open={open} onOpenChange={(o) => !o && close()}>
      <SheetContent side="right" className="w-full gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl">
        <SheetHeader className="border-b pe-14">
          <SheetTitle>Review changes</SheetTitle>
          <SheetDescription>
            {changes
              ? changes.hasChanges
                ? `${changes.summary} since version ${changes.baseVersion}, the live version.`
                : `The draft matches version ${changes.baseVersion}, the live version.`
              : `Changes in the draft since version ${form.currentVersion}, the live version.`}
          </SheetDescription>
        </SheetHeader>
        <ScrollArea className="min-h-0 flex-1">
          <div className="p-4 pb-6">
            {query.isError ? (
              <Alert variant="destructive">
                <AlertTitle>Couldn't load the changes</AlertTitle>
                <AlertDescription>
                  <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
                    Try again
                  </Button>
                </AlertDescription>
              </Alert>
            ) : !changes ? (
              <ChangesSkeleton />
            ) : changes.hasChanges ? (
              <ChangeList changes={changes} />
            ) : (
              <Empty>
                <EmptyHeader>
                  <EmptyTitle>No unpublished changes</EmptyTitle>
                  <EmptyDescription>Everything in the draft is live.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            )}
          </div>
        </ScrollArea>
        <SheetFooter className="border-t sm:flex-row sm:justify-end">
          <DiscardButton form={form} changes={changes} onDone={close} />
          <Button
            disabled={!changes?.hasChanges}
            onClick={() => {
              close()
              onPublish()
            }}
          >
            Publish
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
