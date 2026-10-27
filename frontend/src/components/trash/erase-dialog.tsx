/**
 * "Delete permanently" with a typed confirmation (SUBMISSIONS-SORT-AND-TRASH 3.4): erasing
 * from the trash has no undo, so the button only works once the word is typed.
 */
import { useId, useState, type ReactNode } from 'react'

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'

export const CONFIRM_WORD = 'delete'

export function EraseDialog({
  open,
  onOpenChange,
  title,
  description,
  action,
  pending,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description: ReactNode
  /** The button's words, e.g. "Delete 3 permanently". */
  action: string
  pending: boolean
  onConfirm: () => void
}) {
  const id = useId()
  const [typed, setTyped] = useState('')
  const ok = typed.trim().toLowerCase() === CONFIRM_WORD
  return (
    <AlertDialog
      open={open}
      onOpenChange={(o) => {
        if (pending) return
        if (!o) setTyped('')
        onOpenChange(o)
      }}
    >
      <AlertDialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (ok && !pending) onConfirm()
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>{title}</AlertDialogTitle>
            <AlertDialogDescription>{description}</AlertDialogDescription>
          </AlertDialogHeader>
          <Field>
            <FieldLabel htmlFor={id}>
              Type “{CONFIRM_WORD}” to confirm
            </FieldLabel>
            <Input
              id={id}
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
            <FieldDescription>This can't be undone.</FieldDescription>
          </Field>
          <AlertDialogFooter>
            <AlertDialogCancel type="button" disabled={pending}>
              Cancel
            </AlertDialogCancel>
            <Button type="submit" variant="destructive" disabled={!ok || pending}>
              {pending && <Spinner />}
              {action}
            </Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  )
}
