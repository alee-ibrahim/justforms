/**
 * The success and status (closed / not found / error) screens of the respondent's form. A lazy
 * chunk of the public form (form-view.tsx), so the first page loads less JavaScript.
 */
import { CheckIcon, CopyIcon, InfoIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import type { Form } from '@/schema'

import { MSG as msgs } from './messages'
import { En } from './msg'

export function SuccessScreen({
  form,
  reference,
  onAnother,
}: {
  form: Form
  reference: string
  onAnother?: () => void
}) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex flex-col gap-6">
      <CheckIcon className="size-8 text-primary" aria-hidden />
      <h1 className="text-2xl font-bold" tabIndex={-1} ref={(el) => el?.focus()}>
        {form.settings.successMessage?.trim() || <En>{msgs.successDefault}</En>}
      </h1>
      <div className="flex flex-col items-center gap-1 rounded-md border bg-background py-6 text-center">
        <p className="text-sm text-muted-foreground">
          <En>{msgs.yourReference}</En>
        </p>
        <p className="text-3xl font-bold tabular-nums animate-stamp motion-reduce:animate-none">
          <bdi dir="ltr">{reference}</bdi>
        </p>
        <Button
          type="button"
          variant="ghost"
          className="mt-2 h-11"
          onClick={() => {
            void navigator.clipboard?.writeText(reference).then(() => {
              setCopied(true)
              window.setTimeout(() => setCopied(false), 2000)
            })
          }}
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
          <En>{copied ? msgs.copied : msgs.copyReference}</En>
        </Button>
        <span className="sr-only" aria-live="polite" lang="en">
          {copied ? msgs.copied : ''}
        </span>
      </div>
      {onAnother && (
        <Button type="button" variant="outline" className="h-12 self-start text-base" onClick={onAnother}>
          <En>{msgs.submitAnother}</En>
        </Button>
      )}
    </div>
  )
}

/** A closed / not found / error screen. Title and body are system text (English). */
export function StatusScreen({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: ReactNode
}) {
  return (
    <Empty className="flex-none items-start justify-start p-0 text-start">
      <EmptyHeader className="items-start">
        <EmptyMedia variant="icon">
          <InfoIcon />
        </EmptyMedia>
        <EmptyTitle className="text-xl font-semibold">
          <En>{title}</En>
        </EmptyTitle>
        <EmptyDescription className="text-base">
          <En>{body}</En>
        </EmptyDescription>
      </EmptyHeader>
      {action && <EmptyContent className="items-start">{action}</EmptyContent>}
    </Empty>
  )
}
