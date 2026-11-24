import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { PlusIcon } from 'lucide-react'
import { useState } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { hostPrefix, useSlugCheck } from '@/components/forms/slug'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { api } from '@/lib/api'
import { textProps } from '@/schema/align'
import { titleSlug } from '@/thaana/latin'

export function CreateFormDialog({ orgId }: { orgId: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  // A form has no language: the title may be English, Dhivehi or both. The field's direction
  // follows what is typed.
  const auto = titleSlug(title)
  const check = useSlugCheck(auto, undefined, open && title.trim().length > 0)
  const address = check.result ? (check.result.available ? auto : check.result.suggestion) : null

  const create = useMutation({
    mutationFn: () => api.createForm(orgId, { title: title.trim() }),
    onSuccess: async (form) => {
      await queryClient.invalidateQueries({ queryKey: ['forms', orgId] })
      setOpen(false)
      await navigate({ to: '/forms/$formId/edit', params: { formId: form.id } })
    },
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) {
          setTitle('')
          create.reset()
        }
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <PlusIcon />
          New form
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (title.trim()) create.mutate()
          }}
          className="flex flex-col gap-4"
        >
          <DialogHeader>
            <DialogTitle>New form</DialogTitle>
            <DialogDescription>
              Give the form a title. Forms can hold English and Dhivehi text side by side.
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            {create.isError && (
              <Alert variant="destructive">
                <AlertDescription>
                  Couldn't create the form. Check your connection and try again.
                </AlertDescription>
              </Alert>
            )}
            <Field>
              <FieldLabel htmlFor="form-title">Title</FieldLabel>
              <Input
                id="form-title"
                required
                maxLength={500}
                {...textProps(title)}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                autoFocus
              />
              {/* Until there is a title this line says what Create form needs (REVIEW P3-5); then it
                  shows the address the title gives. */}
              <FieldDescription id="form-title-hint" aria-live="polite" className="min-h-5 truncate">
                {address ? (
                  <>
                    Address: <bdi dir="ltr">{hostPrefix() + address}</bdi>
                  </>
                ) : (
                  'Enter a title to create the form.'
                )}
              </FieldDescription>
            </Field>
          </FieldGroup>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button
              type="submit"
              disabled={!title.trim() || create.isPending}
              aria-describedby={title.trim() ? undefined : 'form-title-hint'}
            >
              {create.isPending && <Spinner />}
              Create form
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
