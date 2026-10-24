/**
 * Builder (PHASE-2-SCREENS 2.2, 2.11): palette, canvas and inspector in resizable panes on
 * desktop; drawers for the palette (< 1024px) and the inspector (< 768px).
 */
import { PlusIcon } from 'lucide-react'
import { useState, useSyncExternalStore } from 'react'

import { SuggestionBanner, SuggestionBar, SuggestionScope } from '@/components/ai/ai-canvas'
import { AiPanel } from '@/components/ai/ai-panel'
import { type AiController, useAi, useAiController, useSuggestion } from '@/components/ai/controller'
import { Canvas } from '@/components/builder/canvas'
import { BuilderDnd } from '@/components/builder/dnd'
import { useFormSummary } from '@/components/builder/form-context'
import { InsertCommand } from '@/components/builder/insert-command'
import { Inspector } from '@/components/builder/inspector'
import { Palette, TypeList } from '@/components/builder/palette'
import { PageStrip } from '@/components/builder/page-strip'
import { InspectorDrawerContext } from '@/components/builder/drawer-context'
import { useBuilder, useStore } from '@/components/builder/store'
import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from '@/components/ui/drawer'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { ScrollArea } from '@/components/ui/scroll-area'

import { NoEditAccess } from './form-layout'

function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query)
      m.addEventListener('change', cb)
      return () => m.removeEventListener('change', cb)
    },
    () => window.matchMedia(query).matches,
  )
}

function PageSheet() {
  return (
    <>
      <div className="mx-auto w-full max-w-[40rem]" onClick={(e) => e.stopPropagation()}>
        <PageStrip />
      </div>
      <Canvas />
    </>
  )
}

function CanvasPane({ narrow, phone, onBackToChat }: { narrow: boolean; phone?: boolean; onBackToChat?: () => void }) {
  const store = useStore()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const suggestion = useSuggestion()
  const locked = useBuilder((s) => s.locked)
  return (
    <section aria-label="Form canvas" className="flex h-full min-h-0 flex-col">
      <ScrollArea className="min-h-0 flex-1 [&_[data-slot=scroll-area-viewport]>div]:block!">
        <div
          className="flex flex-col gap-3 px-3 py-4 sm:px-6"
          onClick={() => {
            const s = suggestion?.showing === 'suggestion' ? suggestion.preview : store
            s.select({ type: 'page', pageId: s.get().pageId })
          }}
        >
          {suggestion && <SuggestionBanner ai={suggestion.ai} showing={suggestion.showing} />}
          {suggestion?.showing === 'suggestion' ? (
            <SuggestionScope preview={suggestion.preview}>
              <PageSheet />
            </SuggestionScope>
          ) : (
            <PageSheet />
          )}
          {narrow && !locked && (
            <Drawer open={paletteOpen} onOpenChange={setPaletteOpen}>
              <DrawerTrigger asChild>
                <Button className="mx-auto w-full max-w-[40rem]" variant="outline" onClick={(e) => e.stopPropagation()}>
                  <PlusIcon />
                  Add question
                </Button>
              </DrawerTrigger>
              <DrawerContent>
                <DrawerHeader>
                  <DrawerTitle>Add a question</DrawerTitle>
                  <DrawerDescription>Tap a question type to add it after the selected question.</DrawerDescription>
                </DrawerHeader>
                <ScrollArea className="max-h-[60vh] px-4 pb-6">
                  <TypeList onAdded={() => setPaletteOpen(false)} />
                </ScrollArea>
              </DrawerContent>
            </Drawer>
          )}
        </div>
      </ScrollArea>
      {phone && suggestion && onBackToChat && <SuggestionBar ai={suggestion.ai} onBack={onBackToChat} />}
    </section>
  )
}

