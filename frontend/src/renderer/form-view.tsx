/**
 * The respondent's form: wizard pages from the evaluated path, live logic, per-page validation
 * with an error summary, and the success / closed / error screens (PHASE-2-SCREENS 4).
 * Used by the public app and by the studio preview.
 */
import { AlertCircleIcon, ChevronLeftIcon, ChevronRightIcon, InfoIcon } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { BrandFooter } from '@/components/brand/brand-parts'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { DirectionProvider } from '@/components/ui/direction'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import { buildIndex } from '@/logic/form-index'
import { evaluate, type Evaluation } from '@/logic/engine'
import type { Brand, ThemeOptions } from '@/lib/branding'
import { cn } from '@/lib/utils'
import { displayText } from '@/thaana/display'
import { hasThaana } from '@yashau/thaana-react'
import type { Element, FieldElement, Form } from '@/schema'
import { contentProps, formLanguage } from '@/schema/language'

import { legibleAccent } from './accent'
import { DEFAULT_THEME, themeAttrs } from './theme'
import { padToMinRows, prefetchControls } from './util'
import {
  type AnswerPath,
  controlId,
  pathKey,
  RendererContext,
  type RendererContextValue,
  type Uploader,
} from './context'
import { FillElements } from './elements'
import { Markdown } from './markdown'
import { fmt, MSG as msgs } from './messages'
import { En, Msg } from './msg'
import { problemMessage, validateAnswer, type Problem as AnswerProblem } from './validation'

type Answers = Record<string, unknown>
type Row = Record<string, unknown>

/** One server-side problem (`backend/app/validation/answers.py` codes). */
export interface ServerError extends AnswerProblem {
  field: string
  repeater?: string
  row?: number
}

export type SubmitOutcome =
  | { ok: true; reference: string }
  | { ok: false; kind: 'network' | 'version' | 'closed' }
  | { ok: false; kind: 'invalid'; errors: ServerError[] }
  /** The caller showed its own message (e.g. a failed CAPTCHA); answers stay. */
  | { ok: false; kind: 'handled' }

export interface FormRendererProps {
  form: Form
  orgName?: string
  /** The organisation's branding (logo above the title, footer links). */
  brand?: Brand | null
  /** `preview`: nothing is posted; uploads stay in the browser. */
  mode: 'live' | 'preview'
  embed?: boolean
  onSubmit: (answers: Answers) => Promise<SubmitOutcome>
  uploader: Uploader
  /** Prefilled answers (hidden values from link parameters, saved progress). */
  initialAnswers?: Answers
  /** The page to start on (saved progress), used when it is on the respondent's path. */
  initialPage?: string
  /** Called after each change the respondent makes, with the answers and the current page. */
  onProgress?: (answers: Answers, pageId: string) => void
  /** Questions to wash with the marker, plus the "form was updated" notice. */
  highlighted?: ReadonlySet<string>
  /** Called with every evaluation (the studio preview shows a logic trace). */
  onEvaluate?: (ev: Evaluation | null, pageId: string) => void
  /** Wraps the sheet (the studio preview puts it in a device frame). */
  frame?: 'page' | 'bare'
  /** Shown under the form title (e.g. "Responding as …"). */
  notice?: ReactNode
  /** Shown above the submit button on the last page (e.g. a CAPTCHA). */
  beforeSubmit?: ReactNode
  /** Offer "Submit another response" after submitting (off for one-response forms). */
  allowAnother?: boolean
  /** The form theme's options (default: the brand's, i.e. what the public page got). */
  theme?: ThemeOptions | null
}

interface Problem {
  key: string
  path: AnswerPath
  message: string
  /** The question's label, so summary links say which question each problem is about. */
  label: string
}

/**
 * "Choose an option" twice in a summary is ambiguous: name the question unless the message does.
 * The label is form content (maybe Dhivehi), the message system text (English): each is isolated.
 */
