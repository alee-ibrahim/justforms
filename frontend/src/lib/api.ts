import type { Operation } from 'fast-json-patch'

import type { Form, FormLanguage } from '@/schema'

import type { Brand, ThemeOptions } from './branding'
import type { Appearance } from './color-scheme'

/** Error from the API; `detail` is the server's error code (e.g. "revision_conflict"). */
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  readonly body: unknown

  constructor(status: number, body: unknown) {
    const detail = (body as { detail?: unknown } | null)?.detail
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.status = status
    this.detail = detail
    this.body = body
  }
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)justforms_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (UNSAFE.has(method)) headers['X-CSRF-Token'] = csrfToken()
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 204) return undefined as T
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

/** Upload a raw file body (branding images). */
async function upload<T>(path: string, file: File): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method: 'PUT',
    headers: { Accept: 'application/json', 'Content-Type': file.type || 'application/octet-stream', 'X-CSRF-Token': csrfToken() },
    credentials: 'same-origin',
    body: file,
  })
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

// -- payload types (mirror backend/app/api/v1) ---------------------------------------------

export type BrandImageKind = 'logo' | 'logo_dark' | 'icon'

export interface BrandImage {
  url: string
  mime: string
  width: number
  height: number
  /** Uploaded by the organisation (false: the instance default). */
  own: boolean
}

export interface PaletteMode {
  primary: string
  foreground: string
  contrast: number
  foregroundContrast: number
}

export interface PaletteReport {
  chosen: string
  adjusted: boolean
  light: PaletteMode
  dark: PaletteMode
  warnings: string[]
  lightTokens?: Record<string, string>
  darkTokens?: Record<string, string>
}

export interface BrandingSettings {
  displayName: string
  primaryColor: string | null
  supportUrl: string
  hidePoweredBy: boolean
}

export interface Branding extends BrandingSettings {
  images: Record<BrandImageKind, BrandImage | null>
  canHidePoweredBy: boolean
  canEdit: boolean
  effective: Brand
  palette: PaletteReport | null
  instance: { name: string; primaryColor: string | null; supportUrl: string | null }
}

/** Organisation roles (DESIGN 7): admin > creator (can create forms) > member. */
export type OrgRole = 'admin' | 'creator' | 'member'
export type FormRole = 'owner' | 'editor' | 'viewer'
export type FormStatus = 'draft' | 'live' | 'closed' | 'archived'
export type AccessMode = 'public' | 'otp' | 'staff'
export type CaptchaMode = 'off' | 'always' | 'auto'
export type CaptchaProvider = 'none' | 'altcha' | 'turnstile' | 'hcaptcha'

export interface Meta {
  version: string
  features: {
    ai: boolean
    /** The AI model can read images ("Start from a paper form"). */
    aiVision: boolean
    /** Who receives what the AI is sent, e.g. "Google Gemini". */
    aiProviderLabel: string
    oidc: boolean
    /** Signed-out visitors go straight to the IdP (JUSTFORMS_OIDC_AUTO_REDIRECT). */
    oidcAutoRedirect: boolean
    localLogin: boolean
    /** A demo sign-in code is configured (demo instances only). */
    demo: boolean
    /** Email can be sent (SMTP configured). */
    email: boolean
    captcha: CaptchaProvider
    captchaBusyThreshold: number
  }
  thaanaFontCssUrl: string
}

export interface Me {
  id: string
  email: string
  displayName: string
  isSuperadmin: boolean
  appearance: Appearance
  orgs: { id: string; name: string; slug: string; role: OrgRole }[]
}

export interface FormSummary {
  id: string
  orgId: string
  orgSlug: string
  slug: string
  /** The public address, https://<host>/<slug>. */
  url: string
  title: string
  status: FormStatus
  accessMode: AccessMode
  draftRevision: number
  currentVersion: number | null
  role: FormRole
  embedOrigins: string[]
  retentionDays: number | null
  otpAllowedDomains: string[]
  otpOneResponse: boolean
  captcha: CaptchaMode
  /** Respondents' answers are kept in their browser while they fill in the form. */
  saveProgress: boolean
  saveProgressDays: number
  /** Questions shown on submission cards (null: chosen automatically). */
  cardFields?: string[] | null
  /** Older versions' fixed questions read as rows of a newer repeater in the export (DESIGN 15.2). */
  versionMappings?: { repeater: string; rows: Record<string, string>[] }[]
  /** "Ask your submissions" may send the text of answers to the AI provider (Settings › AI). */
  aiReadAnswers?: boolean
  submissionCount: number
  newCount: number
  createdAt: string
  updatedAt: string
}

