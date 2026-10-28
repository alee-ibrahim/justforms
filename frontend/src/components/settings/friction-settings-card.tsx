/** "Where people get stuck" (docs/ux/ID-NUMBER-AND-FRICTION-SCREENS.md 3): anonymous counters. */
import { toast } from 'sonner'

import { usePatchForm } from '@/components/forms/use-patch-form'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldContent, FieldDescription, FieldLabel } from '@/components/ui/field'
import { Switch } from '@/components/ui/switch'
import type { FormSummary } from '@/lib/api'

export function FrictionSettingsCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const patch = usePatchForm(form)
  return (
    <Card className="rounded-md border shadow-none ring-0">
      <CardHeader>
        <CardTitle>Where people get stuck</CardTitle>
        <CardDescription>Changes apply right away.</CardDescription>
      </CardHeader>
      <CardContent>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor="friction-insights">Count where people get stuck</FieldLabel>
            <FieldDescription>
              The form counts which pages people reach and which questions show them a problem (for example a wrong
              format), so Insights can show where they give up. Only counts are kept: never answers, and nothing that
              identifies anyone. No cookies are used.
            </FieldDescription>
          </FieldContent>
          <Switch
            id="friction-insights"
            checked={form.frictionInsights !== false}
            disabled={!canManage || patch.isPending}
            onCheckedChange={(on) =>
              patch.mutate(
                { frictionInsights: on },
                { onSuccess: () => toast('Saved'), onError: () => toast.error("Couldn't save. Try again.") },
              )
            }
          />
        </Field>
      </CardContent>
    </Card>
  )
}