function SummaryText({ pr }: { pr: Problem }): ReactNode {
  const label = pr.label.trim()
  // A builder's own pattern message is content (maybe Dhivehi); everything else is English.
  const message = /[\u0780-\u07bf]/.test(pr.message) ? <bdi>{pr.message}</bdi> : <En>{pr.message}</En>
  if (!label || pr.message.toLowerCase().includes(label.toLowerCase())) return message
  // "Which track interests you most?: Choose an option" reads badly: a question mark is enough.
  const sep = /[?:.!؟]$/.test(label) ? '' : ':'
  return (
    <>
      <bdi>
        {label}
        {sep}
      </bdi>{' '}
      {message}
    </>
  )
}

function safeEvaluate(form: Form, answers: Answers): Evaluation | null {
  try {
    return evaluate(form, answers)
  } catch {
    return null // a draft can contain a cycle; show everything rather than crash
  }
}

/** Fields (with repeater scope) inside a list of elements, depth first. */
function* fieldsIn(
  elements: Element[],
  scope?: { repeater: string; row: number },
): Generator<{ el: Element; scope?: { repeater: string; row: number } }> {
  for (const el of elements) {
    yield { el, scope }
    if (el.kind === 'section') yield* fieldsIn(el.elements ?? [], scope)
  }
}

function useStableCallback<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn)
  useEffect(() => {
    ref.current = fn
  })
  return useCallback((...args: A) => ref.current(...args), [])
}

