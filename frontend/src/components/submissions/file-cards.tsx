/**
 * Uploaded and imported files as tappable cards (SUBMISSIONS-VIEWER-SCREENS 1.3): the whole card
 * is the target. Images open a larger preview in a `Dialog` with Download; other files download.
 * Long names wrap instead of running off a phone screen.
 */
import { DownloadIcon, FileIcon, FileTextIcon, MaximizeIcon, SignatureIcon } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { formatSize } from '@/renderer/util'

export interface FileCardEntry {
  key: string
  /** Download address (served as an attachment). */
  url: string
  name: string
  mime: string
  size: number
  /** A signature brought over from Jotform: an image, not captured by JustForms. */
  importedSignature?: boolean
}

/** Images the API shows inline with `?preview=1` (backend files.PREVIEWABLE). */
export const PREVIEWABLE = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])

function Media({ f }: { f: FileCardEntry }) {
  if (PREVIEWABLE.has(f.mime))
    return (
      <ItemMedia variant="image" className="group-data-[size=sm]/item:size-16 bg-paper">
        <img src={`${f.url}?preview=1`} alt="" loading="lazy" />
      </ItemMedia>
    )
  return (
    <ItemMedia variant="icon" className="size-11 rounded-sm bg-muted">
      {f.importedSignature ? <SignatureIcon /> : f.mime === 'application/pdf' ? <FileTextIcon /> : <FileIcon />}
    </ItemMedia>
  )
}

function Body({ f, action }: { f: FileCardEntry; action: string }) {
  return (
    <ItemContent className="min-w-0">
      <ItemTitle className="max-w-full flex-wrap">
        <bdi dir="auto" className="min-w-0 break-all">
          {f.name}
        </bdi>
        {f.importedSignature && <Badge variant="outline">Imported</Badge>}
      </ItemTitle>
      <ItemDescription className="line-clamp-none">
        {f.importedSignature ? (
          'Image from Jotform, not captured by JustForms'
        ) : (
          <span className="tabular-nums">{formatSize(f.size)}</span>
        )}
        <span className="sr-only">, {action}</span>
      </ItemDescription>
    </ItemContent>
  )
}

function ImageCard({ f }: { f: FileCardEntry }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Item variant="outline" size="sm" className="min-h-11 flex-nowrap bg-card text-start break-inside-avoid hover:bg-accent/50" asChild>
        <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog">
          <Media f={f} />
          <Body f={f} action="opens a larger preview" />
          <ItemActions className="text-sm text-primary print:hidden">
            <MaximizeIcon className="size-4" aria-hidden />
            <span>Open</span>
          </ItemActions>
        </button>
      </Item>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="pe-8 break-all">
              <bdi dir="auto">{f.name}</bdi>
            </DialogTitle>
            <DialogDescription>
              {f.importedSignature ? 'Image from Jotform, not captured by JustForms' : formatSize(f.size)}
            </DialogDescription>
          </DialogHeader>
          <div className="flex max-h-[70svh] justify-center overflow-auto rounded-md border bg-paper">
            <img src={`${f.url}?preview=1`} alt={f.name} className="h-auto max-w-full object-contain" />
          </div>
          <DialogFooter>
            <Button asChild>
              <a href={f.url} download={f.name}>
                <DownloadIcon />
                Download
              </a>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

export function FileCards({ files }: { files: FileCardEntry[] }) {
  return (
    <ItemGroup className="gap-2" lang="en" dir="ltr">
      {files.map((f) =>
        PREVIEWABLE.has(f.mime) ? (
          <ImageCard key={f.key} f={f} />
        ) : (
          <Item key={f.key} variant="outline" size="sm" className="min-h-11 flex-nowrap bg-card break-inside-avoid hover:bg-accent/50" asChild>
            <a href={f.url} download={f.name}>
              <Media f={f} />
              <Body f={f} action="downloads the file" />
              <ItemActions className="text-sm text-primary print:hidden">
                <DownloadIcon className="size-4" aria-hidden />
                <span>Download</span>
              </ItemActions>
            </a>
          </Item>
        ),
      )}
    </ItemGroup>
  )
}