export interface PersonRef {
  id: string
  name: string
  email: string
}

/** A row of the forms list: the form plus owner and activity (docs/ux/FORMS-LIST-SCREENS.md). */
export interface FormListItem extends FormSummary {
  language: FormLanguage
  /** Published, and the draft differs from the live version. */
  hasUnpublishedChanges: boolean
  /** The creator while they are an owner, else the earliest owner. */
  owner: PersonRef | null
  ownerCount: number
  /** The viewer holds an explicit owner grant (admins own every form implicitly). */
  ownedByMe: boolean
  /** Submissions in the last 7 days. */
  recentCount: number
  approvalsOn: boolean
  pendingApprovalCount: number
  lastSubmissionAt: string | null
  lastEditedAt: string
  lastEditedBy: PersonRef | null
  importedFrom: string | null
}

/** A form theme: every value optional, missing = inherit (backend app/schemas/theme.py). */
export interface ThemeColors {
  primary?: string
  background?: string
  surface?: string
  text?: string
  mutedText?: string
  border?: string
  error?: string
}

export interface FormTheme {
  colors: ThemeColors
  latinFont?: 'atkinson' | 'inter' | 'ibm-plex-sans' | 'source-serif-4' | 'noto-sans'
  thaanaFont?: string
  textSize?: 's' | 'm' | 'l' | 'xl'
  headingScale?: 'compact' | 'standard' | 'large'
  radius?: 'none' | 'small' | 'medium' | 'large'
  density?: 'compact' | 'comfortable' | 'roomy'
  pageWidth?: 'narrow' | 'standard' | 'wide'
  buttonStyle?: 'filled' | 'outline'
  buttonFullWidth?: boolean
  inputStyle?: 'outlined' | 'filled' | 'underlined'
  progressStyle?: 'bar' | 'steps' | 'none'
  colorScheme?: 'light' | 'dark' | 'auto'
  logoPlacement?: 'start' | 'center' | 'end' | 'hidden'
  logoSize?: 's' | 'm' | 'l'
  /** http(s) address the logo links to. */
  logoLink?: string
  headerImage?: string
  backgroundImage?: string
}

export type ResolvedTheme = Required<Omit<FormTheme, 'colors' | 'headerImage' | 'backgroundImage' | 'logoLink'>> & {
  logoLink: string | null
  headerImage: string | null
  backgroundImage: string | null
}

export interface ThemeAdjustment {
  color: keyof ThemeColors
  chosen: string
  used: string
  contrast: number
  needed: number
}

export interface ThemeReport {
  light: Record<string, string>
  dark: Record<string, string>
  fonts: string[]
  options: ThemeOptions
  resolved: ResolvedTheme
  adjustments: ThemeAdjustment[]
}

export interface ThemeFont {
  id: string
  name: string
  family: string
  cssUrl: string | null
}

/** Form › Settings › Sharing preview (docs/ux/SHARING-PREVIEW-SCREENS.md). */
export interface SharingOut {
  title: string | null
  description: string | null
  effectiveTitle: string
  effectiveDescription: string
  defaultTitle: string
  defaultDescription: string
  siteName: string
  url: string
  language: FormLanguage
  imageUrl: string
  customImage: { width: number; height: number } | null
  published: boolean
  canEdit: boolean
}

export interface ThemeOut {
  theme: FormTheme
  canEdit: boolean
  fonts: { latin: ThemeFont[]; thaana: ThemeFont[] }
  fontSource: string | null
  preview: ThemeReport
  organisation: { theme: FormTheme; resolved: ResolvedTheme } | null
  effective: FormTheme | null
  /** Form endpoints: the form's own logo (null: it shows the organisation's). */
  logo?: { url: string; mime: string; width: number; height: number } | null
}

export interface SlugCheck {
  slug: string
  available: boolean
  problem: 'invalid' | 'reserved' | 'taken' | null
  suggestion: string | null
  url: string
}

export interface Draft {
  schema: Form
  revision: number
  canUndo: boolean
  canRedo: boolean
}

/** A piece of a change's text: form-language content (labels, options) or English words. */
export interface DiffPiece {
  text: string
  content: boolean
}

export type DiffStatus = 'added' | 'removed' | 'changed' | 'moved'

export interface PropertyChange {
  property: string
  /** English name of the property ("Label", "Help text", "Shown when"). */
  name: string
  kind: string
  before: DiffPiece[] | null
  after: DiffPiece[] | null
  summary: string
  options?: {
    added: { value: string; label: string }[]
    removed: { value: string; label: string }[]
    renamed: { value: string; before: string; after: string }[]
    reordered: boolean
  }
}

