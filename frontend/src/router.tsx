import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Outlet,
  redirect,
  type RouterHistory,
} from '@tanstack/react-router'

import { AppShell } from '@/components/layout/app-shell'
import { validateFormsSearch } from '@/components/forms/forms-view'
import { validateSubmissionsSearch } from '@/components/submissions/search'
import { meQuery, metaQuery } from '@/lib/queries'
import { autoSignInUrl, clearSignedOut, loginTarget, startAutoSignIn } from '@/lib/sso-auto'
import { FormEditorPage } from '@/routes/form-editor'
import { FormLayout } from '@/routes/form-layout'
import { FormPreviewPage } from '@/routes/form-preview'
import { FormSettingsPage } from '@/routes/form-settings'
import { FormSharePage } from '@/routes/form-share'
import { FormSubmissionsPage } from '@/routes/form-submissions'
import { FormsPage } from '@/routes/forms'
import { FormsTrashPage } from '@/routes/forms-trash'
import { JotformImportPage } from '@/routes/jotform-import'
import { LoginPage } from '@/routes/login'
import { InvitePage } from '@/routes/invite'
import {
  BrandingSettingsPage,
  FormThemeSettingsPage,
  OrgSettingsLayout,
  PeopleSettingsPage,
} from '@/routes/org-settings'
import { validateSettingsSearch } from '@/lib/settings-org'
import { SubmissionsImportPage } from '@/routes/submissions-import'
import { SubmissionViewPage } from '@/routes/submission-view'

interface RouterContext {
  queryClient: QueryClient
}

const rootRoute = createRootRouteWithContext<RouterContext>()({ component: AppShell })

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  validateSearch: (search: Record<string, unknown>): { next?: string; error?: string; manual?: boolean } => ({
    next: typeof search.next === 'string' ? search.next : undefined,
    error: typeof search.error === 'string' ? search.error : undefined,
    manual: search.manual === 1 || search.manual === '1' || search.manual === true ? true : undefined,
  }),
  beforeLoad: async ({ context, search, preload }) => {
    const me = await context.queryClient.ensureQueryData(meQuery)
    if (me) throw redirect({ to: '/forms' })
    // Automatic single sign-on (DESIGN 8.1): leave for the IdP before the page renders.
    if (preload) return { autoSignIn: false }
    const meta = await context.queryClient.ensureQueryData(metaQuery).catch(() => undefined)
    const url = autoSignInUrl({ features: meta?.features, ...search, next: loginTarget(search.next) })
    if (url) startAutoSignIn(url)
    return { autoSignIn: !!url }
  },
  component: LoginPage,
})

/** The link in an invitation email (PEOPLE-SCREENS 5); works signed in or out. */
const inviteRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login/invite/$token',
  validateSearch: (search: Record<string, unknown>): { manual?: boolean } => ({
    manual: search.manual === 1 || search.manual === '1' || search.manual === true ? true : undefined,
  }),
  component: InvitePage,
})

/** Everything below requires a staff session. */
const authedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'authed',
  beforeLoad: async ({ context, location }) => {
    const me = await context.queryClient.ensureQueryData(meQuery)
    if (!me) throw redirect({ to: '/login', search: { next: location.href, error: undefined } })
    // A live session ends the signed-out state of this tab.
    clearSignedOut()
    return { me }
  },
  component: Outlet,
})

const indexRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: '/',
  beforeLoad: () => {
    throw redirect({ to: '/forms' })
  },
})

const formsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: '/forms',
  validateSearch: validateFormsSearch,
  component: FormsPage,
})

const formsTrashRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: '/forms/trash',
  component: FormsTrashPage,
})

const jotformImportRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: '/forms/import/jotform',
  component: JotformImportPage,
})

const orgSettingsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: '/settings',
  validateSearch: validateSettingsSearch,
  component: OrgSettingsLayout,
})

const brandingSettingsRoute = createRoute({
  getParentRoute: () => orgSettingsRoute,
  path: '/',
  component: BrandingSettingsPage,
})

const formThemeSettingsRoute = createRoute({
  getParentRoute: () => orgSettingsRoute,
  path: '/form-theme',
  component: FormThemeSettingsPage,
})

const peopleSettingsRoute = createRoute({
  getParentRoute: () => orgSettingsRoute,
  path: '/people',
  component: PeopleSettingsPage,
})

const formRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: '/forms/$formId',
  component: FormLayout,
})

const formIndexRoute = createRoute({
  getParentRoute: () => formRoute,
  path: '/',
  beforeLoad: ({ params }) => {
    throw redirect({ to: '/forms/$formId/edit', params })
  },
})

const formEditorRoute = createRoute({
  getParentRoute: () => formRoute,
  path: '/edit',
  component: FormEditorPage,
})

const formPreviewRoute = createRoute({
  getParentRoute: () => formRoute,
  path: '/preview',
  component: FormPreviewPage,
})

const formShareRoute = createRoute({
  getParentRoute: () => formRoute,
  path: '/share',
  component: FormSharePage,
})

const formSubmissionsRoute = createRoute({
  getParentRoute: () => formRoute,
  path: '/submissions',
  validateSearch: validateSubmissionsSearch,
  component: FormSubmissionsPage,
})

/** Insights and "Ask your submissions" (INSIGHTS-SCREENS); lazy: it carries the charts. */
const submissionsInsightsRoute = createRoute({
  getParentRoute: () => formRoute,
  path: '/submissions/insights',
  validateSearch: validateSubmissionsSearch,
  component: lazyRouteComponent(() => import('@/routes/form-insights'), 'FormInsightsPage'),
})

const submissionsImportRoute = createRoute({
  getParentRoute: () => formRoute,
  path: '/submissions/import',
  component: SubmissionsImportPage,
})

/** One submission as the filled form (SUBMISSIONS-VIEWER-SCREENS 1); `$ref` is the reference number. */
const submissionViewRoute = createRoute({
  getParentRoute: () => formRoute,
  path: '/submissions/$ref',
  validateSearch: validateSubmissionsSearch,
  component: SubmissionViewPage,
})

const formSettingsRoute = createRoute({
  getParentRoute: () => formRoute,
  path: '/settings',
  component: FormSettingsPage,
})

const routeTree = rootRoute.addChildren([
  loginRoute,
  inviteRoute,
  authedRoute.addChildren([
    indexRoute,
    formsRoute,
    formsTrashRoute,
    jotformImportRoute,
    orgSettingsRoute.addChildren([brandingSettingsRoute, formThemeSettingsRoute, peopleSettingsRoute]),
    formRoute.addChildren([
      formIndexRoute,
      formEditorRoute,
      formPreviewRoute,
      formShareRoute,
      formSubmissionsRoute,
      submissionsInsightsRoute,
      submissionsImportRoute,
      submissionViewRoute,
      formSettingsRoute,
    ]),
  ]),
])

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({ routeTree, context: { queryClient }, defaultPreload: 'intent', history })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
