/**
 * Settings (PHASE-4-SCREENS 1, APPROVALS-SCREENS 1, FORM-THEME-SCREENS 3.3, SAVED-PROGRESS-SCREENS 3,
 * SHARING-PREVIEW-SCREENS 3): appearance, the link's sharing preview, who can respond and saved progress, spam protection, emails, approvals, webhooks,
 * retention.
 *
 * One section at a time (REVIEW P2-12): a section list at the start edge on desktop, a select on
 * phones. The open section is kept in the URL hash (`#approvals`), so links can point at one.
 */
import { type ReactNode, useEffect, useState } from 'react'

import { useFormSummary } from '@/components/builder/form-context'
import { PageContainer } from '@/components/layout/page'
import { FormAppearanceCard } from '@/components/theme/form-theme-cards'
import { ApprovalsCard } from '@/components/settings/approvals-card'
import { NotificationsCard } from '@/components/settings/notifications-card'
import { ProgressCard } from '@/components/settings/progress-card'
import { RespondentsCard } from '@/components/settings/respondents-card'
import { RetentionCard } from '@/components/settings/retention-card'
import { SharingCard } from '@/components/settings/sharing-card'
import { SpamCard } from '@/components/settings/spam-card'
import { WebhooksCard } from '@/components/settings/webhooks-card'
import { Button } from '@/components/ui/button'
import { Field, FieldLabel } from '@/components/ui/field'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import type { FormSummary } from '@/lib/api'

interface Section {
  id: string
  label: string
  render: (form: FormSummary, canManage: boolean) => ReactNode
}

const SECTIONS: Section[] = [
  { id: 'appearance', label: 'Appearance', render: (form) => <FormAppearanceCard form={form} /> },
  { id: 'sharing', label: 'Sharing preview', render: (form) => <SharingCard form={form} /> },
  {
    id: 'access',
    label: 'Access',
    render: (form, canManage) => (
      <>
        <RespondentsCard form={form} canManage={canManage} />
        <ProgressCard form={form} canManage={canManage} />
      </>
    ),
  },
  { id: 'spam', label: 'Spam protection', render: (form, canManage) => <SpamCard form={form} canManage={canManage} /> },
  {
    id: 'notifications',
    label: 'Notifications',
    render: (form, canManage) => <NotificationsCard form={form} canManage={canManage} />,
  },
  { id: 'approvals', label: 'Approvals', render: (form, canManage) => <ApprovalsCard form={form} canManage={canManage} /> },
  { id: 'webhooks', label: 'Webhooks', render: (form, canManage) => <WebhooksCard form={form} canManage={canManage} /> },
  { id: 'retention', label: 'Data retention', render: (form, canManage) => <RetentionCard form={form} canManage={canManage} /> },
]

function sectionFromHash(): string {
  const id = window.location.hash.slice(1)
  return SECTIONS.some((s) => s.id === id) ? id : SECTIONS[0].id
}

function useSection() {
  const [section, setSection] = useState(sectionFromHash)
  useEffect(() => {
    const onHash = () => setSection(sectionFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const choose = (id: string) => {
    setSection(id)
    window.history.replaceState(window.history.state, '', `#${id}`)
  }
  return [section, choose] as const
}

export function FormSettingsPage() {
  const form = useFormSummary()
  const canManage = form.role === 'owner'
  const [section, choose] = useSection()
  const current = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0]
  return (
    <PageContainer>
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        {!canManage && <p className="text-sm text-muted-foreground">Only owners can change these settings.</p>}
      </div>
      <Field className="lg:hidden">
        <FieldLabel htmlFor="settings-section">Section</FieldLabel>
        <NativeSelect id="settings-section" className="w-full sm:w-72" value={section} onChange={(e) => choose(e.target.value)}>
          {SECTIONS.map((s) => (
            <NativeSelectOption key={s.id} value={s.id}>
              {s.label}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </Field>
      <div className="grid items-start gap-6 lg:grid-cols-[11rem_minmax(0,1fr)] lg:gap-8">
        <nav aria-label="Settings sections" className="flex flex-col gap-0.5 max-lg:hidden lg:sticky lg:top-16">
          {SECTIONS.map((s) => (
            <Button
              key={s.id}
              variant="ghost"
              size="sm"
              className="justify-start aria-[current=true]:bg-secondary aria-[current=true]:font-semibold"
              aria-current={s.id === section ? 'true' : undefined}
              onClick={() => choose(s.id)}
            >
              {s.label}
            </Button>
          ))}
        </nav>
        <section aria-label={current.label} className="flex min-w-0 flex-col gap-6">
          {current.render(form, canManage)}
        </section>
      </div>
    </PageContainer>
  )
}