export interface ElementChange {
  id: string
  kind: 'field' | 'content' | 'section' | 'repeater'
  type: string
  typeName: string
  label: string
  /** Sections and repeaters it sits in, outermost first (form content). */
  within: string[]
  status: DiffStatus
  summary: string
  changes: PropertyChange[]
  /** Where it was before it moved to another page or container. */
  movedFrom: DiffPiece[] | null
  moveSummary?: string
}

export interface PageChange {
  pageId: string
  number: number
  title: string
  /** null: the page itself is unchanged, only questions on it changed. */
  status: DiffStatus | null
  summary: string
  movedFrom: number | null
  changes: PropertyChange[]
  elements: ElementChange[]
}

/** GET /draft/changes: what publishing would change, against the live version. */
export interface DraftChanges {
  /** null before the first publish. */
  baseVersion: number | null
  revision: number
  hasChanges: boolean
  summary: string
  counts: Record<DiffStatus, number>
  language: 'en' | 'dv'
  settings: PropertyChange[]
  pages: PageChange[]
}

export interface Version {
  id: string
  version: number
  schemaHash: string
  publishedAt: string
  publishedByName: string | null
}

export interface PublishIssue {
  code: string
  message: string
  target: string | null
}

export type SubmissionStatus = 'new' | 'in_review' | 'approved' | 'rejected'

export interface SubmissionSummary {
  id: string
  seq: number
  status: SubmissionStatus
  language: FormLanguage
  version: number
  createdAt: string
  submittedAt: string
  /** Confirmed address (emailed code or staff sign-in); never a typed-in answer. */
  respondentEmail: string | null
  data: Record<string, unknown>
  /** Running or finished approval; null when the form asked for none. */
  approval: ApprovalBrief | null
}

export type ApprovalState = 'pending' | 'approved' | 'rejected' | 'stopped'
export type StepState = 'waiting' | 'pending' | 'no_approver' | 'approved' | 'rejected' | 'stopped'

export interface ApprovalBrief {
  state: ApprovalState
  step: number | null
  total: number
}

export interface ApprovalStepInfo {
  step: number
  name: string
  state: StepState
  source: ApproverSource
  fieldId: string | null
  approverEmail: string | null
  /** Steps decided in the studio (`editors`): the addresses told it was waiting. */
  notifyTo?: string[]
  requestedAt: string | null
  decidedAt: string | null
  decidedName: string | null
  /** Who decided: the approver's address (link) or the staff member's (studio). */
  decidedEmail?: string | null
  /** `email`: through the approver's link; `studio`: by a staff member in the studio. */
  decidedVia?: 'email' | 'studio' | null
  comment: string | null
}

export interface ApprovalDetail extends ApprovalBrief {
  outcomeTo: string | null
  steps: ApprovalStepInfo[]
}

/**
 * Who approves a step: the answer to an email question or a fixed address (both get an emailed
 * link and confirm with a code), or `editors`: only people with edit access, in the studio.
 */
export type ApproverSource = 'field' | 'fixed' | 'editors'

export interface ApprovalStepConfig {
  name: string
  source: ApproverSource
  fieldId: string | null
  email: string | null
  /** `editors` steps: addresses told the step is waiting (no link, no code), up to 10. */
  notify?: string[]
  /** `editors` steps: also email everyone with edit access. */
  notifyEditors?: boolean
}

export interface ApprovalConfig {
  enabled: boolean
  steps: ApprovalStepConfig[]
  notifyRespondent: boolean
  respondentEmailField: string | null
  /** Custom wording (placeholders like {reference}); null = the built-in text. */
  requestSubject?: string | null
  requestMessage?: string | null
  /** List the non-sensitive answers in the approver's email. */
  requestIncludeAnswers?: boolean
  outcomeApprovedMessage?: string | null
  outcomeRejectedMessage?: string | null
  outcomeReplyTo?: string | null
}

export interface ApprovalIssue {
  /** 1-based step; 0 for the outcome email or the whole setting. */
  step: number
  code: string
  level: 'error' | 'warning'
  message: string
  /** The setting it is about, for issues that aren't about a step (e.g. `request_subject`). */
  field?: string | null
}

export interface Approvals {
  config: ApprovalConfig
  issues: ApprovalIssue[]
  emailFields: { id: string; label: string }[]
  language: FormLanguage
  smtpEnabled: boolean
}

