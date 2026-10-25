# Configuration

The backend reads environment variables with the `JUSTFORMS_` prefix (`backend/app/config.py`
is the full, authoritative list). Docker Compose takes them from `deploy/compose/.env` (see
`.env.example`); the Helm chart from values and Secrets (every key is in
[its README](../deploy/helm/justforms/README.md)).

A name like `JUSTFORMS_S3_ENDPOINT_URL`, `_BUCKET` means `JUSTFORMS_S3_ENDPOINT_URL` and
`JUSTFORMS_S3_BUCKET`.

- [Core](#core)
- [Storage](#storage)
- [Staff sign-in](#staff-sign-in)
- [Email](#email)
- [AI assistant](#ai-assistant)
- [Thaana fonts](#thaana-fonts)
- [Abuse controls](#abuse-controls)
- [Signed PDFs, approvals and webhooks](#signed-pdfs-approvals-and-webhooks)
- [Branding](#branding)
- [Cloudflare Tunnel](#cloudflare-tunnel)

## Core

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_PUBLIC_URL` | `http://localhost:5173` | The URL people open. Used for links, redirects and Origin checks |
| `JUSTFORMS_SECRET_KEY` | none (required) | Long random secret. Encrypts the PDF signing key: keep it stable |
| `JUSTFORMS_DATABASE_URL`, `JUSTFORMS_REDIS_URL` | local defaults | PostgreSQL (asyncpg) and Redis |
| `JUSTFORMS_COOKIE_SECURE` | auto | Set `true` behind HTTPS |
| `JUSTFORMS_TIMEZONE` | `UTC` | Dates in exports and PDFs, and "today" in date limits |
| `JUSTFORMS_TRUSTED_PROXIES` | empty | Proxies (IPs or CIDRs) whose `X-Forwarded-For` is trusted |
| `JUSTFORMS_SESSION_IDLE_SECONDS`, `_SESSION_ABSOLUTE_SECONDS` | 8 hours, 7 days | Staff session lifetimes |
| `JUSTFORMS_CORS_ORIGINS` | `http://localhost:5173` | Origins allowed to call the API from a browser (the SPA is normally same-origin) |

## Storage

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_STORAGE_BACKEND` | `local` | `local` (a volume or PVC) or `s3` |
| `JUSTFORMS_STORAGE_LOCAL_PATH` | `data/storage` | Where `local` keeps files |
| `JUSTFORMS_S3_ENDPOINT_URL`, `_BUCKET`, `_REGION`, `_ACCESS_KEY_ID`, `_SECRET_ACCESS_KEY`, `_ADDRESSING_STYLE` | | Any S3-compatible service (endpoint empty for AWS) |
| `JUSTFORMS_S3_PUBLIC_ENDPOINT_URL` | `JUSTFORMS_S3_ENDPOINT_URL` | Endpoint used in the presigned upload/download URLs browsers get, when browsers reach the service at another address than the backend (for example the backend uses an internal service name and browsers a public hostname). The backend still sends every request to `JUSTFORMS_S3_ENDPOINT_URL` |
| `JUSTFORMS_MAX_UPLOAD_MB` | `25` | Largest single upload |
| `JUSTFORMS_UPLOAD_URL_TTL_SECONDS` | `900` | How long a started upload may take before its upload URL or token expires |
| `JUSTFORMS_PENDING_UPLOAD_TTL_HOURS` | `24` | Uploads never attached to a submission are purged after this many hours |
| `JUSTFORMS_JOTFORM_API_KEY` | | Optional Jotform API key. With it, submission imports take exact submit times from Jotform's API, and `justforms fetch-imported-files` / `rebuild-jotform-import` work (DESIGN 13.3). Used only for those calls, sent in the `APIKEY` header, never stored or logged. Give it to the backend and worker from a Secret (Helm: `extraEnv` with `valueFrom.secretKeyRef`) |
| `JUSTFORMS_JOTFORM_API_REGION` | `us` | `us`, `eu` or `hipaa`: which Jotform API host the key belongs to |
| `JUSTFORMS_JOTFORM_API_TIMEZONE` | `America/New_York` | Time zone of submission times in Jotform's API (US Eastern, whatever the account's own zone) |

With S3, add the bucket's origin (the public endpoint when one is set) to
`JUSTFORMS_CSP_EXTRA_CONNECT_SRC` (below) so browsers may upload to it directly; the Helm chart
does this for you. The bucket also needs a CORS rule allowing `POST`, `GET` and `HEAD` from
`JUSTFORMS_PUBLIC_URL`, since uploads go straight from the browser to it.

## Staff sign-in

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_OIDC_ISSUER`, `_CLIENT_ID`, `_CLIENT_SECRET` | unset | OIDC sign-in. Unset: emailed one-time codes |
| `JUSTFORMS_OIDC_DISCOVERY_URL` | from the issuer | Override the discovery document URL |
| `JUSTFORMS_OIDC_SCOPES` | `openid email profile` | Scopes requested |
| `JUSTFORMS_OIDC_GROUPS_CLAIM` | `groups` | Claim holding the user's groups |
| `JUSTFORMS_OIDC_ADMIN_GROUPS`, `_CREATOR_GROUPS`, `_MEMBER_GROUPS` | empty | Map IdP groups to roles in the default organisation (see below) |
| `JUSTFORMS_OIDC_SUPERADMIN_GROUPS` | empty | IdP groups whose people are superadmins, checked at each sign-in (see below) |
| `JUSTFORMS_OIDC_DEFAULT_ROLE` | `creator` | Without group mapping: the role people get the first time they sign in (`creator`, `member`, or `none` to let people in only by invitation) |
| `JUSTFORMS_OIDC_AUTO_REDIRECT` | `true` | With OIDC on: signed-out visits to the sign-in page or the studio go straight to the IdP (see below) |
| `JUSTFORMS_INVITE_DAYS` | `14` | How long an invitation to join an organisation stays open (a resend restarts it) |
| `JUSTFORMS_LOGIN_CODE_TTL_SECONDS`, `_LOGIN_CODE_MAX_ATTEMPTS` | `600`, `5` | Emailed sign-in codes |
| `JUSTFORMS_DEMO_LOGIN_CODE`, `JUSTFORMS_DEMO_LOGIN_EMAILS` | unset (off) | **Demo instances only.** See below |
| `JUSTFORMS_DEFAULT_ORG_NAME`, `_DEFAULT_ORG_SLUG` | `JustForms`, `default` | The organisation created on first start |

Respondents who must confirm their email before filling a form get their own codes:

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_RESPONDENT_CODE_TTL_SECONDS`, `_RESPONDENT_CODE_MAX_ATTEMPTS` | `600`, `5` | Respondent email codes |
| `JUSTFORMS_RESPONDENT_TOKEN_SECONDS` | 2 hours | How long a confirmed respondent may fill the form |

**Organisation roles.** Admin (everything, including organisation settings and people),
form creator (creates forms; sees the ones they created or that are shared with them) and
member (only the forms shared with them). Admins invite people from Organisation settings ›
People; an invitation is accepted when that address signs in (with an emailed code, or with
OIDC when the IdP's email matches). With group mapping the IdP decides roles in the default
organisation at each sign-in (admin > creator > member) and removes the role of people in no
mapped group, except people an admin invited. *Upgrading:* `JUSTFORMS_OIDC_MEMBER_GROUPS` used
to give a role that could create forms; it now gives the member role. Put groups whose people
build forms in `JUSTFORMS_OIDC_CREATOR_GROUPS` (the backend logs a warning while only member
groups are set). Existing members became form creators in the upgrade, so nobody lost access.

**Automatic sign-in.** With OIDC configured it is the only staff sign-in method, so by default
(`JUSTFORMS_OIDC_AUTO_REDIRECT=true`) the sign-in page, any studio page visited while signed
out, and invitation links (`/login/invite/{token}`) go straight to the IdP without a button
press, showing only "Signing you in…". The page someone asked for is kept as `next` and opened
after the callback; invitation links pass the invited address as `login_hint`. To avoid loops it
never does this right after signing out (the page says "You're signed out" with a "Sign in
again" button), after a failed sign-in (`/login?error=…` shows the error and "Try again"),
with `?manual=1` (the normal sign-in page), or a second time within 30 seconds in the same
browser. Public forms, approver and verify pages are not affected. Set it to `false` to always
show the sign-in page with its single sign-on button.

**After signing in.** Without a `next`, people land on `/forms` (the studio home), not `/`. A
successful sign-in (OIDC callback or emailed code) answers with
`Clear-Site-Data: "cache", "storage"`: when JustForms replaces another app on the same
hostname, the browser may still hold that app's cached redirects (e.g. `/` pointing at another
site) or its service worker, and this clears them. Cookies are kept (the session cookie is set
on the same response). The trade-off: browser-stored UI preferences on this site (such as the
appearance choice) are dropped and read again from the account. The bundled nginx also answers
404 for the usual service-worker script paths (`/sw.js`, `/service-worker.js`, …), so a
leftover service worker unregisters itself at its next update check.

**Superadmins from IdP groups.** `JUSTFORMS_OIDC_SUPERADMIN_GROUPS` (comma-separated) makes
people in any listed group superadmins (every organisation plus instance settings) when they
sign in with OIDC. It works on its own: the role groups above don't have to be set. Values are
matched exactly against the groups claim, so use whatever your IdP puts there (group names, or
group object IDs with Entra ID). When it is set, someone no longer in a listed group loses
superadmin at their next sign-in, but only if OIDC granted it: superadmins made with
`justforms create-admin` keep it. Grants and removals are audit-logged
(`user.superadmin_grant`, `user.superadmin_revoke`). Leaving it empty changes nobody's
superadmin status. A sign-in that grants or confirms superadmin this way also makes the person
**admin of the default organisation** (the membership is created, or a creator/member role is
raised), audit-logged as `org.member_role` with `source: oidc_superadmin`. Losing superadmin
does not demote them: the admin role stays (group mapping doesn't lower an admin role it didn't
grant) until an admin changes it. Superadmins made with `create-admin` are not affected.

*Entra ID group overage.* When someone is in more groups than fit in a token, Entra ID leaves
the `groups` claim out and sends `_claim_names` / `hasgroups` (a pointer to Microsoft Graph)
instead. JustForms then logs a warning and leaves superadmin status and group-mapped roles as
they are. Avoid it by configuring the app registration to emit only *groups assigned to the
application* (and assigning the relevant groups to the app); reading groups from Graph is not
supported yet.

**Demo login.** `JUSTFORMS_DEMO_LOGIN_CODE` is a fixed 6-digit code accepted, after a code is
requested, for the addresses in `JUSTFORMS_DEMO_LOGIN_EMAILS` only. The list is required and
guessable codes are refused. The backend logs a warning and the sign-in page shows "Demo
instance". Never set it on a real install.

## Email

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_SMTP_HOST`, `_PORT`, `_USERNAME`, `_PASSWORD`, `_SECURITY`, `_FROM` | port `587`, `starttls` | Sign-in codes, notifications, receipts, approvals. `_SECURITY` is `none`, `starttls` or `tls` |

The Compose `dev` profile starts Mailpit (UI on http://localhost:8025) and points SMTP at it.

## AI assistant

Optional. With no provider every AI feature is hidden. See [Features](features.md#ai-assistant).

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_AI_PROVIDER` | `none` | `gemini`, `anthropic` or `openai_compat` (OpenAI, vLLM, Ollama...) |
| `JUSTFORMS_AI_MODEL`, `JUSTFORMS_AI_API_KEY` | | Model name and a key issued for JustForms only |
| `JUSTFORMS_AI_BASE_URL` | | Endpoint; required for `openai_compat` (e.g. `http://ollama:11434/v1`) |
| `JUSTFORMS_AI_VISION_MODEL` | `JUSTFORMS_AI_MODEL` | Model for "Start from a paper form" |
| `JUSTFORMS_AI_VISION` | on for `gemini`/`anthropic`, off for `openai_compat` | Whether the model reads images |
| `JUSTFORMS_AI_PROVIDER_LABEL` | | Provider name shown in the paper-form dialog ("The pages are sent to ...") |
| `JUSTFORMS_AI_DAILY_TOKENS_PER_USER`, `_PER_ORG` | `300000`, `3000000` | Daily token allowances (input + output); `0` turns one off |
| `JUSTFORMS_AI_MAX_OUTPUT_TOKENS`, `_MAX_TOOL_CALLS`, `_TURN_SECONDS`, `_REQUEST_TIMEOUT_SECONDS`, `_MAX_FORM_CHARS` | `4096`, `40`, `120`, `90`, `80000` | Limits per turn; forms larger than `_MAX_FORM_CHARS` are not sent |

## Thaana fonts

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_THAANA_FONT_CSS_URL` | the public [dvfonts](https://dvfonts.yashau.com) CDN (Faruma) | Stylesheet for Faruma. `/fonts/faruma.css` to self-host, empty to disable |
| `JUSTFORMS_THAANA_FONTS` | a built-in list (Faruma, MV Faseyha, MV A Waheed, ...) | Thaana fonts form themes can choose; each loads from the font service above when a form uses it |
| `JUSTFORMS_FONTS_DIR` | `./fonts` | Compose only: directory (relative to `deploy/compose/`) served at `/fonts/` |
| `JUSTFORMS_THAANA_FONT_FILE` | empty (bundled Noto Sans Thaana) | Path to a Thaana TTF/OTF inside the API and worker containers, used for server rendering: signed PDFs and link-preview images |
| `JUSTFORMS_THAANA_FONT_BOLD_FILE` | empty (the regular file) | Optional bold face for the same |

The Thaana stack is `Faruma, "MV Faseyha", "Noto Sans Thaana", sans-serif`. Only Noto Sans
Thaana (SIL OFL) is bundled. Faruma and MV fonts are never shipped in the repository or the
images because their licence is unclear.

By default Faruma loads from the public dvfonts CDN, which then sees the IP address of everyone
who opens a Dhivehi form or the studio. To avoid that, self-host: put the font files and a
`fonts.css` in `deploy/compose/fonts/` (git-ignored; or set `JUSTFORMS_FONTS_DIR`), and set
`JUSTFORMS_THAANA_FONT_CSS_URL=/fonts/faruma.css`. The app always loads `/fonts/fonts.css` as
well. For example:

```css
@font-face {
  font-family: "Faruma";
  src: url("/fonts/Faruma.woff2") format("woff2"), url("/fonts/Faruma.ttf") format("truetype");
  font-display: swap;
  unicode-range: U+0780-07BF, U+060C, U+061B, U+061F, U+FDF2;
}
```

On Kubernetes put the same files in a ConfigMap and set `frontend.fontsConfigMap`. Only use
fonts you are licensed to embed on the web.

### Server-rendered Thaana (PDFs and link previews)

Signed PDFs and generated link-preview images are drawn on the server, so they cannot use the
browser's fonts. They use the bundled Noto Sans Thaana unless `JUSTFORMS_THAANA_FONT_FILE`
points at a TrueType/OpenType Thaana font (for example the same face the web uses, if your
licence allows embedding it). With compose, mount the file into the `backend` and `worker`
services (e.g. `./fonts/Thaana-Regular.ttf:/etc/justforms/fonts/Thaana-Regular.ttf:ro`) and set
the variable; with Helm use `fonts.server.*` (see the chart README).

The file is checked once per process, the first time it is needed:

- it must open as a font with outlines and cover the Thaana letters and vowel signs
  (U+0780 to U+07B0);
- for PDFs, its OS/2 `fsType` must allow embedding a subset (installable, editable or
  preview & print; not "restricted", "no subsetting" or "bitmap only"). Link-preview images are
  rasterised and never contain the font, so a font that may not be embedded is still used there.

A file that fails a check is not used: the bundled face takes its place and a warning is logged
once. The supplied face is used only for the characters Noto Sans Thaana covers (Thaana,
Arabic-script punctuation, digits and common punctuation), so Latin words inside Dhivehi text
keep the Latin face. Generated link-preview images include the font in their version, so they
are made again when it changes. Restart the API and worker after replacing the file.

## Abuse controls

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_RATE_LIMIT_ENABLED`, `JUSTFORMS_RATE_LIMITS` | on, built-in limits | e.g. `public_submit=20/60,upload_init=60/60`; invitations: `invite_user` (50 addresses an hour per admin), `invite_org` (200 a day per organisation), `invite_resend` (3 an hour per invitation) |
| `JUSTFORMS_CAPTCHA_PROVIDER` | `none` | `altcha` (proof of work, no third party), `turnstile` or `hcaptcha` |
| `JUSTFORMS_CAPTCHA_SITE_KEY`, `_SECRET_KEY`, `_BUSY_THRESHOLD` | | Provider keys; responses per hour that count as "busy" (default `1000`) |
| `JUSTFORMS_ALTCHA_MAX_NUMBER` | `100000` | ALTCHA proof-of-work difficulty |
| `JUSTFORMS_CSP_EXTRA_CONNECT_SRC` | empty | Extra origins for the web container's CSP (e.g. your S3 bucket) |

## Signed PDFs, approvals and webhooks

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_PDF_SIGNING_P12`, `_P12_PASSWORD` | unset | Sign with an organisation certificate instead of the install's own key |
| `JUSTFORMS_PDF_TSA_URL` | unset | RFC 3161 timestamp authority |
| `JUSTFORMS_PDF_SIGNER_NAME` | `JustForms document signing` | Name on the install's own signing certificate |
| `JUSTFORMS_APPROVAL_LINK_DAYS` | `14` | How long an approver's link works |
| `JUSTFORMS_WEBHOOK_ALLOWED_CIDRS` | empty | Private networks webhooks may reach (plain `http` only to these) |
| `JUSTFORMS_WEBHOOK_TIMEOUT_SECONDS` | `10` | Timeout per webhook delivery |

Signing keys and checking PDFs: [Security](security.md#signed-pdfs-and-the-verify-page).

## Branding

Instance defaults, used by organisations that set no branding of their own. See
[Features](features.md#branding).

| Variable | Default | Purpose |
|---|---|---|
| `JUSTFORMS_BRAND_NAME`, `_PRIMARY_COLOR`, `_SUPPORT_URL` | JustForms' own | Name, `#RRGGBB` colour and help link when an organisation sets none |
| `JUSTFORMS_BRAND_LOGO_FILE`, `_LOGO_DARK_FILE`, `_ICON_FILE` | unset | Paths to PNG/SVG files the API reads (e.g. a mounted ConfigMap) |
| `JUSTFORMS_BRAND_POWERED_BY` | `optional` | `always` keeps "Powered by JustForms" on every form |

In the Helm chart these are `branding.*` values.

## Cloudflare Tunnel

Read by Docker Compose, not the backend. See [Deployment](deployment.md#cloudflare-tunnel).

| Variable | Purpose |
|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | Token of a named tunnel (`tunnel` profile only) |
