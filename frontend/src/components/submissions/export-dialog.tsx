/** "Export to Excel" (PHASE-3-SCREENS 7): starts a worker job and shows its progress. */
import { useMutation, useQuery } from '@tanstack/react-query'
import { DownloadIcon, TriangleAlertIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Progress } from '@/components/ui/progress'
import { api, type ListFilters } from '@/lib/api'

export function ExportDialog({
  open,
  onOpenChange,
  formId,
  filters,
  count,
  sensitive,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  formId: string
  filters: ListFilters
  count: number
  /** Labels of sensitive questions in the form. */
  sensitive: string[]
}) {
  const start = useMutation({ mutationFn: () => api.startExport(formId, filters) })
  const jobId = start.data?.id
  const job = useQuery({
    queryKey: ['export', jobId],
    queryFn: () => api.getExport(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === 'ready' || q.state.data?.status === 'failed' ? false : 1000),
  })
  const status = job.data?.status ?? (start.isPending ? 'pending' : undefined)
  const openRef = useRef(open)
  useEffect(() => {
    openRef.current = open
  }, [open])
  // Closing early leaves the job running; say so when it is ready.
  const announced = useRef<string | null>(null)
  useEffect(() => {
    const d = job.data
    if (d?.status === 'ready' && d.downloadUrl && !openRef.current && announced.current !== d.id) {
      announced.current = d.id
      toast('Export ready', { action: { label: 'Download', onClick: () => window.location.assign(d.downloadUrl!) } })
    }
  }, [job.data, open])

  const total = job.data?.rowCount ?? null
  const done = job.data?.rowsDone ?? 0
  const pct = total ? Math.round((done / Math.max(total, 1)) * 100) : null
  const reset = () => {
    start.reset()
    announced.current = null
  }
  const running = status === 'pending' || status === 'running'

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o)
        if (!o && !running) reset()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Export to Excel</DialogTitle>
          <DialogDescription>
            <span className="tabular-nums">{count}</span> {count === 1 ? 'submission' : 'submissions'}, with every question from all
            versions. Repeaters go to their own sheets.
          </DialogDescription>
        </DialogHeader>
        {sensitive.length > 0 && (
          <Alert>
            <TriangleAlertIcon />
            <AlertTitle>Includes sensitive answers</AlertTitle>
            <AlertDescription>
              <bdi dir="auto">{sensitive.join(', ')}</bdi>. Store the file somewhere safe.
            </AlertDescription>
          </Alert>
        )}
        {status && status !== 'failed' && (
          <div className="flex flex-col gap-2" aria-live="polite">
            <Progress value={status === 'ready' ? 100 : (pct ?? 5)} aria-label="Export progress" />
            <p className="text-sm text-muted-foreground tabular-nums">
              {status === 'ready'
                ? 'Your export is ready. Available for 24 hours.'
                : total
                  ? `Preparing export, ${done} of ${total}`
                  : 'Preparing export'}
            </p>
          </div>
        )}
        {(status === 'failed' || start.isError) && (
          <Alert variant="destructive">
            <AlertDescription>Couldn't create the export. Try again.</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">{status === 'ready' ? 'Close' : 'Cancel'}</Button>
          </DialogClose>
          {status === 'ready' && job.data?.downloadUrl ? (
            <Button asChild>
              <a href={job.data.downloadUrl} download>
                <DownloadIcon />
                Download
              </a>
            </Button>
          ) : (
            <Button
              disabled={running}
              onClick={() => {
                reset()
                start.mutate()
              }}
            >
              {status === 'failed' || start.isError ? 'Try again' : 'Export'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