export type PdfStatus = 'none' | 'pending' | 'ready' | 'failed'
export type EventType =
  | 'created'
  | 'status_changed'
  | 'comment'
  | 'pdf_generated'
  | 'exported'
  | 'viewed'
  | 'deleted'
  | 'approval_requested'
  | 'approval_decided'
  | 'approval_waiting'
  | 'approval_stopped'

export interface SignatureInfo {
  id: string
  fieldId: string
  signedAt: string | null
  receivedAt: string
  ip: string | null
  userAgent: string | null
  attestation: string
  strokesSha256: string
  imageUrl: string
}

export interface SubmissionEvent {
  seq: number
  type: EventType
  actorName: string | null
  payload: Record<string, unknown>
  createdAt: string
}

/** A stored copy of a file or signature brought over from Jotform. */
export interface ImportedFile {
  fieldId: string
  index: number
  kind: 'file' | 'signature'
  name: string
  mime: string
  size: number
  fetchedAt?: string | null
  url: string
}

export interface SubmissionDetail extends SubmissionSummary {
  formId: string
  /** `form` for responses, `jotform_import` for imported rows. */
  source?: string
  externalId?: string | null
  /** Imported files and signatures not copied yet: links to Jotform, by question. */
  importedLinks?: Record<string, string[]> | null
  importedFiles?: ImportedFile[]
  schema: Form
  canEdit: boolean
  canDelete: boolean
  contentHash: string | null
  pdfStatus: PdfStatus
  signatures: SignatureInfo[]
  events: SubmissionEvent[]
  approval: ApprovalDetail | null
  pdfSha256: string | null
  schemaHash: string | null
  chainHead: string | null
}

export type FilterOp = 'contains' | 'eq' | 'neq' | 'gte' | 'lte' | 'includes' | 'answered' | 'unanswered'

export interface FieldFilter {
  field: string
  op: FilterOp
  value?: string | number | boolean
}

/** A condition in the submissions query language (backend app/insights/dsl.py): Insights
 * bars and the AI's "Show these submissions" links carry these. */
export interface Condition {
  field: string
  op: string
  value?: string | number | boolean | null
  values?: (string | number | boolean)[] | null
}

/** Submission list filters (also the body of an export request). */
export interface ListFilters {
  status?: SubmissionStatus
  q?: string
  from?: string
  to?: string
  version?: number
  fields?: FieldFilter[]
  ids?: string[]
  /** All must hold. */
  where?: Condition[]
  /** At least one must hold. */
  whereAny?: Condition[]
}

/** Query string of the list filters (the list, Insights). */
export function filterParams(f: ListFilters): URLSearchParams {
  const qs = new URLSearchParams()
  if (f.status) qs.set('status', f.status)
  if (f.q) qs.set('q', f.q)
  if (f.from) qs.set('from', f.from)
  if (f.to) qs.set('to', f.to)
  if (f.version) qs.set('version', String(f.version))
  if (f.fields?.length) qs.set('filter', JSON.stringify(f.fields))
  if (f.where?.length || f.whereAny?.length)
    qs.set('where', JSON.stringify({ where: f.where ?? [], whereAny: f.whereAny ?? [] }))
  return qs
}

export interface ExportJob {
  id: string
  status: 'pending' | 'running' | 'ready' | 'failed'
  rowCount: number | null
  rowsDone: number
  expiresAt: string | null
  downloadUrl: string | null
}

export interface AccessEntry {
  userId: string
  email: string
  displayName: string
  role: FormRole
  orgAdmin: boolean
}

/** Someone invited to the organisation who gets `role` on this form when they accept. */
export interface PendingAccess {
  invitationId: string
  email: string
  role: FormRole
  expired: boolean
}

export interface AccessList {
  entries: AccessEntry[]
  pending: PendingAccess[]
  canManage: boolean
  /** Owners who are organisation admins can invite people from outside. */
  canInvite: boolean
  /** Missing from older servers. */
  orgId?: string | null
  orgName: string
  /** "Notify by email" needs email to be set up on the server. */
  smtpEnabled: boolean
}

// -- people (docs/ux/PEOPLE-SCREENS.md) -----------------------------------------------------

/** A member suggested while typing a name or email (PEOPLE-SCREENS 6.2). */
export interface MemberMatch {
  userId: string
  email: string
  displayName: string
  role: OrgRole
  initials: string
  /** With a form: the role they already have on it (organisation admins are owners). */
  formRole: FormRole | null
}

export interface Person {
  userId: string
  email: string
  displayName: string
  role: OrgRole
  status: 'active' | 'never_signed_in'
  lastLoginAt: string | null
  formCount: number
  /** The role comes from OIDC sign-in groups and is set again at each sign-in. */
  managedByGroups: boolean
  isSuperadmin: boolean
}

