/**
 * Settings › AI (INSIGHTS-SCREENS 5): whether "Ask your submissions" may send answers to the
 * AI service. Off by default; owners only; turning it on asks first. The provider is never
 * named in the studio.
 */
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

export function AiCard({ form, canManage }: { form: FormSummary; canManage: boolean }) {
  const patch = usePatchForm(form)
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
          “Ask your submissions” answers questions by counting this form’s submissions and can list answers for you.
          Anyone who can see the submissions can ask.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Field orientation="horizontal">
          <FieldContent>
            <FieldLabel htmlFor="ai-read-answers">Allow AI to read answers</FieldLabel>
            <FieldDescription>
              {on
                ? 'On: answers, including contact details and fields marked sensitive, are sent to the AI service when someone asks a question.'
                : 'Off: the AI service gets the questions and their options, counts, and totals or averages over at least 5 submissions. It never gets a single submission’s answers, text answers or contact details, though a count for a narrow filter can still say something about a few submissions. Lists of answers you ask for are shown only to you.'}{' '}
              Files, signatures and respondents’ IP addresses are never sent.
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
            <AlertDialogTitle>Send answers to the AI service?</AlertDialogTitle>
            <AlertDialogDescription>
              Answers, including contact details and fields marked sensitive, are sent to the AI service when someone
              asks a question (the answers of at most 500 submissions per question). Files, signatures and IP addresses are never sent.
              You can turn this off at any time.
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
