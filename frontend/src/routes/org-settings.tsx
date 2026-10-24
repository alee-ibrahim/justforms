/**
 * Organisation settings (BRANDING-SCREENS 3, FORM-THEME-SCREENS 3.2, PEOPLE-SCREENS 2): one
 * section at a time, each its own route. A section list at the start edge on desktop, a select
 * on phones; an organisation select when the person belongs to more than one (superadmins see
 * every organisation). The organisation is kept in the URL (`?org=`).
 */
import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'

import { BrandingCard } from '@/components/branding/branding-card'
import { PageContainer } from '@/components/layout/page'
import { PeopleSection } from '@/components/people/people-section'
import { OrgFormThemeCard } from '@/components/theme/form-theme-cards'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field, FieldLabel } from '@/components/ui/field'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import type { Me } from '@/lib/api'
import { brandingQuery } from '@/lib/queries'
import { isOrgAdmin } from '@/lib/roles'
import { useSettingsOrg } from '@/lib/settings-org'

const SECTIONS = [
  { to: '/settings', label: 'Branding' },
  { to: '/settings/form-theme', label: 'Form theme' },
  { to: '/settings/people', label: 'People' },
] as const

type SectionPath = (typeof SECTIONS)[number]['to']

function OrgPicker({ me, orgId }: { me: Me; orgId: string }) {
  const navigate = useNavigate()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  if (me.orgs.length < 2) return null
  return (
    <Field className="sm:max-w-72">
      <FieldLabel htmlFor="settings-org">Organisation</FieldLabel>
      <NativeSelect
        id="settings-org"
        className="w-full"
        value={orgId}
        onChange={(e) => void navigate({ to: pathname as SectionPath, search: { org: e.target.value } })}
      >
        {me.orgs.map((o) => (
          <NativeSelectOption key={o.id} value={o.id}>
            {o.name}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    </Field>
  )
}

function SectionNav({ orgId }: { orgId: string }) {
  const navigate = useNavigate()
  const pathname = useRouterState({ select: (s) => s.location.pathname.replace(/\/$/, '') || '/' })
  const current = SECTIONS.find((s) => s.to === pathname)?.to ?? '/settings'
  return (
    <>
      <Field className="lg:hidden">
        <FieldLabel htmlFor="settings-section">Section</FieldLabel>
        <NativeSelect
          id="settings-section"
          className="w-full sm:w-72"
          value={current}
          onChange={(e) => void navigate({ to: e.target.value as SectionPath, search: { org: orgId } })}
        >
          {SECTIONS.map((s) => (
            <NativeSelectOption key={s.to} value={s.to}>
              {s.label}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </Field>
      <nav aria-label="Settings sections" className="flex flex-col gap-0.5 max-lg:hidden lg:sticky lg:top-16">
        {SECTIONS.map((s) => (
          <Button
            key={s.to}
            asChild
            variant="ghost"
            size="sm"
            className="justify-start aria-[current=page]:bg-secondary aria-[current=page]:font-semibold"
          >
            <Link to={s.to} search={{ org: orgId }} aria-current={s.to === current ? 'page' : undefined}>
              {s.label}
            </Link>
          </Button>
        ))}
      </nav>
    </>
  )
}

export function OrgSettingsLayout() {
  const { me, org } = useSettingsOrg()
  // The name people see is the branding display name; the account's own name is only the
  // fallback (it can be a short internal name).
  const branding = useQuery({ ...brandingQuery(org?.id ?? ''), enabled: !!org })
  const name = branding.data ? branding.data.displayName.trim() || org?.name : undefined
  return (
    <PageContainer>
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight">Organisation settings</h1>
        {name && (!me || me.orgs.length < 2) && (
          <p className="text-sm text-muted-foreground">
            <bdi dir="auto">{name}</bdi>
          </p>
        )}
      </div>
      {!org || !me ? (
        <Alert>
          <AlertDescription>You aren't a member of any organisation yet. Ask an administrator to add you.</AlertDescription>
        </Alert>
      ) : (
        <>
          <OrgPicker me={me} orgId={org.id} />
          <div className="grid items-start gap-6 lg:grid-cols-[11rem_minmax(0,1fr)] lg:gap-8">
            <SectionNav orgId={org.id} />
            <section className="flex min-w-0 flex-col gap-6">
              <Outlet />
            </section>
          </div>
        </>
      )}
    </PageContainer>
  )
}

function AdminsOnly({ children }: { children: string }) {
  return (
    <Alert>
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  )
}

export function BrandingSettingsPage() {
  const { me, org } = useSettingsOrg()
  if (!org) return null
  return (
    <>
      {!isOrgAdmin(me, org.id) && <AdminsOnly>Only organisation admins can change branding.</AdminsOnly>}
      <BrandingCard orgId={org.id} />
    </>
  )
}

export function FormThemeSettingsPage() {
  const { org } = useSettingsOrg()
  if (!org) return null
  return <OrgFormThemeCard orgId={org.id} />
}

export function PeopleSettingsPage() {
  const { me, org } = useSettingsOrg()
  if (!org || !me) return null
  if (!isOrgAdmin(me, org.id)) return <AdminsOnly>Only organisation admins can manage people.</AdminsOnly>
  return <PeopleSection orgId={org.id} me={me} />
}
