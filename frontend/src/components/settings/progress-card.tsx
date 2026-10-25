/** "Saved progress" (SAVED-PROGRESS-SCREENS 3): keep respondents' answers on their device. */
import { toast } from 'sonner'

import { usePatchForm } from '@/components/forms/use-patch-form'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Switch } from '@/components/ui/switch'
import type { FormSummary } from '@/lib/api'

const DAYS = [1, 3, 7, 14, 30]

export function ProgressCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const patch = usePatchForm(form)
  const options = { onSuccess: () => toast('Saved'), onError: () => toast.error("Couldn't save. Try again.") }
  const days = DAYS.includes(form.saveProgressDays) ? DAYS : [...DAYS, form.saveProgressDays].sort((a, b) => a - b)
  return (
    <Card className="rounded-md border shadow-none ring-0">
      <CardHeader>
        <CardTitle>Saved progress</CardTitle>
        <CardDescription>Changes apply right away.</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-5">
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor="save-progress">Save progress on this device</FieldLabel>
              <FieldDescription>
                Answers are kept in the respondent's browser so they can close the page and carry on later. They stay on
                that device and browser only and are not synced. Files, signatures and sensitive answers are never kept.
                Turn this off for forms filled in on shared or kiosk devices.
              </FieldDescription>
            </FieldContent>
            <Switch
              id="save-progress"
              checked={form.saveProgress}
              disabled={!canManage || patch.isPending}
              onCheckedChange={(on) => patch.mutate({ saveProgress: on }, options)}
            />
          </Field>
          {form.saveProgress && (
            <Field>
              <FieldLabel htmlFor="save-progress-days">Keep saved progress for</FieldLabel>
              <NativeSelect
                id="save-progress-days"
                className="w-full sm:w-48"
                value={String(form.saveProgressDays)}
                disabled={!canManage || patch.isPending}
                onChange={(e) => patch.mutate({ saveProgressDays: Number(e.target.value) }, options)}
              >
                {days.map((d) => (
                  <NativeSelectOption key={d} value={d}>
                    {d === 1 ? '1 day' : `${d} days`}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
              <FieldDescription>Counted from the last change. Submitting the form clears it.</FieldDescription>
            </Field>
          )}
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
