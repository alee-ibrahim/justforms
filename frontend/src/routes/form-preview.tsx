/** Preview (PHASE-2-SCREENS 2.10): the real renderer with the draft; nothing is posted. */
import { ChevronRightIcon, InfoIcon, MonitorIcon, RotateCcwIcon, SmartphoneIcon } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useCallback, useState } from 'react'

import { ConditionSentence } from '@/components/builder/condition-sentence'
import { useFormSummary } from '@/components/builder/form-context'
import { useBuilder } from '@/components/builder/store'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { Evaluation } from '@/logic/engine'
import { buildIndex } from '@/logic/form-index'
import { formThemeQuery } from '@/lib/queries'
import { canvasMode, themeScope, useFontLinks } from '@/lib/theme'
import { toggleGroupOn } from '@/lib/toggle'
import { cn } from '@/lib/utils'
import type { Uploader } from '@/renderer/context'
import { FormRenderer } from '@/renderer/form-view'
import type { Form } from '@/schema'
import { formLanguage } from '@/schema/language'

import { NoEditAccess } from './form-layout'

/** Preview uploads stay in the browser; progress is simulated so the states can be checked. */
const localUploader: Uploader = (file, _field, onProgress, signal) =>
  new Promise((resolve, reject) => {
    let p = 0
    const t = window.setInterval(() => {
      p = Math.min(1, p + 0.25)
      onProgress(p)
      if (p >= 1) {
        window.clearInterval(t)
        resolve({ fileId: `preview-${file.name}`, name: file.name, size: file.size, mime: file.type })
      }
    }, 150)
    signal.addEventListener('abort', () => {
      window.clearInterval(t)
      reject(new Error('aborted'))
    })
  })

function LogicTrace({ form, ev }: { form: Form; ev: Evaluation | null }) {
  const [open, setOpen] = useState(false)
  if (!ev) return null
  const index = buildIndex(form)
  const lang = formLanguage(form)
  const pageNumbers = ev.path.map((id) => form.pages.findIndex((p) => p.id === id) + 1)
  const skipped = form.pages.map((p, i) => ({ p, i })).filter(({ p }) => !ev.path.includes(p.id))
  const hidden = ev.hidden
    .map((id) => index.elements.get(id))
    .filter((info) => info && ev.path.includes(form.pages[info.pageIndex].id) && info.element.visibleIf)
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mx-auto w-full max-w-[var(--df-sheet,40rem)]">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="group/t">
          <ChevronRightIcon className="transition-transform group-data-[state=open]/t:rotate-90 motion-reduce:transition-none" />
          Logic trace
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-2 rounded-md border bg-card p-4 text-sm">
        <p>
          Pages: {pageNumbers.join(', ')}.
          {skipped.map(({ p, i }) => (
            <span key={p.id}>
              {' '}
              Page {i + 1} skipped
              {p.visibleIf ? (
                <>
                  {' '}
                  because it shows only when <ConditionSentence cond={p.visibleIf} form={form} />
                </>
              ) : (
                ' by a jump rule'
              )}
              .
            </span>
          ))}
        </p>
        {hidden.length ? (
          <ul className="flex list-disc flex-col gap-1 ps-5">
            {hidden.map((info) => (
              <li key={info!.id}>
                <bdi dir="auto" lang={lang}>
                  {(info!.element.kind === 'field' || info!.element.kind === 'repeater' ? info!.element.label : info!.id) || info!.id}
                </bdi>{' '}
                is hidden: it shows only when <ConditionSentence cond={info!.element.visibleIf!} form={form} />.
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">No questions are hidden on these pages.</p>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

export function FormPreviewPage() {
  const summary = useFormSummary()
  const theme = useQuery(formThemeQuery(summary.id)).data?.preview
  useFontLinks(theme?.fonts)
  const scope = themeScope(theme, canvasMode(theme))
  const schema = useBuilder((s) => s.schema)
  const [device, setDevice] = useState<'phone' | 'desktop'>('phone')
  const [run, setRun] = useState(0)
  const [ev, setEv] = useState<Evaluation | null>(null)
  const onEvaluate = useCallback((e: Evaluation | null) => setEv(e), [])
  if (summary.role === 'viewer') return <NoEditAccess />
  return (
    <main className="flex flex-col gap-4 px-4 py-4 sm:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-3">
        <Alert className="min-w-0 flex-1 py-1.5">
          <InfoIcon />
          <AlertDescription>Preview of your latest changes. Answers aren't saved.</AlertDescription>
        </Alert>
        <ToggleGroup type="single" variant="outline" value={device} onValueChange={(v) => v && setDevice(v as typeof device)} aria-label="Device" className={toggleGroupOn}>
          <ToggleGroupItem value="phone">
            <SmartphoneIcon />
            Phone
          </ToggleGroupItem>
          <ToggleGroupItem value="desktop">
            <MonitorIcon />
            Desktop
          </ToggleGroupItem>
        </ToggleGroup>
        <Button variant="outline" size="sm" onClick={() => setRun((n) => n + 1)}>
          <RotateCcwIcon />
          Restart
        </Button>
      </div>
      <div
        {...scope}
        data-df-device={device}
        className={cn(
          scope.className,
          'mx-auto w-full overflow-hidden text-foreground',
          device === 'phone' ? 'max-w-[390px] rounded-xl border bg-card' : 'max-w-5xl',
        )}
      >
        <FormRenderer
          key={run}
          form={schema}
          mode="preview"
          frame={device === 'phone' ? 'bare' : 'page'}
          orgName={undefined}
          uploader={localUploader}
          theme={theme?.options}
          onEvaluate={onEvaluate}
          onSubmit={async () => ({ ok: true, reference: 'Preview' })}
        />
      </div>
      <LogicTrace form={schema} ev={ev} />
    </main>
  )
}
