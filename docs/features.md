# Features

A tour of what JustForms does. For settings see [Configuration](configuration.md); for the
reasoning behind each part see the [design document](DESIGN.md).

- [Languages: English and Dhivehi](#languages-english-and-dhivehi)
- [Building forms](#building-forms)
- [Logic](#logic)
- [Filling forms](#filling-forms)
- [Form addresses and embedding](#form-addresses-and-embedding)
- [Signatures, signed PDFs and the verify page](#signatures-signed-pdfs-and-the-verify-page)
- [Approvals](#approvals)
- [Submissions and export](#submissions-and-export)
- [Emails and webhooks](#emails-and-webhooks)
- [AI assistant](#ai-assistant)
- [Jotform import](#jotform-import)
- [People and roles](#people-and-roles)
- [Branding](#branding)
- [Appearance and form themes](#appearance-and-form-themes)
- [Running it](#running-it)

<p align="center">
  <img src="images/builder.webp" alt="The form builder: question types on the left, the form as a white sheet in the middle with the selected question marked in yellow, its settings on the right" width="880">
</p>

## Languages: English and Dhivehi

Each form is written in **English or Dhivehi**. Dhivehi forms are right to left in Thaana
fonts, with a phonetic Thaana keyboard for answers. Everything around the form (the studio, the
public form's buttons and messages, emails, the verify page and the PDF's labels) is English.

The Thaana font stack is `Faruma, "MV Faseyha", "Noto Sans Thaana", sans-serif`. Only Noto Sans
Thaana (SIL OFL) is bundled; Faruma loads from a font service by default and can be self-hosted
(see [Thaana fonts](configuration.md#thaana-fonts)).

<p align="center">
  <img src="images/dhivehi-phone.webp" alt="A Dhivehi form on a phone, right to left in Thaana" width="320">
</p>

## Building forms

- Question types: short and long answers, email, phone, number, single and multi choice,
  yes/no, rating, date, time, file upload and drawn signature; plus sections, repeating groups,
  headings and text blocks.
- The canvas looks exactly like what respondents will see.
- Autosave, undo and redo, live preview, and published versions: respondents always fill the
  version you published, while you keep editing the draft.

## Logic

Multi-page forms with show, hide, require and skip-page rules. Rules are checked for cycles,
and the same logic engine runs in the browser and on the server.

## Filling forms

- A small, fast public form (initial JavaScript under 120 KB gzip) made for mid-range phones.
- Answers are validated the same way in the browser and on the server.
- Progress is saved on the respondent's device (browser storage) while they type, so a closed
  tab or a reload loses nothing: the form reopens with their answers and page and a small
  notice with **Start over**. Sensitive questions, signatures and files are never kept; saved
  progress expires after 7 days by default and is cleared on submit. Owners can change the
  expiry or turn it off for forms used on shared or kiosk devices (Settings › Access).
- Access: open to anyone with the link, to people who confirm their email first, or to
  signed-in staff.
- Rate limits and optional CAPTCHA per form (off, always, or only when busy).

## Form addresses and embedding

A published form lives at `https://<your-host>/<address>`. Addresses are unique across the
install; a new form takes one from its title and owners can change it on the Share page, which
checks it as they type. Words the app uses itself (`login`, `forms`, `settings`, `api`,
`assets`, ...) can't be addresses. Links in the old `/f/<org>/<address>` form redirect
permanently.

Forms can be embedded in other websites with `?embed=1`; each form can limit which sites may
embed it (any site when the list is empty).

## Signatures, signed PDFs and the verify page

<p align="center">
  <img src="images/signed-pdf.webp" alt="A signed PDF with a QR code in the footer, next to its verify page saying Genuine document" width="880">
</p>

Signatures are kept as raw strokes and re-rendered, with when, from which IP address and device
the form was signed, and the statement the signer saw. Every submission has a SHA-256 content
hash and a hash-chained activity log, and every signed submission gets a **PAdES signed PDF**.

The PDF is the respondent's copy: title, answers, signatures, reference, submission date, the
approval record and a footer QR code. The IP address, device and hashes are not printed; they
stay in the studio and in the file's metadata. The verify page (`/v/{token}`) says only whether
the document is genuine and unchanged, with its reference, issue date and approval outcome,
never the answers. People can also upload their copy there to check it.

How signing keys work and how to check a PDF:
[Security](security.md#signed-pdfs-and-the-verify-page).

## Approvals

Up to three **approval steps** per form. Approvers get an emailed link and need no account;
the link works for `JUSTFORMS_APPROVAL_LINK_DAYS` (14 by default). The outcome is part of the
signed PDF's approval record and shows on the verify page.

## Submissions and export

<p align="center">
  <img src="images/submissions.webp" alt="The submissions table with status badges and masked national ID numbers" width="880">
</p>

A submissions table with search, filters, status (New, In review, Approved, Rejected),
comments, an activity log and export to Excel. Sensitive answers are masked.

## Emails and webhooks

- Email to the form's owners and a receipt for the respondent.
- Signed **webhooks** with retries. Outbound URLs are resolved, checked against private ranges
  and pinned. Events, payloads and verifiers: [webhooks.md](webhooks.md).

## AI assistant

<p align="center">
  <img src="images/ai-suggestion.webp" alt="The AI assistant panel listing suggested changes, with the suggested questions marked on the form" width="880">
</p>

With a provider configured ([AI assistant settings](configuration.md#ai-assistant)), editors can
describe a form and get a draft, ask for changes ("add a phone question after email, show page 2
only to people who answered Yes"), or upload a **blank** paper form to recreate it.

The AI only calls schema tools; each change is validated and shown on the canvas as a
suggestion to apply (one Undo reverts it) or discard. Only the form's questions go to the
provider, never responses, and paper forms must be confirmed blank each time. Dhivehi wording
from the AI is a draft to check. Unset, every AI feature is hidden.

Behind your own reverse proxy, see [Deployment](deployment.md#reverse-proxies) for the
streaming settings the assistant needs.

## Jotform import

Teams leaving Jotform can bring their forms and submission history with them. The importer is
ordinary parsing code, not AI.

- **Forms** come from the form's public link, its pasted or uploaded HTML source, or the
  Jotform API with a key that is never stored. Question types are mapped, collapses become
  sections, inline conditions are translated where they can be, and Thaana text is detected
  to suggest a Dhivehi form.
- A per-question **import report** says what was imported, changed or skipped, and why. The
  result becomes an ordinary draft to review before publishing.
- **Submissions** come from Jotform's `.xlsx` or `.csv` export: JustForms suggests a column
  mapping, previews the first rows and imports them in one go, skipping rows already imported.
  Imported rows send no notifications.

The full mapping is in [DESIGN.md §13](DESIGN.md#13-import-from-jotform).

## People and roles

- Three organisation roles: **Admin** (everything, including organisation settings, people and
  branding; owner of every form), **Form creator** (creates and imports forms, sees the ones
  they created or that are shared with them) and **Member** (sees only the forms shared with
  them). Each form also has its own owners, editors and submissions viewers (can view and export
  submissions, can't edit the form).
- Organisation settings › People lists everyone with their role, status (active, never signed
  in, invited, invite expired) and last sign-in, with search.
- Invite several people at once by email with a role. They get a branded email with a link to
  a prefilled sign-in page; the link works for 14 days. Resend, cancel or change the role of a
  pending invite. With single sign-on, the invitation is accepted when that email signs in.
- Change someone's role or remove them (their access to the organisation's forms goes with
  them). An organisation always keeps at least one admin.
- Sharing a form with someone who isn't in the organisation yet: admins invite them and share
  in one step; they get the form role when they accept.
- Superadmins can do all of this in every organisation.

## Branding

JustForms' name, logo and colour can be replaced by each organisation's own. Organisation
admins open **Organisation settings** from the account menu and set a display name, a logo (PNG
or SVG, plus an optional dark-mode version), a square icon (favicon and app icon), a primary
colour, a support link and whether "Powered by JustForms" shows. A live preview shows the studio
and a form in light and dark, phone and desktop.

The branding appears on the studio header and sign-in page, browser tab and installed app,
public forms, approver and verify pages, emails (sender name, logo, footer), signed PDFs and
Excel exports. The colour is checked for contrast and adjusted when needed, so text on
buttons and links stays readable (WCAG AA). SVGs are cleaned on upload and every image is
served from JustForms' own origin, so the Content-Security-Policy stays tight.

Instance defaults ([`JUSTFORMS_BRAND_*`](configuration.md#branding), or `branding.*` in the
Helm chart) apply to organisations that set nothing; with nothing set anywhere JustForms looks
like JustForms. The sign-in page uses the default organisation's branding.

## Appearance and form themes

The studio is light unless someone picks **Dark** or **Match device** in their account menu;
the choice is saved on their account.

Forms, and the approver and verify pages that belong to them, look the way the organisation's
**form theme** says (Organisation settings, below Branding):

- colours, checked and adjusted so text stays readable, with dark-mode colours generated from
  them;
- a Latin font from a curated set of open-licence fonts served by JustForms itself, and a
  Thaana font from `JUSTFORMS_THAANA_FONTS`;
- text and heading size, corners, spacing, page width, button and input style, the progress
  bar and the logo position;
- header and background images;
- whether people filling it in see it light, dark or matching their device (light by default).

Each form can change any of these on its Settings page; everything it doesn't change follows
the organisation. Both pages have a live preview of an English and a Dhivehi sample on a phone
or desktop. The theme also colours email buttons and the title rule and headings of signed PDFs.

## Running it

- Docker Compose for one server, a Helm chart for Kubernetes: see [Deployment](deployment.md).
- Staff sign in with OIDC (Entra ID, Keycloak, any standard provider) or emailed one-time codes;
  admins invite people by email.
- Files on a local volume or any S3-compatible service.
