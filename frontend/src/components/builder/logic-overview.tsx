/** "View all logic" sheet (PHASE-2-SCREENS 2.8): every rule as a sentence, grouped by page. */
import { useNavigate } from '@tanstack/react-router'
import { TriangleAlertIcon } from 'lucide-react'
import { type ReactNode, type RefObject, useRef } from 'react'

import { Button } from '@/components/ui/button'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { buildIndex, iterLeaves } from '@/logic/form-index'
import type { Condition, Form } from '@/schema'
import { formLanguage } from '@/schema/language'

import { blockInfo, blockLabel } from './block-types'
import { ConditionSentence } from './condition-sentence'
import { useBuilder, useStore } from './store'

interface Rule {
  key: string
  pageIndex: number
  owner: ReactNode
  sentence: ReactNode
  broken: boolean
  select: () => void
}

function brokenCond(form: Form, cond: Condition): boolean {
  const index = buildIndex(form)
  for (const leaf of iterLeaves(cond)) if (!index.elements.has(leaf.field)) return true
  return false
}

export function LogicOverview({
  open,
  onOpenChange,
  formId,
  returnFocus,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  formId: string
  /** Opened from a menu item that is gone by the time the sheet closes: focus this instead. */
  returnFocus?: RefObject<HTMLElement | null>
}) {
  const store = useStore()
  const navigate = useNavigate()
  const form = useBuilder((s) => s.schema)
  const lang = formLanguage(form)
  const index = buildIndex(form)
  const rules: Rule[] = []
  // After "Edit" the inspector's logic group takes focus, so only plain closes return focus.
  const editing = useRef(false)
  const openLogic = (select: () => void) => () => {
    editing.current = true
    onOpenChange(false)
    void navigate({ to: '/forms/$formId/edit', params: { formId } })
    select()
    window.setTimeout(() => {
      const logic = document.getElementById('inspector-logic')
      logic?.click()
      logic?.focus()
    }, 100)
  }
  for (const info of index.elements.values()) {
    const el = info.element
    const owner = (
      <bdi dir="auto" lang={lang}>
        {blockLabel(el) || blockInfo(el).label}
      </bdi>
    )
    const select = () => {
      store.setPage(form.pages[info.pageIndex].id)
      store.select({ type: 'element', id: el.id })
    }
    if (el.visibleIf)
      rules.push({
        key: `${el.id}-v`,
        pageIndex: info.pageIndex,
        owner,
        sentence: <ConditionSentence cond={el.visibleIf} form={form} prefix="Shown when" />,
        broken: brokenCond(form, el.visibleIf),
        select,
      })
    if (el.kind === 'field' && el.requiredIf)
      rules.push({
        key: `${el.id}-r`,
        pageIndex: info.pageIndex,
        owner,
        sentence: <ConditionSentence cond={el.requiredIf} form={form} prefix="Required when" />,
        broken: brokenCond(form, el.requiredIf),
        select,
      })
  }
  form.pages.forEach((page, i) => {
    const owner = `Page ${i + 1}`
    const select = () => store.setPage(page.id)
    if (page.visibleIf)
      rules.push({
        key: `${page.id}-v`,
        pageIndex: i,
        owner,
        sentence: <ConditionSentence cond={page.visibleIf} form={form} prefix="Shown when" />,
        broken: brokenCond(form, page.visibleIf),
        select,
      })
    ;(page.next ?? []).forEach((rule, j) => {
      const target = rule.goto === 'submit' ? 'submit the form' : `go to page ${form.pages.findIndex((p) => p.id === rule.goto) + 1}`
      rules.push({
        key: `${page.id}-n${j}`,
        pageIndex: i,
        owner: `${owner}, after this page`,
        sentence: (
          <>
            <ConditionSentence cond={rule.if} form={form} prefix="If" />, {target}
          </>
        ),
        broken: brokenCond(form, rule.if),
        select,
      })
    })
  })

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full data-[side=right]:w-full data-[side=right]:sm:max-w-xl"
        onOpenAutoFocus={() => {
          editing.current = false
        }}
        onCloseAutoFocus={(e) => {
          if (editing.current) return e.preventDefault()
          if (!returnFocus?.current) return
          e.preventDefault()
          returnFocus.current.focus()
        }}
      >
        <SheetHeader>
          <SheetTitle>All logic</SheetTitle>
          <SheetDescription>
            {rules.length ? `${rules.length} ${rules.length === 1 ? 'rule' : 'rules'} in this form.` : 'This form has no logic yet.'}
          </SheetDescription>
        </SheetHeader>
        <ScrollArea className="min-h-0 flex-1 px-4 pb-6">
          <div className="flex flex-col gap-6">
            {form.pages.map((page, i) => {
              const list = rules.filter((r) => r.pageIndex === i)
              if (!list.length) return null
              return (
                <section key={page.id} className="flex flex-col gap-2" aria-label={`Page ${i + 1}`}>
                  <h3 className="text-sm font-medium text-muted-foreground">
                    Page {i + 1}
                    {page.title && (
                      <>
                        ,{' '}
                        <bdi dir="auto" lang={lang}>
                          {page.title}
                        </bdi>
                      </>
                    )}
                  </h3>
                  <ItemGroup className="gap-2">
                    {list.map((r) => (
                      <Item key={r.key} variant="outline" size="sm">
                        {r.broken && (
                          <ItemMedia variant="icon">
                            <TriangleAlertIcon className="text-destructive" aria-label="Uses a deleted question" />
                          </ItemMedia>
                        )}
                        <ItemContent>
                          <ItemTitle>{r.owner}</ItemTitle>
                          <ItemDescription className="line-clamp-none">{r.sentence}.</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                          <Button variant="outline" size="sm" onClick={openLogic(r.select)}>
                            Edit
                          </Button>
                        </ItemActions>
                      </Item>
                    ))}
                  </ItemGroup>
                </section>
              )
            })}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}
