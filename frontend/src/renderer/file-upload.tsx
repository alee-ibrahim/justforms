/**
 * File question (PHASE-2-SCREENS 4.8): Empty drop area + a button that opens a hidden file
 * input, files as Item rows with Progress. Uploads start on select; Next waits for them.
 */
import { FileIcon, FileTextIcon, RotateCwIcon, UploadIcon, XIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Empty, EmptyContent, EmptyDescription, EmptyMedia } from '@/components/ui/empty'
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from '@/components/ui/item'
import { Progress } from '@/components/ui/progress'
import type { FileField } from '@/schema'

import { pathKey, useRenderer } from './context'
import type { ControlProps } from './fields'
import { fmt, MSG } from './messages'
import { En } from './msg'
import { acceptedTypes, formatSize } from './util'
import type { FileRef } from './validation'

function accepts(field: FileField, file: File): boolean {
  const list = (field.accept ?? []).map((a) => a.toLowerCase())
  if (!list.length) return true
  const name = file.name.toLowerCase()
  const mime = file.type.toLowerCase()
  return list.some((a) =>
    a.startsWith('.')
      ? name.endsWith(a)
      : a.endsWith('/*')
        ? mime.startsWith(a.slice(0, -1))
        : mime === a,
  )
}

/** Why an upload failed, from the API's refusal code (public/upload.ts). English system text. */
function failReason(err: unknown, name: string, types: string, maxMb: number | null): string {
  const code = err instanceof Error ? err.message : ''
  if (code === 'file_type') return fmt(MSG.fileType, { name, types })
  if (code === 'file_too_large')
    return maxMb ? fmt(MSG.fileTooLarge, { name, size: maxMb }) : `“${name}” is too large. Choose a smaller file.`
  if (code === 'file_empty') return `“${name}” is empty. Choose a different file.`
  if (code === 'rate_limited') return 'Too many uploads in a short time. Wait a minute, then retry.'
  return "The upload didn't finish. Check your connection, then retry."
}

interface Entry {
  key: string
  file: File
  status: 'uploading' | 'done' | 'error'
  progress: number
  ref?: FileRef
  error?: string
  /** False when the file itself was refused: retrying the same file can't help. */
  retryable?: boolean
  preview?: string
}

let counter = 0

