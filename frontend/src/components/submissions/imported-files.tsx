/**
 * Copies of files and signatures brought over from Jotform (DESIGN 13.3, "Imported files").
 * They sit outside the answers and the content hash; imported signatures are images only and
 * are marked as not captured by JustForms.
 */
import { DownloadIcon, FileIcon, FileTextIcon, SignatureIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatSize } from '@/renderer/util'

export type ImportedFile = {
  fieldId: string
  index: number
  kind: 'file' | 'signature'
  name: string
  mime: string
  size: number
  fetchedAt?: string | null
  url: string
}

const PREVIEW = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])

export function ImportedFiles({ files, labels }: { files: ImportedFile[]; labels: Map<string, string> }) {
  return (
    <ItemGroup className="gap-2" lang="en" dir="ltr">
      {files.map((f) => {
        const label = labels.get(f.fieldId) ?? f.fieldId
        return (
          <Item key={`${f.fieldId}-${f.index}`} variant="outline" size="sm" className="flex-nowrap bg-background">
            <ItemMedia variant={PREVIEW.has(f.mime) ? 'image' : 'icon'}>
              {PREVIEW.has(f.mime) ? (
                <img src={`${f.url}?preview=1`} alt={f.kind === 'signature' ? `Imported signature: ${label}` : ''} loading="lazy" />
              ) : f.kind === 'signature' ? (
                <SignatureIcon />
              ) : f.mime === 'application/pdf' ? (
                <FileTextIcon />
              ) : (
                <FileIcon />
              )}
            </ItemMedia>
            <ItemContent className="min-w-0">
              <ItemTitle className="max-w-full">
                <bdi dir="auto" className="truncate">
                  {label}
                </bdi>
                {f.kind === 'signature' && <Badge variant="outline">Imported</Badge>}
              </ItemTitle>
              <ItemDescription className="truncate">
                {f.kind === 'signature' ? (
                  'Image from Jotform, not captured by JustForms'
                ) : (
                  <>
                    <bdi dir="auto">{f.name}</bdi> · <span className="tabular-nums">{formatSize(f.size)}</span>
                  </>
                )}
              </ItemDescription>
            </ItemContent>
            <ItemActions>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon-sm" asChild>
                    <a href={f.url} download={f.name} aria-label={`Download ${f.name}`}>
                      <DownloadIcon />
                    </a>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Download</TooltipContent>
              </Tooltip>
            </ItemActions>
          </Item>
        )
      })}
    </ItemGroup>
  )
}
