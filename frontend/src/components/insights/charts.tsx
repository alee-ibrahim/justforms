/**
 * Insights charts (INSIGHTS-SCREENS 3), drawn with the official shadcn Chart (Recharts):
 *
 * - `BarList`: one horizontal bar per answer, the answer's text above its bar and the count
 *   with its share at the end. Answers are form content, so they take the form's language
 *   (Thaana gets its font through `lang`). The chart itself stays left to right like the rest
 *   of the studio.
 * - `Columns`: vertical bars for histograms and months.
 *
 * Bars open the matching submissions (`onPick`). Charts are not keyboard targets: every card
 * also has a table view with buttons (see question-card.tsx).
 */
import { useEffect, useRef, useState } from 'react'
import { Bar, BarChart, Cell, LabelList, XAxis, YAxis } from 'recharts'

import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'

export interface Datum {
  label: string
  count: number
  percent?: number
  /** Muted bar ("Other"). */
  muted?: boolean
  id: string
}

const config = {
  count: { label: 'Submissions', color: 'var(--chart-1)' },
  muted: { label: 'Other', color: 'var(--chart-5)' },
} satisfies ChartConfig

const ROW = 44
const thaana = /[ހ-޿]/

function fit(text: string, width: number): string {
  // About 7px per character at 13px; SVG text has no ellipsis of its own.
  const max = Math.max(8, Math.floor(width / 7))
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

interface LabelProps {
  x?: number | string
  y?: number | string
  width?: number | string
  value?: unknown
  index?: number
}

/** The width of an element, kept up to date. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(320)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

export function BarList({
  data,
  language,
  onPick,
  unit = 'submissions',
}: {
  data: Datum[]
  language: string
  onPick?: (d: Datum) => void
  unit?: string
}) {
  const [ref, width] = useWidth()
  const max = Math.max(1, ...data.map((d) => d.count))
  const NameLabel = ({ x = 0, y = 0, index = 0 }: LabelProps) => {
    const d = data[index]
    if (!d) return null
    const dv = language === 'dv' || thaana.test(d.label)
    return (
      <text
        x={Number(x)}
        y={Number(y) - 6}
        className="fill-foreground text-[13px]"
        lang={dv ? 'dv' : 'en'}
        style={{ unicodeBidi: 'plaintext' }}
      >
        <title>{d.label}</title>
        {fit(d.label, width - 8)}
      </text>
    )
  }
  const ValueLabel = ({ x = 0, y = 0, width = 0, index = 0 }: LabelProps) => {
    const d = data[index]
    if (!d) return null
    return (
      <text
        x={Number(x) + Number(width) + 8}
        y={Number(y) + 10}
        className="fill-muted-foreground text-xs tabular-nums"
      >
        {d.count}
        {d.percent !== undefined ? ` (${d.percent}%)` : ''}
      </text>
    )
  }
  return (
    <div ref={ref} className="w-full">
    <ChartContainer
      config={config}
      className="aspect-auto w-full"
      style={{ height: data.length * ROW + 4 }}
      role="img"
      aria-label={data.map((d) => `${d.label}: ${d.count} ${unit}`).join('; ')}
    >
      <BarChart data={data} layout="vertical" margin={{ top: 18, right: 84, bottom: 0, left: 0 }} barCategoryGap={0}>
        <XAxis type="number" hide domain={[0, max]} />
        <YAxis type="category" dataKey="id" hide />
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              hideIndicator
              labelFormatter={(_v, payload) => (payload?.[0]?.payload as Datum | undefined)?.label ?? ''}
            />
          }
        />
        <Bar
          dataKey="count"
          barSize={12}
          radius={3}
          background={{ fill: 'var(--muted)', radius: 3 }}
          className={onPick ? 'cursor-pointer' : undefined}
          onClick={(entry) => onPick?.(entry.payload as Datum)}
          minPointSize={2}
        >
          {data.map((d) => (
            <Cell key={d.id} fill={d.muted ? 'var(--color-muted)' : 'var(--color-count)'} />
          ))}
          <LabelList dataKey="label" content={NameLabel} />
          <LabelList dataKey="count" content={ValueLabel} />
        </Bar>
      </BarChart>
    </ChartContainer>
    </div>
  )
}

export function Columns({
  data,
  onPick,
  unit = 'submissions',
}: {
  data: Datum[]
  onPick?: (d: Datum) => void
  unit?: string
}) {
  return (
    <ChartContainer
      config={config}
      className="aspect-auto h-44 w-full"
      role="img"
      aria-label={data.map((d) => `${d.label}: ${d.count} ${unit}`).join('; ')}
    >
      <BarChart data={data} margin={{ top: 18, right: 4, bottom: 0, left: 4 }}>
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
          minTickGap={8}
          className="tabular-nums"
        />
        <YAxis hide allowDecimals={false} />
        <ChartTooltip cursor={false} content={<ChartTooltipContent hideIndicator />} />
        <Bar
          dataKey="count"
          radius={3}
          fill="var(--color-count)"
          className={onPick ? 'cursor-pointer' : undefined}
          onClick={(entry) => onPick?.(entry.payload as Datum)}
          minPointSize={2}
        >
          <LabelList dataKey="count" position="top" className="fill-muted-foreground tabular-nums" fontSize={11} />
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}
