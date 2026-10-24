/** The status line under an address input (docs/ux/FORM-THEME-SCREENS.md 1.2). */
import { CheckIcon, CircleAlertIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { FieldDescription, FieldError } from '@/components/ui/field'
import { Spinner } from '@/components/ui/spinner'
import type { SlugCheck } from '@/lib/api'

const PROBLEMS: Record<NonNullable<SlugCheck['problem']>, string> = {
  invalid: 'Use lower-case letters, digits and hyphens, like youth-app.',
  reserved: 'This address is used by JustForms itself. Try another.',
  taken: 'Another form already uses this address.',
}

/** The status line under an address input: checking, available, or what is wrong. */
export function SlugStatus({
  checking,
  result,
  onSuggestion,
}: {
  checking: boolean
  result: SlugCheck | null
  onSuggestion?: (slug: string) => void
}) {
  return (
    <div aria-live="polite" className="min-h-5">
      {checking ? (
        <FieldDescription className="flex items-center gap-1.5">
          <Spinner className="size-3.5" />
          Checking…
        </FieldDescription>
      ) : result?.available ? (
        <FieldDescription className="flex items-center gap-1.5 text-foreground">
          <CheckIcon className="size-4" aria-hidden />
          Available
        </FieldDescription>
      ) : result?.problem ? (
        <FieldError className="flex flex-wrap items-center gap-x-1.5">
          <CircleAlertIcon className="size-4 shrink-0" aria-hidden />
          {PROBLEMS[result.problem]}
          {result.suggestion && onSuggestion && (
            <Button
              type="button"
              variant="link"
              size="sm"
              className="h-auto p-0 font-normal"
              onClick={() => onSuggestion(result.suggestion!)}
            >
              Try <bdi dir="ltr">{result.suggestion}</bdi>
            </Button>
          )}
        </FieldError>
      ) : null}
    </div>
  )
}

