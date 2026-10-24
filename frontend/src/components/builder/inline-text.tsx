/**
 * Form text edited in place on the canvas (docs/ux/INLINE-EDIT-AND-LOGO-SCREENS.md §1).
 *
 * Idle, it is the renderer's own text inside a focusable `role="button"` ("Edit question label:
 * Full name"). A click, tap, Enter or F2 swaps in an official shadcn Input / Textarea (with the
 * "ތ / A" phonetic keyboard toggle in a Dhivehi form) set in the text's own typography. Enter or
 * blur commits once (one undo step, one autosave patch), Esc cancels, Shift+Enter is a line
 * break in multi-line text. Which text is being edited lives in the builder store
 * (`editing`), so other parts (a new block, Enter in an option) can open an editor.
 */
import { mergeRefs, useThaanaKeyboard } from '@yashau/thaana-react'
import {
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'
import { flushSync } from 'react-dom'

import { Input } from '@/components/ui/input'
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupTextarea } from '@/components/ui/input-group'
import { Textarea } from '@/components/ui/textarea'
import { Toggle } from '@/components/ui/toggle'
import { toggleOn } from '@/lib/toggle'
import { cn } from '@/lib/utils'
import { displayText } from '@/thaana/display'
import { contentProps, type FormLanguage } from '@/schema/language'

import { focusInlineText } from './inline-edit'
import { useBuilder, useStore } from './store'

type EditEvent = KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>

export interface EditControls {
  /** Current text in the box. */
  draft: string
  /** End editing: commit (or cancel) and optionally put focus back on the idle text. */
  finish: (commit: boolean, refocus?: boolean) => void
}

export interface InlineTextProps {
  /** Unique key of this text in the builder (`textKey`). */
  editKey: string
  value: string
  onCommit: (text: string) => void
  /** What it edits, for the accessible name: "question label" → "Edit question label: …". */
  name: string
  language: FormLanguage
  multiline?: boolean
  /** The idle rendering of a non-empty value (default: the text, numbers isolated in dv). */
  display?: ReactNode
  /** Shown when the value is empty: a string is a muted placeholder ("Untitled question"); a
   * node is shown as is (a button's English default text). */
  empty?: ReactNode
  /** Always shown when idle instead of the text (the answer box whose placeholder this is). */
  frame?: ReactNode
  /** `box`: the editor looks like an answer box (placeholders) instead of the text. */
  variant?: 'text' | 'box'
  /** Shown (muted) when the value is empty and `active`: an optional text's prompt. */
  prompt?: string
  /** Its block (or the form / page) is selected: prompts show. */
  active?: boolean
  /** Select the owner; with `edit`, start editing this text in the same step. */
  activate?: (edit?: string) => void
  /** Keys while editing (options: Enter adds one, Backspace removes); return true when handled. */
  onEditKey?: (e: EditEvent, controls: EditControls) => boolean
  /** Keys on the idle text (options: Alt+↑/↓ move); return true when handled. */
  onIdleKey?: (e: KeyboardEvent<HTMLElement>) => boolean
  /** Placeholder inside the box while editing. */
  placeholder?: string
  /** Layout of the idle element. */
  block?: boolean
  className?: string
  inputClassName?: string
}

/** A muted English run (prompts, placeholders) that reads correctly inside a dv sheet. */
export function Prompt({ children }: { children: ReactNode }) {
  return (
    <bdi lang="en" dir="ltr" className="font-sans font-normal text-muted-foreground">
      {children}
    </bdi>
  )
}

export function InlineText(props: InlineTextProps) {
  const store = useStore()
  const editing = useBuilder((s) => s.editing === props.editKey)
  const locked = useBuilder((s) => s.locked)
  const { value, language, active, block } = props
  const interactive = !store.readOnly && !locked
  const pressed = useRef(false)

  if (editing && interactive) return <InlineEditor {...props} />

  const filled = value.trim() !== ''
  if (!props.frame && !filled && props.empty === undefined && !(active && props.prompt)) return null
  const empty = props.empty ?? props.prompt
  const content =
    props.frame ??
    (filled ? (props.display ?? displayText(value, language)) : typeof empty === 'string' ? <Prompt>{empty}</Prompt> : empty)
  const Tag = block ? 'div' : 'span'
  if (!interactive) return <Tag className={props.className}>{content}</Tag>

  const start = (e: MouseEvent | KeyboardEvent) => {
    e.stopPropagation()
    // Inside a <label>: don't let the label forward the click to the (inert) answer box.
    e.preventDefault()
    // Mount and focus the input inside the click: phones only open the keyboard for a focus
    // that happens during the tap itself.
    flushSync(() => (props.activate ? props.activate(props.editKey) : store.setEditing(props.editKey)))
  }
  return (
    <Tag
      role="button"
      tabIndex={0}
      data-inline-text={props.editKey}
      aria-label={`Edit ${props.name}${filled ? `: ${value}` : ''}`}
      className={cn(
        'relative cursor-text rounded-xs outline-offset-2 box-decoration-clone',
        // Touch: a 44px tap area around short texts, without moving anything.
        "pointer-coarse:before:absolute pointer-coarse:before:-inset-2.5 pointer-coarse:before:content-['']",
        'hover:outline-1 hover:outline-input hover:outline-dashed',
        'focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
        block ? 'block' : 'inline',
        props.className,
      )}
      onClick={start}
      // A press selects and edits on click. Selecting already on focus (mouse down) would show
      // the block's prompts and move the text away before the click lands.
      onPointerDown={() => {
        pressed.current = true
      }}
      onFocus={(e: FocusEvent) => {
        if (e.target === e.currentTarget && !active && !pressed.current) props.activate?.()
        pressed.current = false
      }}
      onKeyDown={(e: KeyboardEvent<HTMLElement>) => {
        if (props.onIdleKey?.(e)) return
        if (e.key === 'Enter' || e.key === 'F2') {
          e.preventDefault()
          start(e)
        }
      }}
    >
      {content}
    </Tag>
  )
}

