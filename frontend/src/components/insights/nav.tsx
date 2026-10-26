/**
 * Responses / Insights switch under the Submissions heading, and the filter chip for
 * conditions that came from an Insights bar or an AI answer (INSIGHTS-SCREENS 1, 2.4).
 */
import { useNavigate } from '@tanstack/react-router'
import { XIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { SubmissionsSearch } from '@/components/submissions/search'

export function SubmissionsTabs({
  formId,
  current,
  search,
}: {
  formId: string
  current: 'responses' | 'insights'
  search: SubmissionsSearch
}) {
  const navigate = useNavigate()
  const go = (to: string) => {
    if (to === current) return
    void navigate({
      to: to === 'insights' ? '/forms/$formId/submissions/insights' : '/forms/$formId/submissions',
      params: { formId },
      search,
    } as never)
  }
  return (
    <Tabs value={current} onValueChange={go}>
      <TabsList variant="line" aria-label="Submissions view">
        <TabsTrigger value="responses">Responses</TabsTrigger>
        <TabsTrigger value="insights">Insights</TabsTrigger>
      </TabsList>
    </Tabs>
  )
}

export function ConditionChip({ label, onRemove }: { label?: string; onRemove: () => void }) {
  const text = label || 'Matching an answer'
  return (
    <Badge variant="outline" className="h-auto min-h-7 max-w-full gap-1 pe-0.5 text-sm font-normal whitespace-normal">
      <bdi dir="auto" className="min-w-0 py-0.5">
        {text}
      </bdi>
      <Button
        variant="ghost"
        size="icon-xs"
        className="shrink-0 rounded-full"
        aria-label={`Remove filter: ${text}`}
        onClick={onRemove}
      >
        <XIcon />
      </Button>
    </Badge>
  )
}
