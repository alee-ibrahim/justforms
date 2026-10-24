/**
 * Thaana text input (Dhivehi forms): the input with the "ތ / A" phonetic keyboard toggle at its
 * end edge. A lazy chunk: forms in English never load it.
 */
import { useEffect, useRef, useState } from 'react'

import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupTextarea } from '@/components/ui/input-group'
import { Toggle } from '@/components/ui/toggle'
import { toggleOn } from '@/lib/toggle'

import { MSG } from './messages'

export default function ThaanaInput({
  common,
  long,
  rows,
  canvas,
}: {
  /** The text control's shared props (id, value, handlers, aria). */
  common: React.ComponentProps<'input'> & React.ComponentProps<'textarea'>
  long: boolean
  rows: number
  canvas: boolean
}) {
  const [thaana, setThaana] = useState(true)
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!thaana || canvas) return
    let detach: (() => void) | undefined
    let cancelled = false
    void import('@/thaana/phonetic').then((m) => {
      if (!cancelled && ref.current) detach = m.attachPhonetic(ref.current)
    })
    return () => {
      cancelled = true
      detach?.()
    }
  }, [thaana, canvas])

  return (
    <InputGroup className={long ? undefined : 'h-12 sm:h-11'}>
      {long ? (
        <InputGroupTextarea {...common} ref={ref} rows={rows} className="min-h-28 text-base md:text-base" />
      ) : (
        <InputGroupInput {...common} ref={ref} className="text-base md:text-base" />
      )}
      <InputGroupAddon align={long ? 'block-end' : 'inline-end'}>
        <Toggle size="sm" pressed={thaana} onPressedChange={setThaana} aria-label={MSG.thaanaKeyboard} className={toggleOn}>
          <bdi dir="ltr">ތ / A</bdi>
        </Toggle>
      </InputGroupAddon>
    </InputGroup>
  )
}
