/** Publish flow (PHASE-2-SCREENS 3.1): problems dialog, first-publish confirmation, toast. */
import { useNavigate } from '@tanstack/react-router'
import { TriangleAlertIcon } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Spinner } from '@/components/ui/spinner'
import type { FormSummary } from '@/lib/api'
import { formLanguage } from '@/schema/language'

import { approvalChecks, useApprovalConfig } from './approval-problems'
import { blockLabel } from './block-types'
import { blockPosition, formProblems } from './problems'
import { useBuilder, useStore } from './store'
import type { PublishMutation } from './use-publish'
import { findElement, formCounts } from './tree'

export function PublishDialog({ form, mutation }: { form: FormSummary; mutation: PublishMutation }) {
  const store = useStore()
  const navigate = useNavigate()
  const approvals = useApprovalConfig(form.id)
  const open = useBuilder((s) => s.publishing)
  const schema = useBuilder((s) => s.schema)
  const checks = approvalChecks(approvals, schema)
  const problems = [
    ...formProblems(schema),
    ...checks.errors.map((message) => ({ target: null, pageIndex: null, message, settings: true })),
  ]
  const counts = formCounts(schema)
  const lang = formLanguage(schema)
  const close = () => store.setPublishing(false)
  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="sm:max-w-lg">
        {problems.length ? (
          <>
            <DialogHeader>
              <DialogTitle>Fix these before publishing</DialogTitle>
              <DialogDescription>
                {problems.length === 1 ? '1 problem stops' : `${problems.length} problems stop`} this form from going
                live.{problems.length > 5 && ' Scroll the list to see them all.'}
              </DialogDescription>
            </DialogHeader>
            <ScrollArea className="-mx-1 [&>[data-slot=scroll-area-viewport]]:max-h-80">
              <ItemGroup className="gap-2 px-1 pe-3">
                {problems.map((p, i) => {
                  const el = p.target ? findElement(schema, p.target)?.el : undefined
                  const settings = 'settings' in p
                  const label = el ? blockLabel(el) : ''
                  const where = settings
                    ? 'Settings, Approvals'
                    : el && p.target
                      ? (blockPosition(schema, p.target) ?? 'Form')
                      : p.pageIndex !== null
                        ? `Page ${p.pageIndex + 1}`
                        : 'Form'
                  return (
                    <Item key={i} variant="outline" size="sm">
                      <ItemMedia variant="icon">
                        <TriangleAlertIcon className="text-destructive" />
                      </ItemMedia>
                      <ItemContent>
                        <ItemTitle className="font-normal">{p.message}</ItemTitle>
                        <ItemDescription>
                          {where}
                          {label && (
                            <>
                              ,{' '}
                              <bdi dir="auto" lang={lang}>
                                {label}
                              </bdi>
                            </>
                          )}
                        </ItemDescription>
                      </ItemContent>
                      <ItemActions>
                        <Button
                          variant="outline"
                          size="sm"
                          aria-label={settings ? 'Open settings' : `Show ${where}`}
                          onClick={() => {
                            close()
                            if (settings) void navigate({ to: '/forms/$formId/settings', params: { formId: form.id }, hash: 'approvals' })
                            else if (p.target && el) {
                              store.setPage(schema.pages[p.pageIndex ?? 0].id)
                              store.select({ type: 'element', id: p.target })
                            } else if (p.pageIndex !== null) store.setPage(schema.pages[p.pageIndex].id)
                            else store.select({ type: 'form' })
                          }}
                        >
                          {settings ? 'Open settings' : 'Show'}
                        </Button>
                      </ItemActions>
                    </Item>
                  )
                })}
              </ItemGroup>
            </ScrollArea>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">Close</Button>
              </DialogClose>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Publish this form?</DialogTitle>
              <DialogDescription>
                {counts.pages} {counts.pages === 1 ? 'page' : 'pages'}, {counts.questions}{' '}
                {counts.questions === 1 ? 'question' : 'questions'}, {counts.rules}{' '}
                {counts.rules === 1 ? 'logic rule' : 'logic rules'}.
              </DialogDescription>
            </DialogHeader>
            <p className="text-sm">After publishing, question keys are locked so your data stays consistent.</p>
            {checks.warnings.length > 0 && (
              <Alert>
                <TriangleAlertIcon />
                <AlertTitle>Check the approvals</AlertTitle>
                <AlertDescription>
                  <ul className="list-disc ps-4">
                    {checks.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                  <p>Responses without an approver's address wait until someone stops the approval.</p>
                </AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">Cancel</Button>
              </DialogClose>
              <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
                {mutation.isPending && <Spinner />}
                Publish
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