export interface Invitation {
  id: string
  email: string
  role: OrgRole
  state: 'invited' | 'expired' | 'email_failed'
  expiresAt: string
  createdAt: string
  sentAt: string | null
  emailError: string | null
  invitedByName: string | null
  formCount: number
}

export interface People {
  orgId: string
  orgName: string
  members: Person[]
  invitations: Invitation[]
  adminCount: number
  inviteDays: number
}

export interface InviteResult {
  email: string
  outcome: 'invited' | 'already_member'
}

export interface InvitationLink {
  status: 'pending' | 'expired' | 'accepted' | 'invalid'
  orgName: string | null
  orgSlug: string | null
  email: string | null
  role: OrgRole | null
  invitedByName: string | null
  expiresAt: string | null
}

export interface Integrity {
  ok: boolean
  contentOk: boolean
  chainOk: boolean
  chainLength: number
  brokenAt: number | null
  problems: string[]
}

export type PdfVerdict = 'genuine' | 'modified' | 'not_ours' | 'unsigned' | 'data_changed' | 'not_found'

export interface PdfCheck {
  verdict: PdfVerdict
  trustedSigner: boolean
  signedAt: string | null
  signerFingerprint: string | null
  signerSubject: string | null
  submission: { id: string; formId: string; formTitle: string; seq: number; integrityOk: boolean } | null
  problems: string[]
}

export type FormPatch = Partial<{
  slug: string
  status: FormStatus
  embedOrigins: string[]
  accessMode: AccessMode
  otpAllowedDomains: string[]
  otpOneResponse: boolean
  captcha: CaptchaMode
  saveProgress: boolean
  saveProgressDays: number
  /** 0 turns retention off. */
  retentionDays: number
  /** Questions on submission cards; [] goes back to the automatic choice. */
  cardFields: string[]
  /** Owners: let "Ask your submissions" send the text of answers to the AI provider. */
  aiReadAnswers: boolean
}>

export type RuleType = 'owner_email' | 'respondent_receipt'

export interface NotificationRule {
  enabled: boolean
  recipients: string[]
  includeAnswers: boolean
  attachPdf: boolean
  emailField: string | null
  /** Custom subject and opening text (placeholders like {reference}); null = built-in text. */
  subject: string | null
  message: string | null
  replyTo: string | null
}

export interface EmailLogEntry {
  id: string
  kind:
    | 'owner_new'
    | 'receipt'
    | 'webhook_disabled'
    | 'approval_request'
    | 'approval_notice'
    | 'approval_outcome'
    | 'test_owner_new'
    | 'test_receipt'
    | 'test_approval_request'
    | 'test_approval_notice'
    | 'test_approval_approved'
    | 'test_approval_rejected'
    | 'form_shared'
  to: string
  status: 'queued' | 'sent' | 'failed'
  attempts: number
  error: string | null
  createdAt: string
  sentAt: string | null
}

/** 409 from a studio decision: someone decided the step first. */
export interface AlreadyDecided {
  code: 'approval_done'
  state: StepState | null
  decidedName: string | null
  decidedAt: string | null
  decidedVia: 'email' | 'studio' | null
}

export interface BulkDecideResult {
  id: string
  seq: number | null
  result: 'approved' | 'rejected' | 'already_decided' | 'not_found'
  decidedName: string | null
}

export interface Notifications {
  smtpEnabled: boolean
  language: FormLanguage
  ownerEmail: NotificationRule
  respondentReceipt: NotificationRule
  emailFields: { id: string; label: string }[]
  hasSignature: boolean
  recent: EmailLogEntry[]
}

export type WebhookEvent =
  | 'submission.created'
  | 'submission.status_changed'
  | 'submission.comment_added'
  | 'submission.pdf_ready'
  | 'submission.approval_step'

export interface Webhook {
  id: string
  url: string
  events: WebhookEvent[]
  enabled: boolean
  includeSensitive: boolean
  disabledReason: string | null
  consecutiveFailures: number
  rotatingUntil: string | null
  createdAt: string
}

export interface WebhookInput {
  url: string
  events: WebhookEvent[]
  includeSensitive: boolean
  enabled?: boolean
}

export interface WebhookDelivery {
  id: string
  eventId: string
  event: WebhookEvent | 'test'
  status: 'pending' | 'succeeded' | 'failed'
  attempt: number
  responseCode: number | null
  responseSnippet: string | null
  error: string | null
  durationMs: number | null
  nextAttemptAt: string | null
  deliveredAt: string | null
  createdAt: string
  updatedAt: string
  payload: Record<string, unknown>
}