export function FormRenderer({
  form,
  orgName,
  brand,
  mode,
  embed = false,
  onSubmit,
  uploader,
  initialAnswers,
  initialPage,
  onProgress,
  highlighted,
  onEvaluate,
  frame = 'page',
  notice,
  beforeSubmit,
  allowAnother = true,
  theme: themeProp,
}: FormRendererProps) {
  const theme = themeProp ?? brand?.theme ?? DEFAULT_THEME
  const language = formLanguage(form)
  const index = useMemo(() => buildIndex(form), [form])
  const [answers, setAnswers] = useState<Answers>(() => initialAnswers ?? {})
  const [errors, setErrors] = useState<Map<string, string>>(new Map())
  const [summary, setSummary] = useState<Problem[]>([])
  const [pageId, setPageId] = useState<string>(() => {
    const first = form.pages[0].id
    if (!initialPage || initialPage === first) return first
    return safeEvaluate(form, initialAnswers ?? {})?.path.includes(initialPage) ? initialPage : first
  })
  // Set by the respondent's own changes, so prefilled answers alone are never saved.
  const touched = useRef(false)
  const [uploading, setUploadingState] = useState<Set<string>>(new Set())
  const [phase, setPhase] = useState<'filling' | 'submitting' | 'done'>('filling')
  const [failure, setFailure] = useState<'network' | 'closed' | null>(null)
  const [reference, setReference] = useState<string | null>(null)
  const [announce, setAnnounce] = useState<ReactNode>(null)
  const summaryRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const sheetRef = useRef<HTMLDivElement>(null)
  const pageChanged = useRef(false)
  const barRef = useRef<HTMLElement>(null)

  // Rows shown for a repeater's minimum count are evaluated too, so their required questions
  // stop Next even before anything is typed in them.
  const ev = useMemo(
    () => safeEvaluate(form, padToMinRows(index.elements.values(), answers)),
    [form, index, answers],
  )
  const path = ev?.path.length ? ev.path : form.pages.map((p) => p.id)
  const pageIndexInPath = Math.max(0, path.indexOf(pageId))
  const page = form.pages.find((p) => p.id === pageId) ?? form.pages[0]
  const isLast = pageIndexInPath >= path.length - 1

  useEffect(() => {
    onEvaluate?.(ev, pageId)
  }, [ev, pageId, onEvaluate])

  useEffect(() => {
    const types = new Set<string>()
    for (const info of index.elements.values())
      types.add(info.element.kind === 'field' ? info.element.type : info.element.kind)
    prefetchControls(types)
    if (types.has('repeater')) void import('./repeater')
    if (language === 'dv') void import('./thaana-input')
  }, [index, language])

  const visibleSet = useMemo(() => new Set(ev?.visible ?? [...index.elements.keys()]), [ev, index])
  const requiredSet = useMemo(() => new Set(ev?.required ?? []), [ev])

  const isVisible = useCallback(
    (id: string, scope?: { repeater: string; row: number }) => {
      if (!ev) return true
      if (scope) return ev.rows[scope.repeater]?.[scope.row]?.visible.includes(id) ?? true
      return visibleSet.has(id)
    },
    [ev, visibleSet],
  )
  const isRequired = useCallback(
    (id: string, scope?: { repeater: string; row: number }) => {
      if (!ev) {
        const el = index.elements.get(id)?.element
        return el?.kind === 'field' && el.required === true
      }
      if (scope) return ev.rows[scope.repeater]?.[scope.row]?.required.includes(id) ?? false
      return requiredSet.has(id)
    },
    [ev, requiredSet, index],
  )

  // "(optional)" on optional questions when most are required; otherwise "(required)".
  const convention = useMemo(() => {
    let req = 0
    let total = 0
    for (const info of index.elements.values()) {
      const el = info.element
      if (el.kind !== 'field' || el.type === 'hidden') continue
      total++
      if (el.required || el.requiredIf) req++
    }
    return req * 2 >= total ? 'optional' : 'required'
  }, [index])

  const getValue = useCallback(
    (p: AnswerPath) => {
      if (p.repeater === undefined) return answers[p.id]
      const rows = answers[p.repeater]
      return Array.isArray(rows) ? (rows[p.row!] as Row | undefined)?.[p.id] : undefined
    },
    [answers],
  )

  const fieldOf = (id: string) => index.elements.get(id)?.element as FieldElement | undefined

  const check = useStableCallback((p: AnswerPath, value: unknown): string | null => {
    const field = fieldOf(p.id)
    if (!field || field.kind !== 'field') return null
    const scope = p.repeater !== undefined ? { repeater: p.repeater, row: p.row! } : undefined
    if (!isVisible(p.id, scope)) return null
    return validateAnswer(field, value, isRequired(p.id, scope))
  })

  // Answers the respondent has changed: blur only checks those (or ones already showing an
  // error), so leaving an untouched empty question, e.g. the row "Add" just focused, adds no
  // error above the next control. Next and Submit still check everything.
  const edited = useRef(new Set<string>())

  const setValue = useStableCallback((p: AnswerPath, value: unknown) => {
    touched.current = true
    edited.current.add(pathKey(p))
    setAnswers((prev) => {
      if (p.repeater === undefined) {
        const next = { ...prev }
        if (value === undefined) delete next[p.id]
        else next[p.id] = value
        return next
      }
      const rows = Array.isArray(prev[p.repeater]) ? [...(prev[p.repeater] as Row[])] : []
      const row = { ...(rows[p.row!] ?? {}) }
      if (value === undefined) delete row[p.id]
      else row[p.id] = value
      rows[p.row!] = row
      return { ...prev, [p.repeater]: rows }
    })
    setFailure(null)
    const key = pathKey(p)
    // Only clear errors while typing; new errors wait for blur or Next.
    setErrors((prev) => {
      if (!prev.has(key) || check(p, value) !== null) return prev
      const next = new Map(prev)
      next.delete(key)
      return next
    })
  })

  const blur = useStableCallback((p: AnswerPath) => {
    const key = pathKey(p)
    const message = check(p, getValue(p))
    setErrors((prev) => {
      if (message && !edited.current.has(key) && !prev.has(key)) return prev
      const next = new Map(prev)
      if (message) next.set(key, message)
      else next.delete(key)
      return next
    })
  })

  const setUploading = useCallback((key: string, busy: boolean) => {
    setUploadingState((prev) => {
      if (prev.has(key) === busy) return prev
      const next = new Set(prev)
      if (busy) next.add(key)
      else next.delete(key)
      return next
    })
  }, [])

  const rowCount = useCallback(
    (repeaterId: string) => {
      const rows = answers[repeaterId]
      const rep = index.elements.get(repeaterId)?.element
      const min = rep?.kind === 'repeater' ? (rep.minRows ?? 0) : 0
      return Math.max(Array.isArray(rows) ? rows.length : 0, min)
    },
    [answers, index],
  )
  const addRow = useStableCallback((repeaterId: string) => {
    const n = rowCount(repeaterId)
    touched.current = true
    setAnswers((prev) => {
      const rows = Array.isArray(prev[repeaterId]) ? [...(prev[repeaterId] as Row[])] : []
      while (rows.length < n + 1) rows.push({})
      return { ...prev, [repeaterId]: rows }
    })
    // Focus the new row's first control once it renders.
    window.setTimeout(() => {
      const rep = index.elements.get(repeaterId)?.element
      const first = rep?.kind === 'repeater' ? rep.elements?.find((e) => e.kind === 'field') : undefined
      if (first) document.getElementById(controlId({ id: first.id, repeater: repeaterId, row: n }))?.focus()
    }, 0)
  })
  const removeRow = useStableCallback((repeaterId: string, row: number) => {
    touched.current = true
    setAnswers((prev) => {
      const rows = Array.isArray(prev[repeaterId]) ? [...(prev[repeaterId] as Row[])] : []
      rows.splice(row, 1)
      return { ...prev, [repeaterId]: rows }
    })
    setErrors((prev) => new Map([...prev].filter(([k]) => !k.startsWith(`${repeaterId}.`))))
    window.setTimeout(() => {
      const next = document.getElementById(`${repeaterId}-row-${row}`)
      next?.focus()
    }, 0)
  })

  const ctx: RendererContextValue = {
    form,
    language,
    mode: 'fill',
    convention,
    getValue,
    setValue,
    blur,
    errorFor: (p) => errors.get(pathKey(p)) ?? null,
    isVisible,
    isRequired,
    highlighted: highlighted ?? new Set(),
    uploader,
    setUploading,
    rowCount,
    addRow,
    removeRow,
  }

  /** Validate every visible question on a page; returns the problems in page order. */
  const problemsOn = (pageEls: Element[]): Problem[] => {
    const out: Problem[] = []
    const visit = (els: Element[], scope?: { repeater: string; row: number }) => {
      for (const { el, scope: s } of fieldsIn(els, scope)) {
        if (!isVisible(el.id, s)) continue
        if (el.kind === 'repeater') {
          for (let row = 0; row < rowCount(el.id); row++)
            visit(el.elements ?? [], { repeater: el.id, row })
          continue
        }
        if (el.kind !== 'field' || el.type === 'hidden') continue
        const p: AnswerPath = s ? { id: el.id, ...s } : { id: el.id }
        const message = validateAnswer(el, getValue(p), isRequired(el.id, s))
        if (message) out.push({ key: pathKey(p), path: p, message, label: el.label })
      }
    }
    visit(pageEls)
    return out
  }

  const showProblems = (problems: Problem[]) => {
    setErrors(new Map(problems.map((pr) => [pr.key, pr.message])))
    setSummary(problems)
    window.setTimeout(() => {
      summaryRef.current?.focus()
      summaryRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    }, 0)
  }

  const pageUploading = [...uploading].some((key) => {
    const id = key.includes('.') ? key.split('.')[0] : key
    return index.elements.get(id)?.pageIndex === form.pages.indexOf(page)
  })

  const goTo = (id: string) => {
    setPageId(id)
    setSummary([])
    pageChanged.current = true
    const nextPage = form.pages.find((p) => p.id === id)
    const n = path.indexOf(id) + 1
    setAnnounce(
      <>
        <En>{fmt(msgs.stepOf, { n, total: path.length })}</En>
        {nextPage?.title && <>: {nextPage.title}</>}
      </>,
    )
  }

  useEffect(() => {
    if (!pageChanged.current) return
    pageChanged.current = false
    sheetRef.current?.scrollIntoView({ block: 'start' })
    titleRef.current?.focus({ preventScroll: true })
  }, [pageId])

  // Phones: the sticky Back / Next bar must never cover the focused field (WCAG 2.4.11). The bar's
  // height feeds scroll-padding (index.css); a field focused under it is scrolled to the centre.
  useEffect(() => {
    const bar = barRef.current
    if (frame !== 'page' || !bar) return
    const root = document.documentElement
    const measure = () => root.style.setProperty('--df-bar-h', `${bar.offsetHeight}px`)
    measure()
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    ro?.observe(bar)
    const onFocus = (e: FocusEvent) => {
      const el = e.target
      if (!(el instanceof HTMLElement) || bar.contains(el) || getComputedStyle(bar).position !== 'sticky') return
      const vv = window.visualViewport
      const bottom = Math.min(bar.getBoundingClientRect().top, vv ? vv.offsetTop + vv.height : Infinity)
      if (el.getBoundingClientRect().bottom > bottom - 8) el.scrollIntoView({ block: 'center' })
    }
    const sheet = sheetRef.current
    sheet?.addEventListener('focusin', onFocus)
    return () => {
      ro?.disconnect()
      sheet?.removeEventListener('focusin', onFocus)
    }
  }, [frame, phase])

  const submit = async () => {
    setPhase('submitting')
    setFailure(null)
    const outcome = await onSubmit(answers).catch(
      (): SubmitOutcome => ({ ok: false, kind: 'network' }),
    )
    if (outcome.ok) {
      setReference(outcome.reference)
      setPhase('done')
      window.scrollTo({ top: 0 })
      return
    }
    setPhase('filling')
    if (outcome.kind === 'invalid') {
      const problems = outcome.errors.map((e) => {
        const p: AnswerPath =
          e.repeater !== undefined ? { id: e.field, repeater: e.repeater, row: e.row } : { id: e.field }
        const field = fieldOf(e.field)
        return {
          key: pathKey(p),
          path: p,
          message: field ? problemMessage(field, e) : msgs.answerThis,
          label: field?.label ?? '',
        }
      })
      // Jump to the first page with a problem.
      const firstPage = problems.length ? index.elements.get(problems[0].path.id)?.pageIndex : undefined
      if (firstPage !== undefined) setPageId(form.pages[firstPage].id)
      showProblems(problems)
    } else if (outcome.kind === 'closed') setFailure('closed')
    else if (outcome.kind === 'network') setFailure('network')
  }

  const next = () => {
    const problems = problemsOn(page.elements ?? [])
    if (problems.length) {
      showProblems(problems)
      return
    }
    setSummary([])
    if (isLast) void submit()
    else goTo(path[pageIndexInPath + 1])
  }

  const back = () => {
    if (pageIndexInPath > 0) goTo(path[pageIndexInPath - 1])
  }

  // Leaving with answers entered asks first.
  const dirty = Object.keys(answers).length > 0 && phase !== 'done'
  useEffect(() => {
    if (mode !== 'live' || !dirty) return
    const handler = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty, mode])

  // "{n} more questions" once, when logic reveals questions on this page.
  const visibleOnPage = (page.elements ?? []).filter((el) => isVisible(el.id)).length
  const lastVisible = useRef(visibleOnPage)
  const lastPage = useRef(pageId)
  useEffect(() => {
    if (lastPage.current === pageId && visibleOnPage > lastVisible.current) {
      const n = visibleOnPage - lastVisible.current
      setAnnounce(<En>{n === 1 ? msgs.oneMoreQuestion : fmt(msgs.moreQuestions, { n })}</En>)
    }
    lastVisible.current = visibleOnPage
    lastPage.current = pageId
  }, [visibleOnPage, pageId])

  useEffect(() => {
    if (touched.current && phase === 'filling') onProgress?.(answers, pageId)
  }, [answers, pageId, phase, onProgress])

  const resetForm = () => {
    touched.current = false
    edited.current = new Set()
    setAnswers(initialAnswers ?? {})
    setErrors(new Map())
    setSummary([])
    setPageId(form.pages[0].id)
    setReference(null)
    setPhase('filling')
  }

  const multiPage = form.pages.length > 1
  const total = path.length
  const n = pageIndexInPath + 1

  const body =
    phase === 'done' || failure === 'closed' ? (
      // The outcome keeps the form's logo and title, so respondents know which form it was.
      <>
        <div className="flex flex-col gap-1">
          {!embed && <FormLogo form={form} brand={brand} theme={theme} />}
          <p className="text-base text-muted-foreground">{displayText(form.settings.title, language)}</p>
        </div>
        {phase === 'done' ? (
          <SuccessScreen form={form} reference={reference ?? ''} onAnother={allowAnother ? resetForm : undefined} />
        ) : (
          <StatusScreen title={msgs.closedTitle} body={msgs.closedBody} />
        )}
      </>
    ) : (
      <>
        <FormHeader
          form={form}
          orgName={orgName}
          brand={embed ? null : brand}
          theme={embed ? { ...theme, headerImageUrl: null } : theme}
        />
        {notice}
        {multiPage && theme.progressStyle !== 'none' && (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-muted-foreground tabular-nums">
              <Msg t={msgs.stepOf} params={{ n, total }} />
            </p>
            {theme.progressStyle === 'bar' && (
              <Progress
                value={(n / total) * 100}
                aria-label={fmt(msgs.stepOf, { n, total })}
                lang="en"
                className="h-1.5 bg-secondary rtl:-scale-x-100"
              />
            )}
          </div>
        )}
        <Separator />
        <div
          key={pageId}
          className="flex flex-col gap-[var(--df-gap,2rem)] duration-120 animate-in fade-in motion-reduce:animate-none"
        >
          {(page.title || page.description) && (
            <div className="flex flex-col gap-1">
              {page.title && (
                <h2
                  ref={titleRef}
                  tabIndex={-1}
                  className={cn(
                    'df-page-title text-xl outline-none',
                    language === 'dv' ? 'font-bold' : 'font-[650] tracking-tight',
                  )}
                >
                  {displayText(page.title, language)}
                </h2>
              )}
              {page.description && (
                <Markdown text={page.description} className="max-w-xl text-base text-muted-foreground" rtl={language === 'dv'} />
              )}
            </div>
          )}
          {highlighted && highlighted.size > 0 && (
            <Alert>
              <InfoIcon />
              <AlertDescription className="text-base">
                <En>{msgs.versionChanged}</En>
              </AlertDescription>
            </Alert>
          )}
          {summary.length > 0 && (
            <Alert
              variant="destructive"
              ref={summaryRef}
              tabIndex={-1}
              role={undefined}
              className="border-destructive outline-none focus-visible:ring-3 focus-visible:ring-destructive/30"
            >
              <AlertCircleIcon />
              <AlertTitle className="text-base font-semibold">
                <En>{summary.length === 1 ? msgs.problemOne : fmt(msgs.problemMany, { n: summary.length })}</En>
              </AlertTitle>
              <AlertDescription>
                <ul className="flex list-disc flex-col ps-5 text-base">
                  {summary.map((pr) => (
                    <li key={pr.key}>
                      <a
                        href={`#${controlId(pr.path)}`}
                        className="inline-flex flex-wrap items-baseline gap-x-1.5 py-2.5 text-destructive underline underline-offset-4"
                        onClick={(e) => {
                          e.preventDefault()
                          const el = document.getElementById(controlId(pr.path))
                          el?.scrollIntoView({ block: 'center' })
                          el?.focus()
                        }}
                      >
                        <SummaryText pr={pr} />
                      </a>
                    </li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}
          <FillElements elements={page.elements ?? []} />
        </div>
        {isLast && beforeSubmit}
        {failure === 'network' && (
          <Alert variant="destructive" className="border-destructive">
            <AlertCircleIcon />
            <AlertDescription className="text-base">
              <En>{msgs.submitFailed}</En>
            </AlertDescription>
          </Alert>
        )}
        <nav
          ref={barRef}
          aria-label={msgs.next}
          lang="en"
          data-df-sticky-bar={frame === 'page' || undefined}
          className={cn(
            'flex items-center gap-3',
            frame === 'page' &&
              'max-md:sticky max-md:bottom-0 max-md:-mx-5 max-md:border-t max-md:bg-card max-md:px-5 max-md:py-3 max-md:pb-[max(0.75rem,env(safe-area-inset-bottom))]',
          )}
        >
          {pageIndexInPath > 0 && (
            <Button type="button" variant="outline" className="h-12 px-4 text-base" onClick={back}>
              <ChevronLeftIcon className="rtl:rotate-180" />
              {form.settings.backLabel?.trim() ? (
                <bdi {...contentProps(language)}>{form.settings.backLabel.trim()}</bdi>
              ) : (
                <En>{msgs.back}</En>
              )}
            </Button>
          )}
          <Button
            type="button"
            className={cn('ms-auto h-12 px-5 text-base', theme.buttonFullWidth && 'max-md:flex-1')}
            onClick={next}
            disabled={pageUploading || phase === 'submitting'}
            aria-describedby={pageUploading ? 'upload-wait' : undefined}
          >
            {isLast && form.settings.submitLabel?.trim() ? (
              <bdi {...contentProps(language)}>{form.settings.submitLabel.trim()}</bdi>
            ) : !isLast && form.settings.nextLabel?.trim() ? (
              <bdi {...contentProps(language)}>{form.settings.nextLabel.trim()}</bdi>
            ) : (
              <En>{isLast ? msgs.submit : msgs.next}</En>
            )}
            {!isLast && <ChevronRightIcon className="rtl:rotate-180" />}
          </Button>
        </nav>
        {pageUploading && (
          <p id="upload-wait" className="text-sm text-muted-foreground">
            <En>{msgs.waitUploads}</En>
          </p>
        )}
      </>
    )

  const accent = legibleAccent(form.settings.theme?.accent)
  return (
    <RendererContext.Provider value={ctx}>
      <DirectionProvider dir={contentProps(language).dir}>
        <div
          {...contentProps(language)}
          {...themeAttrs(theme)}
          data-df-frame={frame === 'page' && !embed ? 'page' : undefined}
          data-accent={accent ? '' : undefined}
          style={accent ? ({ '--form-accent': accent } as React.CSSProperties) : undefined}
          className={cn(
            'text-base text-foreground',
            frame === 'page' && !embed && 'min-h-svh bg-background md:px-6 md:py-12',
            embed && 'bg-transparent',
          )}
        >
          <div
            ref={sheetRef}
            className={cn(
              '@container mx-auto flex w-full max-w-[var(--df-page-width,40rem)] flex-col gap-6 bg-card p-5 md:p-10',
              frame === 'page' && !embed && 'md:rounded-md md:border',
              embed && 'bg-transparent p-0 md:p-0',
            )}
          >
            {body}
          </div>
          {frame === 'page' && !embed && <BrandFooter brand={brand} madeWith={msgs.madeWith} />}
          {/* start-0: in RTL an unanchored sr-only box sits past the right edge (1px scroll at 320px). */}
          <div className="sr-only start-0 top-0" aria-live="polite">
            {announce}
          </div>
        </div>
      </DirectionProvider>
    </RendererContext.Provider>
  )
}

const LOGO_SIZE = { s: 'h-6 max-w-32', m: 'h-8 max-w-48', l: 'h-14 max-w-80' } as const
const LOGO_PLACE = { start: 'justify-start', center: 'justify-center', end: 'justify-end' } as const

/** The form's logo (its own, else the organisation's) at the theme's size and position, linked
 * when the theme sets a link. */
function FormLogo({ form, brand, theme }: { form: Form; brand?: Brand | null; theme: ThemeOptions }) {
  const own = theme.logoUrl !== undefined
  const url = own ? theme.logoUrl : brand?.logoUrl
  const dark = own ? theme.logoDarkUrl : brand?.logoDarkUrl
  if (!url || theme.logoPlacement === 'hidden') return null
  const alt = theme.logoOwn ? form.settings.title : (brand?.name ?? form.settings.title)
  const img = cn('block w-auto object-contain', LOGO_SIZE[theme.logoSize ?? 'm'])
  const pictures = (
    <>
      <img src={url} alt={theme.logoLink ? '' : alt} className={cn(img, dark && 'dark:hidden')} />
      {dark && <img src={dark} alt={theme.logoLink ? '' : alt} className={cn(img, 'hidden dark:block')} />}
    </>
  )
  return (
    <div className={cn('mb-2 flex', LOGO_PLACE[theme.logoPlacement] ?? 'justify-start')}>
      {theme.logoLink ? (
        <a
          href={theme.logoLink}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`${alt}, opens in a new tab`}
          lang="en"
          className="inline-flex min-h-11 items-center rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {pictures}
        </a>
      ) : (
        pictures
      )}
    </div>
  )
}

export function FormHeader({
  form,
  orgName,
  brand,
  theme = DEFAULT_THEME,
  title,
  description,
}: {
  form: Form
  orgName?: string
  brand?: Brand | null
  theme?: ThemeOptions
  /** Builder: the title and description, edited in place. */
  title?: ReactNode
  description?: ReactNode
}) {
  const language = formLanguage(form)
  const logo = theme.logoPlacement !== 'hidden'
  const center = theme.logoPlacement === 'center'
  const hasLogo = theme.logoUrl !== undefined ? !!theme.logoUrl : !!brand?.logoUrl
  return (
    <header className="flex flex-col gap-2">
      {theme.headerImageUrl && (
        <img
          src={theme.headerImageUrl}
          alt=""
          className="-mx-5 -mt-5 mb-2 aspect-[3/1] w-[calc(100%+2.5rem)] max-w-none object-cover md:-mx-10 md:-mt-10 md:w-[calc(100%+5rem)] md:rounded-t-md"
        />
      )}
      {logo && hasLogo ? (
        <FormLogo form={form} brand={brand} theme={theme} />
      ) : logo && orgName && (
        <p
          className={cn('text-sm text-muted-foreground', center && 'text-center', theme.logoPlacement === 'end' && 'text-end')}
          lang={hasThaana(orgName) ? 'dv' : 'en'}
        >
          {orgName}
        </p>
      )}
      <h1
        className={cn(
          'df-title text-2xl font-bold sm:text-3xl',
          language === 'en' && 'tracking-tight',
        )}
      >
        {title ?? displayText(form.settings.title, language)}
      </h1>
      {description !== undefined
        ? description
        : form.settings.description && (
            <Markdown text={form.settings.description} className="max-w-xl text-base text-muted-foreground" rtl={language === 'dv'} />
          )}
    </header>
  )
}

/** Outcome screens are a lazy chunk: every respondent sees one at most once, at the end. */
const LazySuccess = lazy(() => import('./outcome').then((m) => ({ default: m.SuccessScreen })))
const LazyStatus = lazy(() => import('./outcome').then((m) => ({ default: m.StatusScreen })))

function SuccessScreen(props: { form: Form; reference: string; onAnother?: () => void }) {
  return (
    <Suspense fallback={null}>
      <LazySuccess {...props} />
    </Suspense>
  )
}

/** A closed / not found / error screen. Title and body are system text (English). */
export function StatusScreen(props: { title: string; body: string; action?: ReactNode }) {
  return (
    <Suspense fallback={null}>
      <LazyStatus {...props} />
    </Suspense>
  )
}