export default function FileUpload({ field, path, invalid, describedBy }: ControlProps & { field: FileField }) {
  const ctx = useRenderer()
  const inputRef = useRef<HTMLInputElement>(null)
  const controllers = useRef(new Map<string, AbortController>())
  const [entries, setEntries] = useState<Entry[]>(() => {
    const v = ctx.getValue(path)
    return Array.isArray(v)
      ? (v as FileRef[]).map((ref) => ({
          key: ref.fileId,
          file: new File([], ref.name, { type: ref.mime }),
          status: 'done' as const,
          progress: 1,
          ref,
        }))
      : []
  })
  const current = useRef(entries)
  /** Apply a change to the list; publish finished files as the answer when asked. */
  const mutate = (fn: (list: Entry[]) => Entry[], publish = false) => {
    const next = fn(current.current)
    current.current = next
    setEntries(next)
    if (publish) {
      const refs = next.filter((e) => e.status === 'done' && e.ref).map((e) => e.ref!)
      setValue(path, refs.length ? refs : undefined)
    }
  }
  const [rejected, setRejected] = useState<string | null>(null)
  const maxFiles = field.maxFiles ?? 1
  const maxMb = field.maxSizeMb ?? null
  const types = acceptedTypes(field)
  const key = pathKey(path)
  const busy = entries.some((e) => e.status === 'uploading')
  const counted = entries.filter((e) => e.status !== 'error').length

  const { setUploading, setValue } = ctx
  useEffect(() => {
    setUploading(key, busy)
  }, [busy, key, setUploading])
  useEffect(() => () => setUploading(key, false), [key, setUploading])
  useEffect(() => {
    const ctrls = controllers.current
    return () => ctrls.forEach((c) => c.abort())
  }, [])

  const start = (entry: Entry) => {
    const ctrl = new AbortController()
    controllers.current.set(entry.key, ctrl)
    const update = (patch: Partial<Entry>) =>
      mutate(
        (list) => list.map((e) => (e.key === entry.key ? { ...e, ...patch } : e)),
        patch.status !== undefined,
      )
    ctx
      .uploader(entry.file, field.id, (p) => update({ progress: p }), ctrl.signal)
      .then((ref) => update({ status: 'done', progress: 1, ref }))
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted)
          update({
            status: 'error',
            error: failReason(err, entry.file.name, types, maxMb),
            retryable: !/^file_(type|too_large|empty)$/.test(err instanceof Error ? err.message : ''),
          })
      })
  }

  const add = (files: FileList | File[]) => {
    setRejected(null)
    // A failed file doesn't use up a place: it can be retried or replaced.
    const room = maxFiles - current.current.filter((e) => e.status !== 'error').length
    const fresh: Entry[] = []
    for (const file of Array.from(files).slice(0, Math.max(0, room))) {
      if (!accepts(field, file)) {
        setRejected(fmt(MSG.fileType, { name: file.name, types }))
        continue
      }
      if (maxMb && file.size > maxMb * 1024 * 1024) {
        setRejected(fmt(MSG.fileTooLarge, { name: file.name, size: maxMb }))
        continue
      }
      fresh.push({
        key: `f${++counter}`,
        file,
        status: 'uploading',
        progress: 0,
        preview: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
      })
    }
    if (!fresh.length) return
    mutate((list) => [...list, ...fresh])
    fresh.forEach(start)
  }

  const remove = (entry: Entry) => {
    controllers.current.get(entry.key)?.abort()
    if (entry.preview) URL.revokeObjectURL(entry.preview)
    mutate((list) => list.filter((e) => e.key !== entry.key), true)
    ctx.blur(path)
  }

  const retry = (entry: Entry) => {
    const again = { ...entry, status: 'uploading' as const, progress: 0, error: undefined }
    mutate((list) => list.map((e) => (e.key === entry.key ? again : e)))
    start(again)
  }

  const hint =
    maxFiles > 1
      ? fmt(MSG.filesHint, { types, n: maxFiles, size: maxMb ?? '' })
      : fmt(MSG.fileHint, { types, size: maxMb ?? '' })

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        <En>{maxMb ? hint : types}</En>
      </p>
      {counted < maxFiles ? (
        <Empty
          className="items-start border border-input bg-transparent p-5 text-start sm:p-6 max-sm:border-0 max-sm:p-0"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            add(e.dataTransfer.files)
          }}
        >
          <EmptyMedia variant="icon" className="max-sm:hidden">
            <UploadIcon />
          </EmptyMedia>
          <EmptyDescription className="max-sm:hidden">
            <En>{MSG.dragFiles}</En>
          </EmptyDescription>
          <EmptyContent className="items-start max-sm:max-w-none">
            {/* The button stays neutral in the error state; the question's message says what's wrong. */}
            <Button
              type="button"
              variant="outline"
              className="h-12 text-base sm:h-11 max-sm:w-full"
              data-invalid={invalid || undefined}
              aria-describedby={describedBy}
              id={`q-${key.replace(/\./g, '-')}`}
              onClick={() => inputRef.current?.click()}
              onBlur={() => ctx.blur(path)}
            >
              <En>{maxFiles > 1 ? MSG.chooseFiles : MSG.chooseFile}</En>
            </Button>
          </EmptyContent>
          <input
            ref={inputRef}
            type="file"
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            multiple={maxFiles > 1}
            accept={(field.accept ?? []).join(',') || undefined}
            onChange={(e) => {
              if (e.target.files) add(e.target.files)
              e.target.value = ''
            }}
          />
        </Empty>
      ) : (
        <p className="text-sm text-muted-foreground">
          <En>{fmt(MSG.filesMaxed, { n: maxFiles })}</En>
        </p>
      )}
      {rejected && (
        <p className="text-sm text-destructive" role="alert">
          <En>{rejected}</En>
        </p>
      )}
      {entries.length > 0 && (
        <ItemGroup className="gap-2">
          {entries.map((entry) => (
            <Item key={entry.key} variant="outline" className="flex-wrap bg-card">
              <ItemMedia variant={entry.preview ? 'image' : 'icon'}>
                {entry.preview ? (
                  <img src={entry.preview} alt="" />
                ) : entry.file.type === 'application/pdf' ? (
                  <FileTextIcon />
                ) : (
                  <FileIcon />
                )}
              </ItemMedia>
              <ItemContent className="min-w-0">
                <ItemTitle className="max-w-full text-base">
                  <bdi className="truncate" lang={/[\u0780-\u07bf]/.test(entry.file.name) ? 'dv' : 'en'}>
                    {entry.file.name}
                  </bdi>
                </ItemTitle>
                <ItemDescription
                  className={entry.status === 'error' ? 'text-destructive' : 'tabular-nums'}
                >
                  {entry.status === 'error' ? (
                    <En>{entry.error}</En>
                  ) : entry.status === 'uploading' ? (
                    <>
                      <En>
                        {MSG.uploading} {Math.round(entry.progress * 100)}%
                      </En>
                    </>
                  ) : (
                    <bdi dir="ltr">{formatSize(entry.ref?.size ?? entry.file.size)}</bdi>
                  )}
                </ItemDescription>
              </ItemContent>
              <ItemActions>
                {entry.status === 'error' && entry.retryable !== false && (
                  <Button type="button" variant="outline" size="sm" onClick={() => retry(entry)}>
                    <RotateCwIcon />
                    <En>{MSG.retry}</En>
                  </Button>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-11"
                  aria-label={fmt(MSG.removeFile, { name: entry.file.name })}
                  onClick={() => remove(entry)}
                >
                  <XIcon />
                </Button>
              </ItemActions>
              {entry.status === 'uploading' && (
                <Progress
                  value={entry.progress * 100}
                  className="basis-full bg-secondary rtl:-scale-x-100"
                  aria-label={MSG.uploading}
                />
              )}
            </Item>
          ))}
        </ItemGroup>
      )}
    </div>
  )
}
