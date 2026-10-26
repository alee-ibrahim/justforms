/**
 * Settings › AI (INSIGHTS-SCREENS 5): whether "Ask your submissions" may send the text of
 * answers to the AI provider. Off by default; owners only; turning it on asks first.
 */
import { useQuery } from '@tanstack/react-query'
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldContent, FieldDescription, FieldLabel } from '@/components/ui/field'
import { Switch } from '@/components/ui/switch'
import type { FormSummary } from '@/lib/api'
import { metaQuery } from '@/lib/queries'

export function AiCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const patch = usePatchForm(form)
  const provider = useQuery(metaQuery).data?.features.aiProviderLabel || 'the AI service this site uses'
  const on = !!form.aiReadAnswers
  const [confirm, setConfirm] = useState(false)
  const save = (value: boolean) =>
    patch.mutate(
      { aiReadAnswers: value },
      {
        onSuccess: () => toast(value ? 'AI can read answers' : 'AI no longer reads answers'),
        onError: () => toast.error("Couldn't save. Try again."),
      },
    )
  return (
    <Card className="rounded-md border shadow-none ring-0">
      <CardHeader>
        <CardTitle>AI</CardTitle>
        <CardDescription>
          “Ask your submissions” on the Insights page answers questions by counting this form’s submissions. Anyone who
          can see the submissions can ask.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor="ai-read-answers">Allow AI to read answers</FieldLabel>
            <FieldDescription>
              {on
                ? `On: to summarise answers or find themes, the text of answers is sent to ${provider}.`
                : `Off: ${provider} only gets the questions, counts and numbers, never the text of answers.`}{' '}
              Sensitive questions, files, signatures, email addresses, phone numbers and respondents’ IP addresses are
              never sent.
            </FieldDescription>
          </FieldContent>
          <Switch
            id="ai-read-answers"
            checked={on}
            disabled={!canManage || patch.isPending}
            onCheckedChange={(next) => (next ? setConfirm(true) : save(false))}
          />
        </Field>
      </CardContent>
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Send answers to {provider}?</AlertDialogTitle>
            <AlertDialogDescription>
              When someone asks for a summary, the text of up to 200 submissions’ answers goes to {provider}. Sensitive
              questions, files, signatures, email addresses, phone numbers and IP addresses are never sent. You can turn
              this off at any time.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => save(true)}>Allow AI to read answers</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
