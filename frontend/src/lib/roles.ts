/** Organisation roles in the studio (DESIGN 7, docs/ux/PEOPLE-SCREENS.md 1). */
import type { Me, OrgRole } from './api'

export interface RoleOption {
  value: OrgRole
  label: string
  description: string
}

/** Lowest first: the order the role pickers list them in. */
export const ORG_ROLES: RoleOption[] = [
  { value: 'member', label: 'Member', description: "Sees only the forms shared with them. Can't create forms." },
  { value: 'creator', label: 'Form creator', description: 'Creates forms. Sees the forms they created or that are shared with them.' },
  { value: 'admin', label: 'Admin', description: 'Everything, including organisation settings and people. Owner of every form.' },
]

export const ORG_ROLE_LABEL: Record<OrgRole, string> = {
  admin: 'Admin',
  creator: 'Form creator',
  member: 'Member',
}

/** "as a form creator" in sentences. */
export const ORG_ROLE_PHRASE: Record<OrgRole, string> = {
  admin: 'an admin',
  creator: 'a form creator',
  member: 'a member',
}

export function orgRole(me: Me | null | undefined, orgId: string | undefined): OrgRole | null {
  if (!me || !orgId) return null
  if (me.isSuperadmin) return 'admin'
  return me.orgs.find((o) => o.id === orgId)?.role ?? null
}

export const isOrgAdmin = (me: Me | null | undefined, orgId: string | undefined) => orgRole(me, orgId) === 'admin'

/** Form creators and admins create, import and duplicate forms. */
export function canCreateForms(me: Me | null | undefined, orgId: string | undefined): boolean {
  const role = orgRole(me, orgId)
  return role === 'admin' || role === 'creator'
}