/** Typography of the text it replaces; a quiet box shows what is being typed into. */
const TEXT =
  'h-auto min-h-0 pointer-coarse:min-h-11 rounded-sm bg-transparent px-1.5 py-0.5 -mx-1.5 -my-0.5 shadow-none text-[length:inherit] md:text-[length:inherit] font-[inherit] leading-[inherit] tracking-[inherit] dark:bg-transparent'

function InlineEditor({
  editKey,
  value,
  onCommit,
  name,
  language,
  multiline,
  onEditKey,
  placeholder,
  block,
  inputClassName,
  variant,
}: InlineTextProps) {
  const store = useStore()
  const box = variant === 'box'
  const [draft, setDraft] = useState(value)
  const [thaana, setThaana] = useState(true)
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null)
  const keyboard = useThaanaKeyboard<HTMLInputElement & HTMLTextAreaElement>({ enabled: language === 'dv' && thaana })
  const done = useRef(false)
  const latest = useRef({ draft, value, onCommit })
  useEffect(() => {
    latest.current = { draft, value, onCommit }
  })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.focus({ preventScroll: true })
    const end = el.value.length
    el.setSelectionRange(end, end)
    el.scrollIntoView?.({ block: 'nearest' })
  }, [])

  // Unmounted without Enter or blur (another text opened, the block went away): keep the text.
  useEffect(() => {
    done.current = false
    return () => {
      if (done.current) return
      const { draft: d, value: v, onCommit: commit } = latest.current
      if (d !== v) commit(d)
    }
  }, [])

  const finish = (commit: boolean, refocus = false) => {
    if (done.current) return
    done.current = true
    if (commit && draft !== value) onCommit(draft)
    if (store.get().editing === editKey) store.setEditing(null)
    if (refocus) focusInlineText(editKey)
  }

  const onKeyDown = (e: EditEvent) => {
    e.stopPropagation()
    if (e.nativeEvent.isComposing) return
    if (onEditKey?.(e, { draft, finish })) return
    if (e.key === 'Escape') {
      e.preventDefault()
      finish(false, true)
    } else if (e.key === 'Enter' && !(multiline && e.shiftKey)) {
      e.preventDefault()
      finish(true, true)
    }
  }

  const merged = mergeRefs(ref, keyboard)
  const common = {
    value: draft,
    onChange: (e: { target: { value: string } }) => setDraft(e.target.value),
    onKeyDown,
    onClick: (e: MouseEvent) => e.stopPropagation(),
    'aria-label': `Edit ${name}`,
    placeholder,
    autoCapitalize: 'sentences',
    enterKeyHint: multiline ? ('enter' as const) : ('done' as const),
    ...contentProps(language),
  }
  const Wrap = block ? 'div' : 'span'
  // Placeholders are typed in a box like the answer box; other texts in their own typography.
  const BOX = box ? 'h-12 sm:h-11 text-base md:text-base' : TEXT
  const shift = box ? 'w-full' : 'w-[calc(100%+0.75rem)]'
  return (
    <Wrap
      className={cn(block ? 'block w-full min-w-0' : 'inline-block w-full align-top')}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) finish(true)
      }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {language === 'dv' ? (
        <InputGroup className={cn(box ? 'h-auto' : '-mx-1.5 -my-0.5 h-auto rounded-sm', shift, multiline && 'flex-col')}>
          {multiline ? (
            <InputGroupTextarea {...common} ref={merged} rows={box ? 3 : 1} className={cn(BOX, 'mx-0 my-0 h-auto min-h-0 resize-none', inputClassName)} />
          ) : (
            <InputGroupInput {...common} ref={merged} className={cn(BOX, 'mx-0 my-0', inputClassName)} />
          )}
          <InputGroupAddon align={multiline ? 'block-end' : 'inline-end'} className={multiline ? 'justify-end' : undefined}>
            <Toggle
              size="sm"
              pressed={thaana}
              onPressedChange={setThaana}
              // Keep the caret in the text: pressing the toggle mustn't blur (commit) it.
              onPointerDown={(e) => e.preventDefault()}
              onMouseDown={(e) => e.preventDefault()}
              aria-label="Thaana keyboard"
              title="Thaana keyboard"
              className={toggleOn}
            >
              <bdi dir="ltr">ތ / A</bdi>
            </Toggle>
          </InputGroupAddon>
        </InputGroup>
      ) : multiline ? (
        <Textarea {...common} ref={merged} rows={box ? 3 : 1} className={cn(BOX, shift, 'h-auto resize-none', box && 'min-h-28', inputClassName)} />
      ) : (
        <Input {...common} ref={merged} className={cn(BOX, shift, inputClassName)} />
      )}
    </Wrap>
  )
}
