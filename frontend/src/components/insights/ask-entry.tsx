/**
 * The Insights page's way into "Ask your submissions" (INSIGHTS-SCREENS 4): a short card with
 * questions built from the form and a question box that opens the panel. Hidden while the
 * panel is open.
 */
import { MessageSquareTextIcon, SparklesIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { Form } from '@/schema'

import { askExamples } from './ask-examples'
import { useAsk } from './ask-state'

export function AskEntry({ schema, language }: { schema: Form | undefined; language: string }) {
  const ask = useAsk()
  if (!ask?.available || ask.open) return null
  const ideas = askExamples(schema, false, 3)
  return (
    <Card className="min-w-0 gap-3 rounded-md border shadow-none ring-0" aria-labelledby="ask-entry-title">
      <CardHeader>
        <CardTitle id="ask-entry-title" className="flex items-center gap-2 text-base">
          <SparklesIcon className="size-4 text-muted-foreground" aria-hidden />
          Ask your submissions
        </CardTitle>
        <CardDescription>Ask in your own words. Answers are counted from the submissions and link to them.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Button
          variant="outline"
          className="h-11 w-full justify-start font-normal text-muted-foreground"
          onClick={() => ask.setOpen(true)}
        >
          <MessageSquareTextIcon />
          Ask a question about the submissions…
        </Button>
        {ideas.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">Try asking</span>
            {ideas.map((idea) => (
              <Button
                key={idea}
                variant="secondary"
                size="sm"
                className="h-auto max-w-full py-1.5 text-start font-normal whitespace-normal"
                onClick={() => ask.ask(idea)}
              >
                <bdi dir="auto" lang={/[ހ-޿]/.test(idea) ? 'dv' : language}>
                  {idea}
                </bdi>
              </Button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
