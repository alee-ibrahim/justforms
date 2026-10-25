/**
 * The link in an invitation email: /login/invite/{token} (PEOPLE-SCREENS 5). A sign-in card for
 * the invited address; signing in accepts the invitation on the server. Signed in already as
 * that address: accepted at once. Expired, used or cancelled links say so.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { KeyRoundIcon } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { api, ApiError, ssoLoginUrl, type InvitationLink, type Me } from '@/lib/api'
import { applyBrand } from '@/lib/branding'
import { brandQuery, meQuery, metaQuery } from '@/lib/queries'
import { ORG_ROLE_PHRASE } from '@/lib/roles'
import { autoSignInUrl, clearSignedOut, markSignedOut, startAutoSignIn } from '@/lib/sso-auto'
import { LocalLogin, SigningIn } from '@/routes/login'

function Frame({ title, description, children }: { title: ReactNode; description?: ReactNode; children?: ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-sm flex-col gap-6 px-4 py-8">
      <Card>
        <CardHeader>
          <CardTitle>
            <h1>{title}</h1>
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        {children && <CardContent className="flex flex-col gap-4">{children}</CardContent>}
      </Card>
    </main>
  )
}

const org = (link: InvitationLink) => <bdi dir="auto">{link.orgName ?? 'the organisation'}</bdi>

function ToSignIn({ label = 'Go to sign-in' }: { label?: string }) {
  return (
    <Button asChild variant="outline">
      <Link to="/login" search={{ next: undefined, error: undefined }}>
        {label}
      </Link>
    </Button>
  )
}

/** Signed in as the invited address: accept and open the studio. */
function AcceptNow({ token, link }: { token: string; link: InvitationLink }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const started = useRef(false)
  const accept = useMutation({
    mutationFn: () => api.acceptInvitation(token),
    onSuccess: async ({ me, orgName }) => {
      queryClient.setQueryData(['me'], me)
      await queryClient.invalidateQueries({ queryKey: ['forms'] })
      toast(`You joined ${orgName}`)
      await navigate({ to: '/forms' })
    },
  })
  useEffect(() => {
    if (started.current) return
    started.current = true
    accept.mutate()
  }, [accept])
  if (accept.isError)
    return (
      <Frame title={<>Join {org(link)}</>}>
        <Alert variant="destructive">
          <AlertDescription>Couldn't accept the invitation. Reload the page to try again.</AlertDescription>
        </Alert>
      </Frame>
    )
  return (
    <Frame title={<>Join {org(link)}</>}>
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner /> Joining…
      </p>
    </Frame>
  )
}

/** Back from single sign-on, which accepted the invitation: open the studio. */
function Joined({ link }: { link: InvitationLink }) {
  const navigate = useNavigate()
  const done = useRef(false)
  useEffect(() => {
    if (done.current) return
    done.current = true
    toast(`You joined ${link.orgName ?? 'the organisation'}`)
    void navigate({ to: '/forms' })
  }, [link, navigate])
  return null
}

function WrongAccount({ link, me }: { link: InvitationLink; me: Me }) {
  const queryClient = useQueryClient()
  const signOut = async () => {
    markSignedOut()
    const { logoutUrl } = await api.logout()
    queryClient.setQueryData(['me'], null)
    if (logoutUrl) window.location.assign(logoutUrl)
  }
  return (
    <Frame
      title={
        <>
          This invitation is for <bdi dir="ltr">{link.email}</bdi>
        </>
      }
      description={
        <>
          You're signed in as <bdi dir="ltr">{me.email}</bdi>. Sign out, then sign in as{' '}
          <bdi dir="ltr">{link.email}</bdi>.
        </>
      }
    >
      <Button onClick={() => void signOut()}>Sign out</Button>
    </Frame>
  )
}

/** A pending invitation, signed out: with automatic single sign-on, straight to the IdP with
 * the invited address as the login hint (DESIGN 8.1). Decided once, at mount: the attempt it
 * records would flip the answer on the next render. */
