/**
 * Share page: a Dhivehi form still at a generic address (`form`, `form-3`, from before titles
 * were romanised) is offered one made from its title. The old address keeps redirecting.
 */
import { LanguagesIcon } from 'lucide-react'
import { toast } from 'sonner'

import { useSlugCheck } from '@/components/forms/slug'
import { usePatchForm } from '@/components/forms/use-patch-form'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import type { FormSummary } from '@/lib/api'

export function ReadableAddress({ form, suggested }: { form: FormSummary; suggested: string }) {
  const patch = usePatchForm(form)
  const { result } = useSlugCheck(suggested, form.id, true)
  // Taken by another form: the API's free variant (kandi-2).
  const slug = result ? (result.available ? suggested : result.suggestion) : null
  if (!slug) return null
  return (
    <Alert role="status">
      <LanguagesIcon aria-hidden />
      <AlertTitle>Use a readable address</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        <span>
          Its address isn't made from its Dhivehi title. Use one in Latin letters that says what the form is.
          The old address keeps working and redirects to the new one.
        </span>
        <Button
          variant="outline"
          className="h-auto max-w-full py-2 text-start whitespace-normal max-sm:w-full"
          disabled={patch.isPending}
          onClick={() =>
            patch.mutate(
              { slug },
              {
                onSuccess: () => toast(`Changed the address. /${form.slug} still leads here.`),
                onError: () => toast.error("Couldn't change the address. Try again."),
              },
            )
          }
        >
          {patch.isPending && <Spinner />}
          <span className="min-w-0 break-all">
            Use <bdi dir="ltr" className="font-mono">/{slug}</bdi>
          </span>
        </Button>
      </AlertDescription>
    </Alert>
  )
}
