/** "Who can fill in this form" (PHASE-4-SCREENS 1.1): access mode and email-code options. */
import { useState } from 'react'
import { toast } from 'sonner'

import { usePatchForm } from '@/components/forms/use-patch-form'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Switch } from '@/components/ui/switch'
import type { AccessMode, FormSummary } from '@/lib/api'

const OPTIONS: { value: AccessMode; label: string; description: string }[] = [
  {
    value: 'public',
    label: 'Anyone with the link',
    description: 'No sign-in. Turn on spam protection if you expect abuse.',
  },
  {
    value: 'otp',
    label: 'People who confirm their email',
    description: 'They get a 6-digit code by email before they see the form. Their address is saved with the response.',
  },
  {
    value: 'staff',
    label: 'Signed-in staff only',
    description: "Only signed-in people in this form's organisation can respond.",
  },
]

const DOMAIN = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/

export function RespondentsCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const patch = usePatchForm(form)
  const [domains, setDomains] = useState(form.otpAllowedDomains.join(', '))
  const [domainError, setDomainError] = useState<string | null>(null)
  const saved = (message = 'Saved') => () => toast(message)
  const failed = () => toast.error("Couldn't save. Try again.")

  return (
    <Card className="rounded-md border shadow-none ring-0">
      <CardHeader>
        <CardTitle>Who can fill in this form</CardTitle>
        <CardDescription>
          Changes apply right away.
          {form.status === 'live' && ' People who already opened the form need to reload it after a change.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <RadioGroup
          value={form.accessMode}
          disabled={!canManage || patch.isPending}
          aria-label="Who can fill in this form"
          onValueChange={(v) => patch.mutate({ accessMode: v as AccessMode }, { onSuccess: saved(), onError: failed })}
          className="gap-4"
        >
          {OPTIONS.map((o) => (
            <div key={o.value} className="flex flex-col gap-3">
              <Field orientation="horizontal">
                <RadioGroupItem value={o.value} id={`access-${o.value}`} />
                <FieldContent>
                  <FieldLabel htmlFor={`access-${o.value}`} className="font-normal">
                    {o.label}
                  </FieldLabel>
                  <FieldDescription>{o.description}</FieldDescription>
                </FieldContent>
              </Field>
              {o.value === 'otp' && form.accessMode === 'otp' && (
                <FieldGroup className="gap-4 ps-7">
                  <Field data-invalid={domainError ? true : undefined}>
                    <FieldLabel htmlFor="otp-domains">Allowed email domains</FieldLabel>
                    <Input
                      id="otp-domains"
                      dir="ltr"
                      placeholder="example.org, example.com"
                      value={domains}
                      disabled={!canManage}
                      aria-invalid={domainError ? true : undefined}
                      onChange={(e) => setDomains(e.target.value)}
                      onBlur={() => {
                        const list = domains
                          .split(',')
                          .map((d) => d.trim().toLowerCase().replace(/^@/, ''))
                          .filter(Boolean)
                        if (list.some((d) => !DOMAIN.test(d)))
                          return setDomainError('Enter domains like example.org, separated by commas')
                        setDomainError(null)
                        if (list.join(',') !== form.otpAllowedDomains.join(','))
                          patch.mutate({ otpAllowedDomains: list }, { onSuccess: saved(), onError: failed })
                      }}
                    />
                    <FieldDescription>Leave empty to allow any address.</FieldDescription>
                    {domainError && <FieldError>{domainError}</FieldError>}
                  </Field>
                  <Field orientation="horizontal">
                    <FieldContent>
                      <FieldLabel htmlFor="otp-one">One response per email</FieldLabel>
                      <FieldDescription>A second response from the same address is refused.</FieldDescription>
                    </FieldContent>
                    <Switch
                      id="otp-one"
                      checked={form.otpOneResponse}
                      disabled={!canManage || patch.isPending}
                      onCheckedChange={(on) => patch.mutate({ otpOneResponse: on }, { onSuccess: saved(), onError: failed })}
                    />
                  </Field>
                </FieldGroup>
              )}
            </div>
          ))}
        </RadioGroup>
      </CardContent>
    </Card>
  )
}
