import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { CircleHelpIcon, LogOutIcon, MonitorIcon, MoonIcon, SettingsIcon, SunIcon, UserIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'

import { BrandLogo } from '@/components/brand/brand-parts'
import { JustFormsLogo } from '@/components/brand/logo'
import { ShortcutList } from '@/components/layout/shortcuts'
import { useHeightVar } from '@/components/layout/sticky'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Toaster } from '@/components/ui/sonner'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useMenuTooltip } from '@/components/layout/use-menu-tooltip'
import { api, type Me } from '@/lib/api'
import { applyBrand, type Brand } from '@/lib/branding'
import { applyAppearance, rememberAppearance, storedAppearance, type Appearance } from '@/lib/color-scheme'
import { brandQuery, meQuery, metaQuery } from '@/lib/queries'
import { markSignedOut } from '@/lib/sso-auto'
import { cn } from '@/lib/utils'
import { loadThaanaFont } from '@/lib/thaana-font'

const APPEARANCES: { value: Appearance; label: string; icon: typeof SunIcon }[] = [
  { value: 'light', label: 'Light', icon: SunIcon },
  { value: 'dark', label: 'Dark', icon: MoonIcon },
  { value: 'system', label: 'Match device', icon: MonitorIcon },
]

function UserMenu() {
  const { data: me } = useQuery(meQuery)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  if (!me) return null

  const choose = (value: string) => {
    const pref = APPEARANCES.find((a) => a.value === value)?.value
    if (!pref || pref === me.appearance) return
    applyAppearance(pref)
    rememberAppearance(pref)
    const optimistic: Me = { ...me, appearance: pref }
    queryClient.setQueryData(meQuery.queryKey, optimistic)
    api.patchMe({ appearance: pref }).then(
      (next) => queryClient.setQueryData(meQuery.queryKey, next),
      () => toast("Couldn't save your appearance choice. It applies on this device only."),
    )
  }

  const signOut = async () => {
    // Not straight back to the IdP afterwards: the sign-in page says "You're signed out".
    markSignedOut()
    const { logoutUrl } = await api.logout()
    queryClient.clear()
    if (logoutUrl) window.location.assign(logoutUrl)
    else await navigate({ to: '/login', search: { next: undefined, error: undefined } })
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label="Account">
          <UserIcon />
          <bdi dir="ltr" className="max-w-48 truncate max-sm:hidden">
            {me.displayName || me.email}
          </bdi>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-56">
        <DropdownMenuLabel>
          <bdi dir="ltr">{me.email}</bdi>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">Appearance</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={me.appearance} onValueChange={choose}>
          {APPEARANCES.map(({ value, label, icon: Icon }) => (
            <DropdownMenuRadioItem key={value} value={value} onSelect={(e) => e.preventDefault()}>
              <Icon />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        {(me.isSuperadmin || me.orgs.some((o) => o.role === 'admin')) && (
          <DropdownMenuItem asChild>
            <Link to="/settings">
              <SettingsIcon />
              Organisation settings
            </Link>
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => void signOut()}>
          <LogOutIcon />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function HelpButton() {
  const menuTip = useMenuTooltip()
  return (
    <Popover>
      <Tooltip {...menuTip.tooltip}>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Keyboard shortcuts">
              <CircleHelpIcon />
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>Keyboard shortcuts</TooltipContent>
      </Tooltip>
      <PopoverContent align="end" className="w-80" {...menuTip.content}>
        <p className="text-sm font-medium">Keyboard shortcuts</p>
        <ShortcutList />
      </PopoverContent>
    </Popover>
  )
}

/** The header identity: the organisation's logo, else its icon and name, else JustForms'. */
function HeaderBrand({ brand }: { brand: Brand | undefined }) {
  if (brand?.logoUrl) return <BrandLogo brand={brand} className="max-w-48" />
  if (brand?.custom)
    return (
      <span className="flex items-center gap-2 font-semibold">
        {brand.iconUrl && <img src={brand.iconUrl} alt="" className="size-6 rounded-sm" />}
        <bdi dir="auto" className="max-w-40 truncate">
          {brand.name}
        </bdi>
      </span>
    )
  return <JustFormsLogo />
}

/** Pages inside one form (`/forms/{id}/...`), which carry the form bar. */
const FORM_PAGE = /^\/forms\/(?!import\/)[^/]+\/./

/** Studio chrome. The studio UI is English and left-to-right; only form content follows
 * the form's language (see `contentProps` in `@/schema`). On phones a form page shows one
 * bar, the form bar, so this header steps aside there (STUDIO-HEADER 2). */
export function AppShell() {
  const meta = useQuery(metaQuery)
  const me = useQuery(meQuery)
  const slug = me.data?.orgs[0]?.slug ?? '_'
  const brand = useQuery({ ...brandQuery(slug), enabled: !me.isPending })
  useEffect(() => loadThaanaFont(meta.data?.thaanaFontCssUrl), [meta.data])
  // The account's appearance wins over this device's cached copy (another device may have
  // changed it).
  const appearance = me.data?.appearance
  useEffect(() => {
    if (!appearance || appearance === storedAppearance()) return
    applyAppearance(appearance)
    rememberAppearance(appearance)
  }, [appearance])
  useEffect(() => {
    if (brand.data) applyBrand(brand.data, '')
  }, [brand.data])
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const signedIn = !pathname.startsWith('/login')
  const header = useRef<HTMLElement>(null)
  useHeightVar(header, '--app-bar-h')
  return (
    <TooltipProvider>
      <div className="flex min-h-svh flex-col">
        <header
          ref={header}
          className={cn(
            'sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b bg-card px-4 print:hidden',
            FORM_PAGE.test(pathname) && 'max-sm:hidden',
          )}
        >
          <Link
            to="/forms"
            aria-label={brand.data?.custom ? brand.data.name : 'JustForms'}
            className="me-2 flex h-8 items-center rounded-sm px-1 pointer-coarse:h-11 text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <HeaderBrand brand={brand.data} />
          </Link>
          {signedIn && (
            <nav aria-label="Main" className="flex items-center max-sm:hidden">
              <Button asChild variant="ghost" size="sm">
                <Link to="/forms" activeProps={{ 'aria-current': 'page' }}>
                  Forms
                </Link>
              </Button>
            </nav>
          )}
          <div className="ms-auto flex items-center gap-1">
            {signedIn && <HelpButton />}
            <UserMenu />
          </div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col">
          <Outlet />
        </div>
      </div>
      <Toaster position="bottom-right" />
    </TooltipProvider>
  )
}
