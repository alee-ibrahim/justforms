/** "Data retention" (PHASE-4-SCREENS 1.5): erase submissions N days after they arrive. */
import { useState } from 'react'
import { toast } from 'sonner'

import { usePatchForm } from '@/components/forms/use-patch-form'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldContent, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@/components/ui/input-group'
import { Switch } from '@/components/ui/switch'
import type { FormSummary } from '@/lib/api'

const DEFAULT_DAYS = 365

export function RetentionCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const patch = usePatchForm(form)
  const current = form.retentionDays
  const [on, setOn] = useState(current !== null)
  const [days, setDays] = useState(String(current ?? DEFAULT_DAYS))
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<number | null>(null)

  const apply = (value: number) =>
    patch.mutate(
      { retentionDays: value },
      {
        onSuccess: () => toast(value ? `Retention set to ${value} days` : 'Submissions are kept until deleted'),
        onError: () => toast.error("Couldn't save. Try again."),
      },
    )
  const save = () => {
    const n = Number(days)
    if (!/^\d+$/.test(days.trim()) || n < 1 || n > 36500) return setError('Enter a number of days from 1 to 36500')
    setError(null)
    if (n === current) return
    // Turning retention on, or shortening it, can erase submissions tonight: ask first.
    if (current === null || n < current) setConfirm(n)
    else apply(n)
  }

  return (
    <Card className="rounded-md border shadow-none ring-0">
      <CardHeader>
        <CardTitle>Data retention</CardTitle>
        <CardDescription>
          Turning this off applies right away. A new number of days saves when you choose Save.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-4">
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor="retention-on">Erase submissions automatically</FieldLabel>
              <FieldDescription>
                {current === null
                  ? 'Off: submissions are kept until someone deletes them.'
                  : `Submissions are erased ${current} days after they arrive.`}
              </FieldDescription>
            </FieldContent>
            <Switch
              id="retention-on"
              checked={on}
              disabled={!canManage || patch.isPending}
              onCheckedChange={(next) => {
                setOn(next)
                setError(null)
                if (!next && current !== null) apply(0)
              }}
            />
          </Field>
          {on && (
            <Field data-invalid={error ? true : undefined} className="ps-4">
              <FieldLabel htmlFor="retention-days">After</FieldLabel>
              <div className="flex flex-wrap items-center gap-2">
                <InputGroup className="w-40">
                  <InputGroupInput
                    id="retention-days"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={36500}
                    value={days}
                    disabled={!canManage}
                    aria-invalid={error ? true : undefined}
                    className="tabular-nums"
                    onChange={(e) => setDays(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && save()}
                  />
                  <InputGroupAddon align="inline-end">
                    <InputGroupText>days</InputGroupText>
                  </InputGroupAddon>
                </InputGroup>
                <Button variant="outline" disabled={!canManage || patch.isPending} onClick={save}>
                  Save
                </Button>
              </div>
              <FieldDescription>
                Submissions, their files, signatures and PDFs are erased for good this many days after they arrive. The
                nightly clean-up does this.
              </FieldDescription>
              {error && <FieldError>{error}</FieldError>}
            </Field>
          )}
        </FieldGroup>
      </CardContent>
      <AlertDialog open={confirm !== null} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Erase older submissions?</AlertDialogTitle>
            <AlertDialogDescription>
              Submissions older than {confirm} days will be erased tonight, with their files, signatures and PDFs. This
              can't be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => confirm !== null && apply(confirm)}>
              Erase after {confirm} days
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
