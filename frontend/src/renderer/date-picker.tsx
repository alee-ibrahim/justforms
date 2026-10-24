/** Date question on pointer devices: Popover + Calendar (lazy chunk, PHASE-2-SCREENS 4.5). */
import { CalendarIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

import { controlId, useRenderer } from './context'
import type { ControlProps } from './fields'
import { MSG } from './messages'
import { En } from './msg'
import { formatDate, resolveDateBound } from './validation'

const pad = (n: number) => String(n).padStart(2, '0')
const toIso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const fromIso = (s: string) => {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export default function DatePicker({ field, path, invalid, describedBy }: ControlProps) {
  const ctx = useRenderer()
  const [open, setOpen] = useState(false)
  const value = ctx.getValue(path)
  const iso = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null
  const lo = field.type === 'date' ? resolveDateBound(field.minDate) : null
  const hi = field.type === 'date' ? resolveDateBound(field.maxDate) : null
  const disabled = [
    ...(lo ? [{ before: fromIso(lo) }] : []),
    ...(hi ? [{ after: fromIso(hi) }] : []),
  ]
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) ctx.blur(path)
      }}
    >
      <PopoverTrigger asChild>
        <Button
          id={controlId(path)}
          variant="outline"
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={cn(
            'h-12 w-full max-w-64 justify-start border-input text-base font-normal sm:h-11',
            !iso && 'text-muted-foreground',
          )}
        >
          <CalendarIcon />
          <En>{iso ? formatDate(iso) : MSG.pickDate}</En>
        </Button>
      </PopoverTrigger>
      {/* The calendar is system text (English month and day names), so it stays left to right. */}
      <PopoverContent className="w-auto p-0" align="start" lang="en" dir="ltr">
        <Calendar
          mode="single"
          captionLayout="dropdown"
          dir="ltr"
          selected={iso ? fromIso(iso) : undefined}
          defaultMonth={iso ? fromIso(iso) : lo ? fromIso(lo) : undefined}
          disabled={disabled}
          onSelect={(d) => {
            ctx.setValue(path, d ? toIso(d) : undefined)
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
