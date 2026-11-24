/**
 * Inputs for form text in the studio. Form text may be English, Dhivehi or both, so every
 * input follows what is typed (first strong character: Thaana right to left, Latin left to
 * right) and offers the "ތ / A" phonetic Thaana keyboard toggle (@yashau/thaana, attached to the
 * official shadcn Input/Textarea). The keyboard starts on when the text is Dhivehi, or when the
 * box is empty and its block reads right to left (`dir`).
 */
import { mergeRefs, useThaanaKeyboard } from '@/thaana/keyboard'
import { type ComponentProps } from 'react'

import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupTextarea,
} from '@/components/ui/input-group'
import { Toggle } from '@/components/ui/toggle'
import { toggleOn } from '@/lib/toggle'
import type { TextDirection } from '@/schema/direction'

import { useContentTyping } from './content-typing'

export function ThaanaToggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <Toggle
      size="sm"
      pressed={on}
      onPressedChange={onChange}
      // Keep the caret in the text: pressing the toggle mustn't blur (commit) it.
      onPointerDown={(e) => e.preventDefault()}
      onMouseDown={(e) => e.preventDefault()}
      aria-label="Thaana keyboard"
      title="Thaana keyboard"
      className={toggleOn}
    >
      <bdi dir="ltr">ތ / A</bdi>
    </Toggle>
  )
}

type Extra = {
  /** Direction to assume while the box is empty (its block's). */
  dir?: TextDirection
}

export function ContentInput({ dir, ref, ...props }: Omit<ComponentProps<'input'>, 'dir'> & Extra) {
  const { thaana, setThaana, attrs } = useContentTyping(props.value, dir)
  const keyboard = useThaanaKeyboard<HTMLInputElement>({ enabled: thaana })
  return (
    <InputGroup>
      <InputGroupInput ref={mergeRefs(ref, keyboard)} {...attrs} {...props} />
      <InputGroupAddon align="inline-end">
        <ThaanaToggle on={thaana} onChange={setThaana} />
      </InputGroupAddon>
    </InputGroup>
  )
}

export function ContentTextarea({ dir, ref, ...props }: Omit<ComponentProps<'textarea'>, 'dir'> & Extra) {
  const { thaana, setThaana, attrs } = useContentTyping(props.value, dir)
  const keyboard = useThaanaKeyboard<HTMLTextAreaElement>({ enabled: thaana })
  return (
    <InputGroup>
      <InputGroupTextarea ref={mergeRefs(ref, keyboard)} {...attrs} {...props} />
      <InputGroupAddon align="block-end" className="justify-end">
        <ThaanaToggle on={thaana} onChange={setThaana} />
      </InputGroupAddon>
    </InputGroup>
  )
}
