import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { PlusIcon } from 'lucide-react'
import { useThaanaKeyboard } from '@yashau/thaana-react'
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
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Spinner } from '@/components/ui/spinner'
import { api } from '@/lib/api'
import { contentProps, isFormLanguage, type FormLanguage } from '@/schema'

/** The address the server derives from a title (`app/services/slugs.py` slugify). */
function titleSlug(title: string): string {
  const ascii = title.normalize('NFKD').replace(/[^\x20-\x7e]/g, '')
  const slug = ascii.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60).replace(/-+$/, '')
  return slug || 'form'
}

export function CreateFormDialog({ orgId }: { orgId: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [lang, setLang] = useState<FormLanguage>('en')
  const keyboard = useThaanaKeyboard<HTMLInputElement>({ enabled: lang === 'dv' })
  const auto = titleSlug(title)
  const check = useSlugCheck(auto, undefined, open && title.trim().length > 0)
  const address = check.result ? (check.result.available ? auto : check.result.suggestion) : null

  const create = useMutation({
    mutationFn: () => api.createForm(orgId, { title: title.trim(), language: lang }),
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
          setLang('en')
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
              Give the form a title and pick the language its questions are written in.
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
                ref={keyboard}
                id="form-title"
                required
                maxLength={500}
                {...contentProps(lang)}
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
            <FieldSet>
              <FieldLegend variant="label">Form language</FieldLegend>
              <RadioGroup
                value={lang}
                onValueChange={(v) => {
                  if (isFormLanguage(v)) setLang(v)
                }}
                className="flex gap-6"
              >
                <Field orientation="horizontal" className="w-auto">
                  <RadioGroupItem value="en" id="lang-en" />
                  <FieldLabel htmlFor="lang-en" className="font-normal">
                    English
                  </FieldLabel>
                </Field>
                <Field orientation="horizontal" className="w-auto">
                  <RadioGroupItem value="dv" id="lang-dv" />
                  <FieldLabel htmlFor="lang-dv" className="font-normal">
                    Dhivehi
                  </FieldLabel>
                </Field>
              </RadioGroup>
            </FieldSet>
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
