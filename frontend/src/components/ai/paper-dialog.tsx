/** "Start from a paper form" (PHASE-5-SCREENS 5): blank forms only, confirmed every time. */
import { useQuery } from '@tanstack/react-query'
import { ShieldAlertIcon } from 'lucide-react'
import { useId, useState } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, FieldContent, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { metaQuery } from '@/lib/queries'

import { fileProblem } from './files'

function size(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function PaperDialog({
  open,
  onOpenChange,
  onRead,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onRead: (file: File) => void
}) {
  const meta = useQuery(metaQuery)
  const provider = meta.data?.features.aiProviderLabel || 'the AI service this site uses'
  const [file, setFile] = useState<File | null>(null)
  const [blank, setBlank] = useState(false)
  const fileId = useId()
  const blankId = useId()
  const problem = file ? fileProblem(file) : null
  const ready = !!file && !problem && blank

  const change = (next: boolean) => {
    if (!next) {
      // Ask again every time: the confirmation is about this document.
      setFile(null)
      setBlank(false)
    }
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Start from a paper form</DialogTitle>
          <DialogDescription>
            The AI reads the questions on a blank form and recreates them here. You check the result before anything
            changes.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            if (!ready || !file) return
            onRead(file)
            change(false)
          }}
        >
          <Alert>
            <ShieldAlertIcon />
            <AlertTitle>Only upload blank forms</AlertTitle>
            <AlertDescription>
              The pages are sent to {provider} to read them. Never upload a form someone has filled in: their answers
              would be sent too.
            </AlertDescription>
          </Alert>
          <Field data-invalid={!!problem || undefined}>
            <FieldLabel htmlFor={fileId}>File</FieldLabel>
            <Input
              id={fileId}
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp"
              aria-invalid={!!problem || undefined}
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                setBlank(false)
              }}
            />
            {file && !problem && (
              <FieldDescription>
                <bdi dir="auto">{file.name}</bdi>, {size(file.size)}
              </FieldDescription>
            )}
            <FieldDescription>PDF, JPG, PNG or WebP, up to 20 MB and 10 pages.</FieldDescription>
            {problem && <FieldError>{problem}</FieldError>}
          </Field>
          <Field orientation="horizontal">
            <Checkbox id={blankId} checked={blank} onCheckedChange={(v) => setBlank(v === true)} />
            <FieldContent>
              <FieldLabel htmlFor={blankId} className="font-normal">
                This form is blank. It has no one's answers, names or signatures on it.
              </FieldLabel>
              {!blank && <FieldDescription>Tick this to confirm the form is blank.</FieldDescription>}
            </FieldContent>
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => change(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!ready}>
              Read the form
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
