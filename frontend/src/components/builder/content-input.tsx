/**
 * Inputs for form text in the studio. In a Dhivehi form they type Thaana with the phonetic
 * keyboard (@yashau/thaana, attached to the official shadcn Input/Textarea) and offer the
 * "ތ / A" toggle; otherwise they are plain inputs with the form's lang/dir.
 */
import { mergeRefs, useThaanaKeyboard } from '@yashau/thaana-react'
import { type ComponentProps, useState } from 'react'

import { Input } from '@/components/ui/input'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupTextarea,
} from '@/components/ui/input-group'
import { Textarea } from '@/components/ui/textarea'
import { Toggle } from '@/components/ui/toggle'
import { toggleOn } from '@/lib/toggle'
import { contentProps, type FormLanguage } from '@/schema/language'

function ThaanaToggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <Toggle
      size="sm"
      pressed={on}
      onPressedChange={onChange}
      aria-label="Thaana keyboard"
      title="Thaana keyboard"
      className={toggleOn}
    >
      <bdi dir="ltr">ތ / A</bdi>
    </Toggle>
  )
}

export function ContentInput({
  language,
  ref,
  ...props
}: ComponentProps<'input'> & { language: FormLanguage }) {
  const [on, setOn] = useState(true)
  const keyboard = useThaanaKeyboard<HTMLInputElement>({ enabled: language === 'dv' && on })
  if (language !== 'dv') return <Input ref={ref} {...contentProps(language)} {...props} />
  return (
    <InputGroup>
      <InputGroupInput ref={mergeRefs(ref, keyboard)} {...contentProps(language)} {...props} />
      <InputGroupAddon align="inline-end">
        <ThaanaToggle on={on} onChange={setOn} />
      </InputGroupAddon>
    </InputGroup>
  )
}

export function ContentTextarea({
  language,
  ref,
  ...props
}: ComponentProps<'textarea'> & { language: FormLanguage }) {
  const [on, setOn] = useState(true)
  const keyboard = useThaanaKeyboard<HTMLTextAreaElement>({ enabled: language === 'dv' && on })
  if (language !== 'dv') return <Textarea ref={ref} {...contentProps(language)} {...props} />
  return (
    <InputGroup>
      <InputGroupTextarea ref={mergeRefs(ref, keyboard)} {...contentProps(language)} {...props} />
      <InputGroupAddon align="block-end" className="justify-end">
        <ThaanaToggle on={on} onChange={setOn} />
      </InputGroupAddon>
    </InputGroup>
  )
}
