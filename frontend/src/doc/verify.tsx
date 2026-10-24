/**
 * Public verify page (`/v/{token}`, APPROVALS-SCREENS 5): is this document genuine and its
 * record unchanged? Status only: issuer, reference, dates and the approval outcome, never
 * answers or personal data. Kept tiny: plain elements plus `Button` and `Alert`. All of it is
 * system text, so the page is English and left to right for every form; only the organisation
 * name may be Thaana.
 */
import { BadgeCheckIcon, CircleHelpIcon, FileUpIcon, XIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { applyBrand, type Brand } from '@/lib/branding'
import { loadThaanaFont } from '@/lib/thaana-font'
import { Msg } from '@/renderer/msg'
import { DOC as msgs, fmt, formatDay, scriptLang } from './messages'
import { Page } from './page'

export interface ApprovalSummary {
  state: 'pending' | 'waiting' | 'approved' | 'rejected' | 'stopped'
  step: number
  total: number
  decidedAt: string | null
}

interface VerifyInfo {
  state: 'genuine' | 'changed'
  orgName: string
  brand?: Brand
  reference: string
  issuedAt: string | null
  approval: ApprovalSummary | null
  thaanaFontCssUrl: string
}

type Load = { kind: 'ok'; info: VerifyInfo } | { kind: 'not_found' } | { kind: 'error' } | null

type CopyResult = 'genuine' | 'older' | 'modified' | 'different' | 'not_ours' | 'changed'

function approvalText(a: ApprovalSummary): ReactNode {
  if (a.state === 'approved' && a.decidedAt) return <Msg t={msgs.approvedOn} params={{ date: formatDay(a.decidedAt) }} />
  if (a.state === 'rejected' && a.decidedAt) return <Msg t={msgs.rejectedOn} params={{ date: formatDay(a.decidedAt) }} />
  if (a.state === 'stopped') return msgs.stopped
  return <Msg t={msgs.inProgress} params={{ n: a.step, total: a.total }} />
}

function CheckCopy({ token, info }: { token: string; info: VerifyInfo }) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)
  const check = async (file: File) => {
    setBusy(true)
    setResult(null)
    try {
      const res = await fetch(`/api/v1/public/verify/${encodeURIComponent(token)}/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/pdf', Accept: 'application/json' },
        referrerPolicy: 'no-referrer',
        body: file,
      })
      if (res.status === 429) return setResult({ ok: false, text: msgs.tooMany })
      if (res.status === 413) return setResult({ ok: false, text: msgs.tooLarge })
      if (!res.ok) return setResult({ ok: false, text: msgs.checkFailed })
      const r = ((await res.json()) as { result: CopyResult }).result
      const text =
        r === 'older' && info.issuedAt
          ? fmt(msgs.result_older, { date: formatDay(info.issuedAt) })
          : msgs[`result_${r}`]
      setResult({ ok: r === 'genuine' || r === 'older', text })
    } catch {
      setResult({ ok: false, text: msgs.checkFailed })
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }
  return (
    <section className="flex flex-col gap-3" aria-labelledby="check-copy">
      <h2 id="check-copy" className="text-lg font-semibold">
        {msgs.checkCopy}
      </h2>
      <p className="text-muted-foreground">{msgs.checkCopyHint}</p>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void check(file)
        }}
      />
      <Button type="button" variant="outline" className="h-12 self-start text-base sm:h-11" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <Spinner /> : <FileUpIcon />}
        {busy ? msgs.checking : msgs.choosePdf}
      </Button>
      <div aria-live="polite">
        {result && (
          <Alert variant={result.ok ? 'default' : 'destructive'}>
            {result.ok ? <BadgeCheckIcon /> : <XIcon />}
            <AlertDescription className="text-base text-foreground">{result.text}</AlertDescription>
          </Alert>
        )}
      </div>
    </section>
  )
}

export function VerifyPage({ token }: { token: string }) {
  const [load, setLoad] = useState<Load>(token ? null : { kind: 'not_found' })
  useEffect(() => {
    if (!token) return
    fetch(`/api/v1/public/verify/${encodeURIComponent(token)}`, {
      headers: { Accept: 'application/json' },
      referrerPolicy: 'no-referrer',
    })
      .then(async (res) => {
        if (res.status === 404) return setLoad({ kind: 'not_found' })
        if (!res.ok) return setLoad({ kind: 'error' })
        const info = (await res.json()) as VerifyInfo
        loadThaanaFont(scriptLang(info.orgName) === 'dv' ? info.thaanaFontCssUrl : null)
        applyBrand(info.brand ?? null, msgs.verifyTitle)
        setLoad({ kind: 'ok', info })
      })
      .catch(() => setLoad({ kind: 'error' }))
  }, [token])

  useEffect(() => {
    document.title = msgs.verifyTitle
  }, [])

  if (load === null) return <Page />
  if (load.kind !== 'ok') {
    const notFound = load.kind === 'not_found'
    return (
      <Page>
        <div className="flex items-start gap-3">
          <CircleHelpIcon className="mt-1 size-7 shrink-0 text-muted-foreground" aria-hidden />
          <div className="flex flex-col gap-2">
            <h1 className="text-2xl font-bold">{notFound ? msgs.notFoundTitle : msgs.verifyTitle}</h1>
            <p className="text-muted-foreground">{notFound ? msgs.notFoundBody : msgs.loadFailed}</p>
          </div>
        </div>
      </Page>
    )
  }

  const { info } = load
  const genuine = info.state === 'genuine'
  const rows: [string, ReactNode][] = [[msgs.reference, <bdi key="ref" dir="ltr">{info.reference}</bdi>]]
  if (info.issuedAt) rows.push([msgs.issued, formatDay(info.issuedAt)])
  if (info.approval) rows.push([msgs.approval, approvalText(info.approval)])
  return (
    <Page brand={info.brand}>
      <div className="flex items-start gap-3">
        {genuine ? (
          <BadgeCheckIcon className="mt-1 size-8 shrink-0 text-primary" aria-hidden />
        ) : (
          <XIcon className="mt-1 size-8 shrink-0 text-destructive" aria-hidden />
        )}
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-2xl font-bold">{genuine ? msgs.genuineTitle : msgs.changedTitle}</h1>
          {info.orgName && (
            <p className="text-muted-foreground">
              <Msg t={msgs.issuedBy} params={{ org: <bdi lang={scriptLang(info.orgName)}>{info.orgName}</bdi> }} />
            </p>
          )}
        </div>
      </div>
      {!genuine && <p className="text-destructive">{msgs.changedBody}</p>}
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2 text-base">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="border-t pt-6 text-muted-foreground">{msgs.about}</p>
      <CheckCopy token={token} info={info} />
    </Page>
  )
}