function AutoSignIn({
  children,
  ...input
}: Parameters<typeof autoSignInUrl>[0] & { children: ReactNode }) {
  const [url] = useState(() => autoSignInUrl(input))
  useEffect(() => {
    if (url) startAutoSignIn(url)
  }, [url])
  return url ? <SigningIn /> : children
}

export function InvitePage() {
  const { token } = useParams({ from: '/login/invite/$token' })
  const { manual } = useSearch({ from: '/login/invite/$token' })
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const meta = useQuery(metaQuery)
  const me = useQuery(meQuery)
  const link = useQuery({
    queryKey: ['invitation', token],
    queryFn: () => api.invitationLink(token),
    retry: (n, err) => !(err instanceof ApiError && err.status === 429) && n < 1,
  })
  // The page wears the inviting organisation's branding.
  const brand = useQuery({ ...brandQuery(link.data?.orgSlug ?? '_'), enabled: !!link.data?.orgSlug })
  useEffect(() => {
    if (brand.data) applyBrand(brand.data, '')
  }, [brand.data])

  if (link.isError)
    return (
      <Frame
        title="Couldn't open this invitation"
        description={
          link.error instanceof ApiError && link.error.status === 429
            ? 'Too many attempts. Wait a minute and try again.'
            : 'Check your connection and reload the page.'
        }
      />
    )
  if (link.isPending || me.isPending || meta.isPending)
    return (
      <main className="mx-auto flex w-full max-w-sm flex-col gap-4 px-4 py-8">
        <Skeleton className="h-56 w-full" />
      </main>
    )
  const data = link.data
  const signedIn = me.data ?? null
  const isMember = !!signedIn && signedIn.orgs.some((o) => o.slug === data.orgSlug)

  if (data.status === 'invalid')
    return (
      <Frame
        title="This invitation link doesn't work"
        description="It may have been cancelled, or a newer invitation email replaced it. Ask an admin of the organisation for a new one."
      >
        <ToSignIn />
      </Frame>
    )
  if (data.status === 'expired')
    return (
      <Frame
        title="This invitation has expired"
        description={
          <>
            Ask {data.invitedByName ? <bdi dir="auto">{data.invitedByName}</bdi> : 'an admin'} or another admin of{' '}
            {org(data)} to send a new one.
          </>
        }
      >
        <ToSignIn />
      </Frame>
    )
  if (data.status === 'accepted') {
    if (isMember) return <Joined link={data} />
    return (
      <Frame
        title="This invitation was already accepted"
        description={
          <>
            Sign in with <bdi dir="ltr">{data.email}</bdi> to open {org(data)}.
          </>
        }
      >
        <ToSignIn label="Sign in" />
      </Frame>
    )
  }

  // Pending.
  if (signedIn && signedIn.email.toLowerCase() === data.email?.toLowerCase()) return <AcceptNow token={token} link={data} />
  if (signedIn) return <WrongAccount link={data} me={signedIn} />

  const here = `/login/invite/${token}`
  return (
    <AutoSignIn features={meta.data?.features} manual={manual} next={here} loginHint={data.email}>
      <Frame
        title={<>Join {org(data)}</>}
        description={
          <>
            {data.invitedByName ? <bdi dir="auto">{data.invitedByName}</bdi> : 'An admin'} invited you as{' '}
            {ORG_ROLE_PHRASE[data.role ?? 'member']}.
          </>
        }
      >
        {meta.data?.features.oidc && (
          <Button asChild>
            <a href={ssoLoginUrl(here, data.email)} onClick={() => clearSignedOut()}>
              <KeyRoundIcon />
              Sign in with single sign-on
            </a>
          </Button>
        )}
        {meta.data?.features.localLogin && data.email && (
          <LocalLogin
            next="/forms"
            fixedEmail={data.email}
            onSignedIn={async () => {
              await queryClient.invalidateQueries({ queryKey: ['invitation', token] })
              toast(`You joined ${data.orgName ?? 'the organisation'}`)
              await navigate({ to: '/forms' })
            }}
          />
        )}
      </Frame>
    </AutoSignIn>
  )
}
