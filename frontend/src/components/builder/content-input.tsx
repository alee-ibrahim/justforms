/**
 * Inputs for form text in the studio. Form text may be English, Dhivehi or both, so every
 * input follows what is typed (first strong character: Thaana right to left, Latin left to
 * right). Dhivehi is typed with the device's own keyboard; the app adds no keyboard of its own.
 */
import { type ComponentProps } from 'react'

import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { TextDirection } from '@/schema/direction'

import { contentTyping } from './content-typing'

type Extra = {
  /** Direction to assume while the box is empty (its block's). */
  dir?: TextDirection
}

export function ContentInput({ dir, ...props }: Omit<ComponentProps<'input'>, 'dir'> & Extra) {
  return <Input {...contentTyping(props.value, dir)} {...props} />
}

export function ContentTextarea({ dir, ...props }: Omit<ComponentProps<'textarea'>, 'dir'> & Extra) {
  return <Textarea {...contentTyping(props.value, dir)} {...props} />
}