/** Phones: the inspector opens in a drawer when a block is tapped. */
function InspectorDrawer() {
  const store = useStore()
  // Opens when a block is tapped outside its text; editing text in place never opens it.
  const inspect = useBuilder((s) => s.inspect)
  const element = useBuilder((s) => s.selection.type === 'element')
  const [openedAt, setOpenedAt] = useState<number | null>(null)
  if (element && inspect > 0 && openedAt !== inspect && openedAt !== -inspect) setOpenedAt(inspect)
  else if (!element && openedAt === inspect) setOpenedAt(-inspect)
  const open = element && openedAt === inspect
  return (
    <Drawer
      open={open}
      onOpenChange={(o) => {
        if (o) return
        setOpenedAt(-inspect)
        store.select({ type: 'page', pageId: store.get().pageId })
      }}
    >
      <DrawerContent className="max-h-[85vh]">
        <DrawerHeader className="sr-only">
          <DrawerTitle>Question settings</DrawerTitle>
          <DrawerDescription>Edit the selected question</DrawerDescription>
        </DrawerHeader>
        <div className="h-[60vh] min-h-0">
          <Inspector />
        </div>
      </DrawerContent>
    </Drawer>
  )
}

/** Phones: the AI assistant in a drawer; "Preview on the form" closes it. */
function AiDrawer({ ai }: { ai: AiController }) {
  const open = useAi(ai, (s) => s.open)
  return (
    <Drawer open={open} onOpenChange={(o) => ai.setOpen(o)}>
      <DrawerContent className="h-[85vh] max-h-[85vh]">
        <DrawerHeader className="pb-0">
          <DrawerTitle>AI assistant</DrawerTitle>
          <DrawerDescription className="sr-only">Describe a form or ask for changes</DrawerDescription>
        </DrawerHeader>
        <div className="min-h-0 flex-1">
          <AiPanel ai={ai} headerless onClose={() => ai.setOpen(false)} onPreview={() => ai.setOpen(false)} />
        </div>
      </DrawerContent>
    </Drawer>
  )
}

export function FormEditorPage() {
  const form = useFormSummary()
  const wide = useMedia('(min-width: 1024px)')
  // Landscape phones are wide but short: they get the phone layout (drawers), not three panes.
  const tablet = useMedia('(min-width: 768px) and (min-height: 560px)')
  const ai = useAiController()
  const aiOpen = useAi(ai, (s) => s.open)
  const locked = useBuilder((s) => s.locked)
  if (form.role === 'viewer') return <NoEditAccess />

  return (
    <BuilderDnd>
      <div className="flex min-h-0 min-w-0 flex-1">
        {tablet ? (
          <ResizablePanelGroup orientation="horizontal" className="min-h-0">
            {wide && (
              <>
                <ResizablePanel id="palette" defaultSize={240} minSize={200} maxSize={360} className="border-e">
                  <div className="h-full" inert={locked} aria-disabled={locked || undefined}>
                    <Palette />
                  </div>
                </ResizablePanel>
                <ResizableHandle aria-label="Resize panel" />
              </>
            )}
            <ResizablePanel id="canvas" minSize={360}>
              <CanvasPane narrow={!wide} />
            </ResizablePanel>
            <ResizableHandle aria-label="Resize panel" />
            <ResizablePanel id="inspector" defaultSize={340} minSize={300} maxSize={480} className="border-s">
              {ai && aiOpen ? <AiPanel ai={ai} onClose={() => ai.setOpen(false)} /> : <Inspector />}
            </ResizablePanel>
          </ResizablePanelGroup>
        ) : (
          <div className="min-h-0 min-w-0 flex-1">
            <InspectorDrawerContext.Provider value={!locked}>
              <CanvasPane narrow phone onBackToChat={ai ? () => ai.setOpen(true) : undefined} />
            </InspectorDrawerContext.Provider>
            {!locked && <InspectorDrawer />}
            {ai && <AiDrawer ai={ai} />}
          </div>
        )}
      </div>
      <InsertCommand />
    </BuilderDnd>
  )
}
