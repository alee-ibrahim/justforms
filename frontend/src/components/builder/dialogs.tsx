/** Builder dialogs: delete confirmations and the revision conflict (PHASE-2-SCREENS 2.3, 2.6). */
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
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { formLanguage } from '@/schema/language'

import { deleteElement, quoted } from './actions'
import { blockLabel } from './block-types'
import { useBuilder, useStore } from './store'
import { findElement, removePage, rulesReading, subtreeIds } from './tree'

function RuleList({ ids }: { ids: Set<string> }) {
  const form = useBuilder((s) => s.schema)
  const lang = formLanguage(form)
  const rules = rulesReading(form, ids)
  if (!rules.length) return null
  return (
    <span className="flex flex-col gap-1">
      <span>
        {rules.length === 1 ? '1 rule uses' : `${rules.length} rules use`} these questions. Those rules will be removed.
      </span>
      <span className="flex flex-col">
        {rules.map((r) => {
          const pageIndex = form.pages.findIndex((p) => p.id === r.ownerId)
          const el = findElement(form, r.ownerId)?.el
          const what = r.kind === 'next' ? 'after-this-page rule' : r.kind === 'requiredIf' ? 'required rule' : 'show rule'
          return (
            <span key={`${r.ownerId}-${r.kind}`}>
              {pageIndex >= 0 ? (
                `Page ${pageIndex + 1}, ${what}`
              ) : (
                <>
                  <bdi dir="auto" lang={lang}>
                    {el ? blockLabel(el) || r.ownerId : r.ownerId}
                  </bdi>
                  , {what}
                </>
              )}
            </span>
          )
        })}
      </span>
    </span>
  )
}

export function ConfirmDialogs() {
  const store = useStore()
  const confirm = useBuilder((s) => s.confirm)
  const form = useBuilder((s) => s.schema)
  const close = () => store.setConfirm(null)

  let title = ''
  let ids = new Set<string>()
  let questionCount = 0
  if (confirm?.kind === 'element') {
    const el = findElement(form, confirm.id)?.el
    title = el ? `Delete ${quoted(el)}?` : 'Delete this question?'
    ids = new Set(el ? subtreeIds(el) : [])
  } else if (confirm?.kind === 'page') {
    const page = form.pages[confirm.pageIndex]
    ids = new Set([page?.id ?? '', ...(page?.elements ?? []).flatMap(subtreeIds)])
    questionCount = (page?.elements ?? []).flatMap(subtreeIds).length
    title = questionCount
      ? `Delete page ${confirm.pageIndex + 1} and its ${questionCount} ${questionCount === 1 ? 'question' : 'questions'}?`
      : `Delete page ${confirm.pageIndex + 1}?`
  }

  return (
    <AlertDialog open={confirm !== null} onOpenChange={(open) => !open && close()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription className="flex flex-col gap-2">
            <span>You can undo this right after.</span>
            <RuleList ids={ids} />
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={() => {
              if (confirm?.kind === 'element') deleteElement(store, confirm.id, true)
              if (confirm?.kind === 'page') {
                const n = confirm.pageIndex + 1
                store.edit((f) => removePage(f, confirm.pageIndex))
                toast(`Deleted page ${n}`, { action: { label: 'Undo', onClick: () => void store.undo() } })
              }
              close()
            }}
          >
            {confirm?.kind === 'page' ? 'Delete page' : 'Delete question'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function ConflictDialog() {
  const store = useStore()
  const conflict = useBuilder((s) => s.conflict)
  return (
    <AlertDialog open={conflict}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>This form was changed somewhere else</AlertDialogTitle>
          <AlertDialogDescription>
            Someone (or another tab) edited this form after you opened it. Reload to get the latest version. Your
            last change will be lost.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              void navigator.clipboard?.writeText(store.pendingPatch()).then(() => toast('Copied your change as JSON'))
            }}
          >
            Copy my change as JSON
          </Button>
          <AlertDialogAction onClick={() => void store.reload()}>Reload</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
