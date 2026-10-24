/** "Check a PDF" (PHASE-3-SCREENS 3): is a JustForms PDF genuine, unchanged and still current? */
import { useMutation } from '@tanstack/react-query'
import { FileSearchIcon, ShieldAlertIcon, ShieldCheckIcon, UploadIcon } from 'lucide-react'
import { useRef, useState } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Empty, EmptyContent, EmptyDescription, EmptyMedia } from '@/components/ui/empty'
import { Spinner } from '@/components/ui/spinner'
import { api, type PdfCheck, type PdfVerdict } from '@/lib/api'
import { formatDateTime } from '@/lib/format'

const RESULTS: Record<PdfVerdict, { title: string; body: string }> = {
  genuine: { title: 'Genuine and unchanged', body: 'Signed by this JustForms install, and it matches the submission as it is stored now.' },
  modified: { title: 'Changed after signing', body: "The PDF's signature does not cover its current contents. Someone edited the file." },
  not_ours: { title: 'Not signed by this JustForms', body: "The PDF is signed, but not with this install's key." },
  unsigned: { title: 'Not signed', body: 'This file has no digital signature, or it is not a PDF.' },
  data_changed: { title: "Doesn't match the stored submission", body: "The PDF is genuine, but the submission's data has changed since it was signed." },
  not_found: { title: 'Submission not found', body: "The PDF is genuine, but its submission was deleted or you don't have access to it." },
}

function fingerprint(hex: string): string {
  return (hex.match(/.{2}/g) ?? []).join(':').toUpperCase()
}

function Result({ r }: { r: PdfCheck }) {
  const good = r.verdict === 'genuine'
  const text = RESULTS[r.verdict]
  return (
    <Alert variant={good ? 'default' : 'destructive'}>
      {good ? <ShieldCheckIcon /> : <ShieldAlertIcon />}
      <AlertTitle>{text.title}</AlertTitle>
      <AlertDescription>
        <p>{text.body}</p>
        <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
          {r.submission && (
            <>
              <dt>Submission</dt>
              <dd className="min-w-0">
                <span className="tabular-nums">#{String(r.submission.seq).padStart(4, '0')}</span>,{' '}
                <bdi dir="auto">{r.submission.formTitle}</bdi>
              </dd>
            </>
          )}
          {r.signedAt && (
            <>
              <dt>Signed</dt>
              <dd className="tabular-nums">{formatDateTime(r.signedAt)}</dd>
            </>
          )}
          {r.signerFingerprint && (
            <>
              <dt>Key fingerprint</dt>
              <dd className="min-w-0 font-mono break-all">{fingerprint(r.signerFingerprint)}</dd>
            </>
          )}
        </dl>
      </AlertDescription>
    </Alert>
  )
}

export function CheckPdfDialog() {
  const [open, setOpen] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const check = useMutation({ mutationFn: (file: File) => api.checkPdf(file) })
  const pick = (files: FileList | null) => {
    const file = files?.[0]
    if (file) check.mutate(file)
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) check.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <FileSearchIcon />
          Check a PDF
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Check a signed PDF</DialogTitle>
          <DialogDescription>
            Find out whether a PDF from JustForms is genuine and unchanged, and whether it still matches the submission.
          </DialogDescription>
        </DialogHeader>
        {check.data ? (
          <Result r={check.data} />
        ) : (
          <Empty
            className="border border-dashed border-input p-6"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              pick(e.dataTransfer.files)
            }}
          >
            <EmptyMedia variant="icon">{check.isPending ? <Spinner /> : <UploadIcon />}</EmptyMedia>
            <EmptyDescription>{check.isPending ? 'Checking' : 'Drop a PDF here or'}</EmptyDescription>
            <EmptyContent>
              <Button variant="outline" disabled={check.isPending} onClick={() => input.current?.click()}>
                Choose PDF
              </Button>
              <input
                ref={input}
                type="file"
                accept="application/pdf,.pdf"
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={(e) => {
                  pick(e.target.files)
                  e.target.value = ''
                }}
              />
            </EmptyContent>
          </Empty>
        )}
        {check.isError && (
          <Alert variant="destructive">
            <AlertDescription>Couldn't check the file. Check your connection and try again.</AlertDescription>
          </Alert>
        )}
        {check.data && (
          <DialogFooter>
            <Button variant="outline" onClick={() => check.reset()}>
              Check another
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}