export const api = {
  meta: () => request<Meta>('GET', '/meta'),
  me: () => request<Me>('GET', '/auth/me'),
  patchMe: (body: { appearance?: Appearance }) => request<Me>('PATCH', '/auth/me', body),
  logout: () => request<{ logoutUrl: string | null }>('POST', '/auth/logout'),
  publicBrand: (slug: string) =>
    request<Brand>('GET', `/public/branding/${encodeURIComponent(slug)}`),
  branding: (orgId: string) => request<Branding>('GET', `/orgs/${orgId}/branding`),
  saveBranding: (orgId: string, body: BrandingSettings) =>
    request<Branding>('PUT', `/orgs/${orgId}/branding`, body),
  uploadBrandImage: (orgId: string, kind: BrandImageKind, file: File) =>
    upload<Branding>(`/orgs/${orgId}/branding/images/${kind}`, file),
  deleteBrandImage: (orgId: string, kind: BrandImageKind) =>
    request<Branding>('DELETE', `/orgs/${orgId}/branding/images/${kind}`),
  palette: (color: string) =>
    request<PaletteReport>('GET', `/branding/palette?color=${encodeURIComponent(color)}`),
  requestCode: (email: string) =>
    request<{ status: string }>('POST', '/auth/local/request', { email }),
  verifyCode: (email: string, code: string) =>
    request<Me>('POST', '/auth/local/verify', { email, code }),

  listForms: (orgId: string) => request<FormListItem[]>('GET', `/orgs/${orgId}/forms`),
  createForm: (orgId: string, body: { title: string; language: FormLanguage; slug?: string }) =>
    request<FormSummary>('POST', `/orgs/${orgId}/forms`, body),
  orgTheme: (orgId: string) => request<ThemeOut>('GET', `/orgs/${orgId}/form-theme`),
  saveOrgTheme: (orgId: string, theme: FormTheme) => request<ThemeOut>('PUT', `/orgs/${orgId}/form-theme`, theme),
  formTheme: (formId: string) => request<ThemeOut>('GET', `/forms/${formId}/theme`),
  saveFormTheme: (formId: string, theme: FormTheme) => request<ThemeOut>('PUT', `/forms/${formId}/theme`, theme),
  previewTheme: (body: { orgId: string; organisation?: FormTheme; form?: FormTheme; formId?: string }) =>
    request<ThemeReport>('POST', '/themes/preview', body),
  uploadFormLogo: (formId: string, file: File) => upload<ThemeOut>(`/forms/${formId}/logo`, file),
  deleteFormLogo: (formId: string) => request<ThemeOut>('DELETE', `/forms/${formId}/logo`),
  sharing: (formId: string) => request<SharingOut>('GET', `/forms/${formId}/sharing`),
  saveSharing: (formId: string, body: { title: string | null; description: string | null }) =>
    request<SharingOut>('PUT', `/forms/${formId}/sharing`, body),
  uploadSharingImage: (formId: string, file: File) => upload<SharingOut>(`/forms/${formId}/sharing/image`, file),
  deleteSharingImage: (formId: string) => request<SharingOut>('DELETE', `/forms/${formId}/sharing/image`),
  uploadThemeImage: (orgId: string, file: File) =>
    upload<{ ref: string; url: string; width: number; height: number }>(`/orgs/${orgId}/theme-images`, file),
  checkSlug: (slug: string, formId?: string) => {
    const qs = new URLSearchParams({ slug })
    if (formId) qs.set('formId', formId)
    return request<SlugCheck>('GET', `/forms/slug-check?${qs}`)
  },
  getForm: (formId: string) => request<FormSummary>('GET', `/forms/${formId}`),
  patchForm: (formId: string, body: FormPatch) =>
    request<FormSummary>('PATCH', `/forms/${formId}`, body),
  deleteForm: (formId: string) => request<void>('DELETE', `/forms/${formId}`),
  duplicateForm: (formId: string) => request<FormSummary>('POST', `/forms/${formId}/duplicate`),
  getDraft: (formId: string) => request<Draft>('GET', `/forms/${formId}/draft`),
  patchDraft: (formId: string, baseRevision: number, patch: Operation[]) =>
    request<Draft>('PATCH', `/forms/${formId}/draft`, { baseRevision, patch }),
  undo: (formId: string, baseRevision: number) =>
    request<Draft>('POST', `/forms/${formId}/draft/undo`, { baseRevision }),
  redo: (formId: string, baseRevision: number) =>
    request<Draft>('POST', `/forms/${formId}/draft/redo`, { baseRevision }),
  draftChanges: (formId: string) => request<DraftChanges>('GET', `/forms/${formId}/draft/changes`),
  discardDraft: (formId: string, baseRevision: number) =>
    request<Draft>('POST', `/forms/${formId}/draft/discard`, { baseRevision }),
  publish: (formId: string) => request<Version>('POST', `/forms/${formId}/publish`),
  versions: (formId: string) => request<Version[]>('GET', `/forms/${formId}/versions`),
  listSubmissions: (formId: string, f: ListFilters & { cursor?: number }) => {
    const qs = filterParams(f)
    if (f.cursor !== undefined) qs.set('cursor', String(f.cursor))
    return request<{ items: SubmissionSummary[]; nextCursor: number | null; total: number }>(
      'GET',
      `/forms/${formId}/submissions?${qs.toString()}`,
    )
  },
  submissionStats: (formId: string) =>
    request<Record<SubmissionStatus | 'all', number>>('GET', `/forms/${formId}/submissions/stats`),
  getSubmission: (id: string) => request<SubmissionDetail>('GET', `/submissions/${id}`),
  /** By reference number (#0047 is 47). */
  getSubmissionByReference: (formId: string, seq: number) =>
    request<SubmissionDetail>('GET', `/forms/${formId}/submissions/seq/${seq}`),
  setSubmissionStatus: (id: string, status: SubmissionStatus, reason?: string) =>
    request<SubmissionDetail>('PATCH', `/submissions/${id}`, { status, reason }),
  addComment: (id: string, text: string) => request<SubmissionDetail>('POST', `/submissions/${id}/comments`, { text }),
  reveal: (id: string, fieldId: string, row?: number) =>
    request<{ value: string }>('POST', `/submissions/${id}/reveal`, { fieldId, row }),
  bulk: (formId: string, body: { ids: string[]; action: 'status' | 'delete'; status?: SubmissionStatus; reason?: string }) =>
    request<{ changed: number }>('POST', `/forms/${formId}/submissions/bulk`, body),
  startExport: (formId: string, filters: ListFilters) => request<ExportJob>('POST', `/forms/${formId}/exports`, filters),
  getExport: (id: string) => request<ExportJob>('GET', `/exports/${id}`),
  getAccess: (formId: string) => request<AccessList>('GET', `/forms/${formId}/permissions`),
  /** `notify` emails the people who get a role or a higher one, with the optional `message`. */
  putAccess: (
    formId: string,
    grants: { email: string; role: FormRole }[],
    options: { notify?: boolean; message?: string } = {},
  ) => request<AccessList>('PUT', `/forms/${formId}/permissions`, { grants, ...options }),
  inviteAndShare: (formId: string, email: string, role: FormRole) =>
    request<AccessList>('POST', `/forms/${formId}/permissions/invite`, { email, role }),
  removePendingAccess: (formId: string, invitationId: string) =>
    request<AccessList>('DELETE', `/forms/${formId}/permissions/invitations/${invitationId}`),
  people: (orgId: string) => request<People>('GET', `/orgs/${orgId}/people`),
  /** Members matching a name or email (at least 2 characters); `formId` for a form's owners. */
  searchMembers: (orgId: string, q: string, formId?: string) => {
    const params = new URLSearchParams({ q, limit: '8' })
    if (formId) params.set('form_id', formId)
    return request<MemberMatch[]>('GET', `/orgs/${orgId}/members/search?${params}`)
  },
  invite: (orgId: string, emails: string[], role: OrgRole) =>
    request<{ results: InviteResult[] }>('POST', `/orgs/${orgId}/invitations`, { emails, role }),
  setInvitationRole: (orgId: string, id: string, role: OrgRole) =>
    request<Invitation>('PATCH', `/orgs/${orgId}/invitations/${id}`, { role }),
  resendInvitation: (orgId: string, id: string) =>
    request<Invitation>('POST', `/orgs/${orgId}/invitations/${id}/resend`),
  cancelInvitation: (orgId: string, id: string) =>
    request<void>('DELETE', `/orgs/${orgId}/invitations/${id}`),
  setMemberRole: (orgId: string, userId: string, role: OrgRole) =>
    request<unknown>('PATCH', `/orgs/${orgId}/members/${userId}`, { role }),
  removeMember: (orgId: string, userId: string) =>
    request<void>('DELETE', `/orgs/${orgId}/members/${userId}`),
  invitationLink: (token: string) =>
    request<InvitationLink>('GET', `/public/invitations/${encodeURIComponent(token)}`),
  acceptInvitation: (token: string) =>
    request<{ orgId: string; orgName: string; me: Me }>('POST', `/invitations/${encodeURIComponent(token)}/accept`),
  verifySubmission: (id: string) => request<Integrity>('GET', `/submissions/${id}/verify`),
  requestPdf: (id: string) => request<{ pdfStatus: PdfStatus }>('POST', `/submissions/${id}/pdf`),
  checkPdf: async (file: File): Promise<PdfCheck> => {
    const res = await fetch('/api/v1/pdf-checks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/pdf', 'X-CSRF-Token': csrfToken(), Accept: 'application/json' },
      credentials: 'same-origin',
      body: file,
    })
    const data: unknown = await res.json().catch(() => null)
    if (!res.ok) throw new ApiError(res.status, data)
    return data as PdfCheck
  },
  getNotifications: (formId: string) => request<Notifications>('GET', `/forms/${formId}/notifications`),
  putNotification: (formId: string, type: RuleType, rule: NotificationRule) =>
    request<Notifications>('PUT', `/forms/${formId}/notifications/${type}`, rule),
  sendTestEmails: (formId: string) => request<Notifications>('POST', `/forms/${formId}/notifications/test`),
  listWebhooks: (formId: string) => request<Webhook[]>('GET', `/forms/${formId}/webhooks`),
  createWebhook: (formId: string, body: WebhookInput) =>
    request<{ webhook: Webhook; secret: string }>('POST', `/forms/${formId}/webhooks`, body),
  patchWebhook: (formId: string, id: string, body: Partial<WebhookInput>) =>
    request<Webhook>('PATCH', `/forms/${formId}/webhooks/${id}`, body),
  deleteWebhook: (formId: string, id: string) => request<void>('DELETE', `/forms/${formId}/webhooks/${id}`),
  rotateWebhookSecret: (formId: string, id: string) =>
    request<{ webhook: Webhook; secret: string }>('POST', `/forms/${formId}/webhooks/${id}/rotate-secret`),
  testWebhook: (formId: string, id: string) =>
    request<WebhookDelivery>('POST', `/forms/${formId}/webhooks/${id}/test`),
  listDeliveries: (formId: string, id: string, before?: string) =>
    request<WebhookDelivery[]>(
      'GET',
      `/forms/${formId}/webhooks/${id}/deliveries${before ? `?before=${encodeURIComponent(before)}` : ''}`,
    ),
  redeliver: (formId: string, id: string, deliveryId: string) =>
    request<WebhookDelivery>('POST', `/forms/${formId}/webhooks/${id}/deliveries/${deliveryId}/redeliver`),
  getApprovals: (formId: string) => request<Approvals>('GET', `/forms/${formId}/approvals`),
  putApprovals: (formId: string, config: ApprovalConfig) =>
    request<Approvals>('PUT', `/forms/${formId}/approvals`, config),
  resendApproval: (id: string) => request<{ status: string }>('POST', `/submissions/${id}/approval/resend`),
  stopApproval: (id: string, reason: string) =>
    request<{ status: string }>('POST', `/submissions/${id}/approval/stop`, { reason }),
  decideApproval: (id: string, body: { step: number; decision: 'approve' | 'reject'; comment?: string }) =>
    request<{ state: StepState; status: SubmissionStatus; approval: ApprovalDetail | null }>(
      'POST',
      `/submissions/${id}/approval/decide`,
      body,
    ),
  bulkDecideApproval: (
    formId: string,
    body: { items: { id: string; step: number }[]; decision: 'approve' | 'reject'; comment?: string },
  ) => request<{ results: BulkDecideResult[] }>('POST', `/forms/${formId}/submissions/approval/decide`, body),
  testApprovals: (formId: string) =>
    request<{ kinds: string[]; to: string }>('POST', `/forms/${formId}/approvals/test`),
  getVersion: (formId: string, n: number) =>
    request<Version & { schema: Form }>('GET', `/forms/${formId}/versions/${n}`),
}

/** Start OIDC login (full-page redirect through the API). */
/** Single sign-on, coming back to `next`. `loginHint` (an invited address) pre-fills the
 * IdP's account picker where it supports that. */
export function ssoLoginUrl(next: string, loginHint?: string | null): string {
  const hint = loginHint ? `&login_hint=${encodeURIComponent(loginHint)}` : ''
  return `/api/v1/auth/login?next=${encodeURIComponent(next)}${hint}`
}
