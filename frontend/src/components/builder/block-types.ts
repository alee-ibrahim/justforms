import {
  AtSignIcon,
  CalendarIcon,
  CircleDotIcon,
  ClockIcon,
  EyeOffIcon,
  HashIcon,
  HeadingIcon,
  type LucideIcon,
  MinusIcon,
  PenLineIcon,
  PhoneIcon,
  PilcrowIcon,
  RepeatIcon,
  SquareCheckIcon,
  SquareIcon,
  StarIcon,
  TextIcon,
  ToggleLeftIcon,
  UploadIcon,
  RectangleHorizontalIcon,
} from 'lucide-react'

import type { Element } from '@/schema'

import type { BlockType } from './tree'

export interface BlockTypeInfo {
  type: BlockType
  label: string
  icon: LucideIcon
  group: 'Text' | 'Choice' | 'Date and time' | 'Files' | 'Layout' | 'Other'
  /** Extra words for search ("tel" finds Phone). */
  keywords: string
  disabled?: string
}

export const BLOCK_TYPES: BlockTypeInfo[] = [
  { type: 'short_text', label: 'Short answer', icon: RectangleHorizontalIcon, group: 'Text', keywords: 'text name line input' },
  { type: 'long_text', label: 'Long answer', icon: TextIcon, group: 'Text', keywords: 'paragraph textarea comment multi line' },
  { type: 'email', label: 'Email', icon: AtSignIcon, group: 'Text', keywords: 'mail address' },
  { type: 'phone', label: 'Phone', icon: PhoneIcon, group: 'Text', keywords: 'tel telephone mobile number' },
  { type: 'number', label: 'Number', icon: HashIcon, group: 'Text', keywords: 'amount age integer digits' },
  { type: 'single_choice', label: 'Single choice', icon: CircleDotIcon, group: 'Choice', keywords: 'radio dropdown select option one' },
  { type: 'multi_choice', label: 'Multi choice', icon: SquareCheckIcon, group: 'Choice', keywords: 'checkbox checkboxes many options' },
  { type: 'yes_no', label: 'Yes / no', icon: ToggleLeftIcon, group: 'Choice', keywords: 'boolean yes no' },
  { type: 'rating', label: 'Rating', icon: StarIcon, group: 'Choice', keywords: 'scale score stars' },
  { type: 'date', label: 'Date', icon: CalendarIcon, group: 'Date and time', keywords: 'day birthday calendar' },
  { type: 'time', label: 'Time', icon: ClockIcon, group: 'Date and time', keywords: 'hour clock' },
  { type: 'file', label: 'File upload', icon: UploadIcon, group: 'Files', keywords: 'attachment document image pdf' },
  { type: 'section', label: 'Section', icon: SquareIcon, group: 'Layout', keywords: 'group fieldset' },
  { type: 'repeater', label: 'Repeater', icon: RepeatIcon, group: 'Layout', keywords: 'repeat rows list table people' },
  { type: 'heading', label: 'Heading', icon: HeadingIcon, group: 'Layout', keywords: 'title text block' },
  { type: 'paragraph', label: 'Text block', icon: PilcrowIcon, group: 'Layout', keywords: 'paragraph instructions note' },
  { type: 'divider', label: 'Divider', icon: MinusIcon, group: 'Layout', keywords: 'line separator rule' },
  { type: 'hidden', label: 'Hidden value', icon: EyeOffIcon, group: 'Other', keywords: 'prefill parameter utm source' },
  { type: 'signature', label: 'Signature', icon: PenLineIcon, group: 'Other', keywords: 'sign signature declaration' },
]

export const BLOCK_GROUPS = ['Text', 'Choice', 'Date and time', 'Files', 'Layout', 'Other'] as const

export function blockType(el: Element): BlockType {
  if (el.kind === 'field') return el.type
  if (el.kind === 'content') return el.contentType === 'image' ? 'paragraph' : el.contentType
  return el.kind
}

export function blockInfo(el: Element | BlockType): BlockTypeInfo {
  const type = typeof el === 'string' ? el : blockType(el)
  return BLOCK_TYPES.find((b) => b.type === type) ?? BLOCK_TYPES[0]
}

/** Text shown for a block in lists (outline, logic pickers). */
export function blockLabel(el: Element): string {
  if (el.kind === 'field' || el.kind === 'repeater') return el.label.trim()
  if (el.kind === 'section') return el.title?.trim() ?? ''
  if (el.kind === 'content') return el.text?.trim() ?? ''
  return ''
}
