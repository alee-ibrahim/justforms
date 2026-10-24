/**
 * The AI assistant panel (PHASE-5-SCREENS 3): transcript, suggestion card and composer. It
 * takes the inspector's pane on desktop and sits in a drawer on phones.
 */
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpIcon,
  CheckIcon,
  FileScanIcon,
  MessageSquarePlusIcon,
  RotateCcwIcon,
  SquareIcon,
  TriangleAlertIcon,
  XIcon,
} from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { useBuilder } from '@/components/builder/store'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from '@/components/ui/empty'
import { FieldError } from '@/components/ui/field'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from '@/components/ui/input-group'
import { Item, ItemContent, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { metaQuery } from '@/lib/queries'
import { formLanguage } from '@/schema/language'

import type { AiMessage, Step } from './api'
import { type AiController, errorText, MAX_REQUEST, useAi } from './controller'
import { textLang } from './files'
import { PaperDialog } from './paper-dialog'
import { SuggestionCard } from './suggestion-card'

const CREATE_EXAMPLES = [
  'A volunteer sign-up form with name, phone and availability',
  "A leave request with dates, reason and a manager's email",
  'An event feedback form with a 1 to 5 rating',
]
const EDIT_EXAMPLES = ['Add a phone number question', 'Make every question on page 1 required', 'Split this into two pages']

function StepRow({ step, language }: { step: Step; language: string }) {
  if (step.tool === 'get_form') return null
  if (!step.ok)
    return (
      <Item size="sm" className="py-1 text-muted-foreground" title={step.error}>
        <ItemMedia>
          <RotateCcwIcon className="size-4" />
        </ItemMedia>
        <ItemContent>
          <ItemTitle className="font-normal">Fixed a step the form didn't accept</ItemTitle>
        </ItemContent>
      </Item>
    )
  return (
    <Item size="sm" className="py-1">
      <ItemMedia>
        <CheckIcon className="size-4 text-muted-foreground" />
      </ItemMedia>
      <ItemContent className="min-w-0">
        <ItemTitle className="block w-full min-w-0 truncate font-normal">
          {step.action}
          {step.label && (
            <>
              {' '}
              “<bdi dir="auto" lang={textLang(step.label, language)}>
                {step.label}
              </bdi>
              ”
            </>
          )}
        </ItemTitle>
      </ItemContent>
    </Item>
  )
}

function Steps({ steps, language }: { steps: Step[]; language: string }) {
  if (!steps.some((s) => s.tool !== 'get_form')) return null
  return (
    <ItemGroup className="-mx-3 gap-0">
      {steps.map((s, i) => (
        <StepRow key={i} step={s} language={language} />
      ))}
    </ItemGroup>
  )
}

function Request({ text, file }: { text: string; file?: { name: string; pages?: number } }) {
  if (file)
    return (
      <p className="flex items-center gap-2 self-start rounded-lg bg-secondary px-3 py-2 text-sm">
        <FileScanIcon className="size-4 shrink-0" />
        <span className="min-w-0">
          Read <bdi dir="auto">{file.name || 'the uploaded form'}</bdi>
          {file.pages ? ` (${file.pages} page${file.pages === 1 ? '' : 's'})` : ''}
        </span>
      </p>
    )
  return (
    <p className="self-start whitespace-pre-wrap rounded-lg bg-secondary px-3 py-2 text-sm" dir="auto">
      <span className="sr-only">You said: </span>
      {text}
    </p>
  )
}

function Message({
  ai,
  msg,
  last,
  language,
}: {
  ai: AiController
  msg: AiMessage
  last: boolean
  language: string
}) {
  const c = msg.content
  if (msg.role === 'user') return <Request text={c.text ?? ''} file={c.attachment} />
  if (msg.role === 'status')
    return <p className="text-sm text-muted-foreground">{c.status === 'applied' ? 'Applied.' : 'Discarded.'}</p>
  return (
    <div className="flex flex-col gap-2">
      <Steps steps={c.steps ?? []} language={language} />
      {c.status === 'ok' && c.text && (
        <p className="whitespace-pre-wrap text-sm" dir="auto">
          {c.text}
        </p>
      )}
      {c.status === 'ok' && !c.changed && !c.text && <p className="text-sm text-muted-foreground">No changes.</p>}
      {c.status === 'cancelled' && (
        <p className="text-sm text-muted-foreground">Stopped. Nothing from this request was kept.</p>
      )}
      {c.status === 'filled_in' && (
        <Alert>
          <TriangleAlertIcon />
          <AlertDescription>
            This looks like a filled-in form, so nothing was added. Upload a blank copy.
          </AlertDescription>
        </Alert>
      )}
      {c.status === 'error' && (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertDescription className="flex flex-col items-start gap-2">
            {errorText({ code: c.error ?? '' })}
            {last && (
              <Button size="sm" variant="outline" onClick={() => ai.retry()}>
                Try again
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}

function EmptyChat({ ai, onPaper }: { ai: AiController; onPaper: () => void }) {
  const meta = useQuery(metaQuery)
  const schema = useBuilder((s) => s.schema)
  const empty = schema.pages.every((p) => !(p.elements ?? []).length)
  const language = formLanguage(schema)
  return (
    <Empty className="gap-4 p-4">
      <EmptyHeader>
        <EmptyTitle>{empty ? 'Describe your form' : 'Ask for a change'}</EmptyTitle>
        <EmptyDescription>
          {empty
            ? 'Say who fills it in and what you need to know. The AI drafts the questions; you check them before anything changes.'
            : 'For example: add a phone question after email, or show page 2 only to people who answered Yes.'}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent className="gap-2">
        {(empty ? CREATE_EXAMPLES : EDIT_EXAMPLES).map((text) => (
          <Button
            key={text}
            variant="outline"
            size="sm"
            className="h-auto w-full justify-start whitespace-normal py-1.5 text-start font-normal"
            onClick={() => {
              ai.setComposer(text)
              document.getElementById('ai-composer')?.focus()
            }}
          >
            {text}
          </Button>
        ))}
        {meta.data?.features.aiVision && (
          <div className="mt-2 flex w-full flex-col items-start gap-1 border-t pt-4">
            <Button variant="outline" size="sm" onClick={onPaper}>
              <FileScanIcon />
              Start from a paper form
            </Button>
            <p className="text-start text-xs text-muted-foreground">
              Upload a blank PDF or photo; the AI recreates the questions.
            </p>
          </div>
        )}
        {language === 'dv' && (
          <p className="mt-2 text-start text-xs text-muted-foreground">
            This form is in Dhivehi. The AI writes in Dhivehi; check the wording before you publish.
          </p>
        )}
      </EmptyContent>
    </Empty>
  )
}

function Composer({ ai }: { ai: AiController }) {
  const text = useAi(ai, (s) => s.composer)
  const busy = useAi(ai, (s) => s.busy)
  const sending = busy === 'sending'
  const offline = useBuilder((s) => s.status === 'offline' || s.status === 'error')
  const schema = useBuilder((s) => s.schema)
  const empty = schema.pages.every((p) => !(p.elements ?? []).length)
  const tooLong = text.length > MAX_REQUEST
  const reason = sending
    ? 'Wait for the AI to finish, or stop it'
    : offline
      ? 'Reconnect to save your changes first'
      : tooLong
        ? 'Keep requests under 4,000 characters'
        : null
  const canSend = !reason && !busy && text.trim().length > 0
  return (
    <div className="flex flex-col gap-1">
      <InputGroup>
        <InputGroupTextarea
          id="ai-composer"
          aria-label="Request to the AI assistant"
          placeholder={empty ? 'Describe your form…' : 'Ask for a change…'}
          dir="auto"
          rows={2}
          className="max-h-48 min-h-14"
          value={text}
          aria-invalid={tooLong || undefined}
          onChange={(e) => ai.setComposer(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              if (canSend) ai.send(text)
            } else if (e.key === 'Escape' && sending) {
              e.preventDefault()
              ai.stop()
            }
          }}
        />
        <InputGroupAddon align="block-end" className="justify-end">
          {sending ? (
            <InputGroupButton variant="outline" size="sm" onClick={() => ai.stop()}>
              <SquareIcon />
              Stop
            </InputGroupButton>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <InputGroupButton
                  variant="default"
                  size="icon-sm"
                  aria-label="Send (Enter)"
                  // aria-disabled, not disabled: a disabled button greys out the whole input group
                  // and can't show why in its tooltip.
                  aria-disabled={!canSend}
                  className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
                  onClick={() => canSend && ai.send(text)}
                >
                  <ArrowUpIcon />
                </InputGroupButton>
              </TooltipTrigger>
              <TooltipContent>{reason ?? 'Send (Enter)'}</TooltipContent>
            </Tooltip>
          )}
        </InputGroupAddon>
      </InputGroup>
      {tooLong && <FieldError>Keep requests under 4,000 characters.</FieldError>}
    </div>
  )
}

export function AiPanel({
  ai,
  onClose,
  onPreview,
  headerless = false,
}: {
  ai: AiController
  onClose: () => void
  onPreview?: () => void
  /** Phones: the drawer supplies the title. */
  headerless?: boolean
}) {
  const session = useAi(ai, (s) => s.session)
  const loading = useAi(ai, (s) => s.loading)
  const live = useAi(ai, (s) => s.live)
  const error = useAi(ai, (s) => s.error)
  const language = useBuilder((s) => formLanguage(s.schema))
  const [paper, setPaper] = useState(false)
  const vision = !!useQuery(metaQuery).data?.features.aiVision
  const viewport = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  const messages = session?.messages ?? []
  const proposal = session?.proposal ?? null

  useEffect(() => {
    document.getElementById('ai-composer')?.focus()
  }, [])

  // Follow new content unless the person scrolled up.
  useLayoutEffect(() => {
    const el = viewport.current?.querySelector<HTMLElement>('[data-slot=scroll-area-viewport]')
    if (el && stick.current) el.scrollTop = el.scrollHeight
  })

  return (
    <aside aria-label="AI assistant" className="flex h-full min-h-0 flex-col bg-card">
      <div className="flex items-center gap-1 border-b px-3 py-2">
        {!headerless && <h2 className="me-auto text-base font-medium">AI assistant</h2>}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className={headerless ? 'me-auto' : undefined}
              disabled={!!live || !messages.length}
              onClick={() => void ai.newChat()}
            >
              <MessageSquarePlusIcon />
              New chat
            </Button>
          </TooltipTrigger>
          <TooltipContent>Start over; the form keeps its changes</TooltipContent>
        </Tooltip>
        {vision && messages.length > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Start from a paper form"
                disabled={!!live}
                onClick={() => setPaper(true)}
              >
                <FileScanIcon />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Start from a paper form</TooltipContent>
          </Tooltip>
        )}
        {!headerless && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Close AI assistant" onClick={onClose}>
                <XIcon />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Close AI assistant</TooltipContent>
          </Tooltip>
        )}
      </div>
      <div ref={viewport} className="min-h-0 flex-1">
        <ScrollArea
          className="h-full [&_[data-slot=scroll-area-viewport]>div]:block!"
          onScrollCapture={(e) => {
            const el = e.target as HTMLElement
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
          }}
        >
          <div role="log" aria-live="polite" aria-busy={!!live} className="flex flex-col gap-4 p-3">
            {loading && !session ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Spinner />
                Opening the assistant…
              </div>
            ) : messages.length === 0 && !live ? (
              <EmptyChat ai={ai} onPaper={() => setPaper(true)} />
            ) : (
              messages.map((m, i) => (
                <Message
                  key={m.id}
                  ai={ai}
                  msg={m}
                  language={language}
                  last={!live && i === messages.length - 1}
                />
              ))
            )}
            {live && (
              <div className="flex flex-col gap-2">
                <Request text={live.text} file={live.file} />
                <Steps steps={live.steps} language={language} />
                {live.reply && (
                  <p className="whitespace-pre-wrap text-sm" dir="auto">
                    {live.reply}
                  </p>
                )}
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Spinner />
                  Working on it…
                </p>
              </div>
            )}
            {error && (
              <Alert variant="destructive">
                <TriangleAlertIcon />
                <AlertDescription className="flex flex-col items-start gap-2">
                  {errorText(error)}
                  {['provider_unavailable', 'network', 'http_502', 'http_504'].includes(error.code) && (
                    <Button size="sm" variant="outline" onClick={() => ai.retry()}>
                      Try again
                    </Button>
                  )}
                </AlertDescription>
              </Alert>
            )}
            {proposal && !live && <SuggestionCard ai={ai} proposal={proposal} onPreview={onPreview} />}
          </div>
        </ScrollArea>
      </div>
      <div className="flex flex-col gap-2 border-t p-3">
        <Composer ai={ai} />
        <p className="text-xs text-muted-foreground">
          The AI sees this form's questions, never its responses. Nothing changes until you apply it.
        </p>
      </div>
      <PaperDialog open={paper} onOpenChange={setPaper} onRead={(file) => ai.importFile(file)} />
    </aside>
  )
}
