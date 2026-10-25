import { EyeIcon, InboxIcon, PencilIcon, SettingsIcon, Share2Icon } from 'lucide-react'

/** The pages of one form, in the form bar's order. */
export const FORM_NAV = [
  { to: '/forms/$formId/edit', label: 'Edit', icon: PencilIcon },
  { to: '/forms/$formId/preview', label: 'Preview', icon: EyeIcon },
  { to: '/forms/$formId/share', label: 'Share', icon: Share2Icon },
  { to: '/forms/$formId/submissions', label: 'Submissions', icon: InboxIcon },
  { to: '/forms/$formId/settings', label: 'Settings', icon: SettingsIcon },
] as const
export type NavItem = (typeof FORM_NAV)[number]

/** The form page a path is on: `/forms/{id}/submissions/12` is on Submissions. */
export function activeNav(pathname: string): NavItem {
  const segment = /^\/forms\/[^/]+\/([^/]+)/.exec(pathname)?.[1]
  return FORM_NAV.find((n) => n.to.endsWith(`/${segment}`)) ?? FORM_NAV[0]
}
