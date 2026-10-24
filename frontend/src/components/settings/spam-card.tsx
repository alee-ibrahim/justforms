/** "Spam protection" (PHASE-4-SCREENS 1.2): the form's CAPTCHA mode. */
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'

import { usePatchForm } from '@/components/forms/use-patch-form'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import type { CaptchaMode, CaptchaProvider, FormSummary } from '@/lib/api'
import { metaQuery } from '@/lib/queries'

const PROVIDERS: Record<Exclude<CaptchaProvider, 'none'>, string> = {
  altcha: 'Uses a proof-of-work check that runs in the browser. No third party is involved.',
  turnstile: 'Uses Cloudflare Turnstile.',
  hcaptcha: 'Uses hCaptcha.',
}

const MODES: { value: CaptchaMode; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'always', label: 'Always' },
  { value: 'auto', label: 'When busy' },
]

export function SpamCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const meta = useQuery(metaQuery)
  const patch = usePatchForm(form)
  const provider = meta.data?.features.captcha ?? 'none'
  return (
    <Card className="rounded-md border shadow-none ring-0">
      <CardHeader>
        <CardTitle>Spam protection</CardTitle>
        <CardDescription>
          {meta.data && provider !== 'none' && `${PROVIDERS[provider]} `}
          Changes apply right away.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!meta.data ? (
          <Skeleton className="h-10" />
        ) : provider === 'none' ? (
          <p className="text-sm text-muted-foreground">
            Spam protection isn't set up on this install. An administrator can turn it on with{' '}
            <code className="font-mono text-xs">JUSTFORMS_CAPTCHA_PROVIDER</code>.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            <RadioGroup
              value={form.captcha}
              disabled={!canManage || patch.isPending}
              aria-label="Spam protection"
              className="flex flex-wrap gap-6"
              onValueChange={(v) =>
                patch.mutate(
                  { captcha: v as CaptchaMode },
                  { onSuccess: () => toast('Saved'), onError: () => toast.error("Couldn't save. Try again.") },
                )
              }
            >
              {MODES.map((m) => (
                <Field key={m.value} orientation="horizontal" className="w-auto">
                  <RadioGroupItem value={m.value} id={`captcha-${m.value}`} />
                  <FieldLabel htmlFor={`captcha-${m.value}`} className="font-normal">
                    {m.label}
                  </FieldLabel>
                </Field>
              ))}
            </RadioGroup>
            <FieldDescription>
              “When busy” turns the check on after {meta.data.features.captchaBusyThreshold.toLocaleString('en')} responses
              in an hour.
            </FieldDescription>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
