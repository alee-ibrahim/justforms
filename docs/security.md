# Security

How JustForms protects staff accounts, respondents and signed documents, and how to report a
problem. Abuse-control settings are in [Configuration](configuration.md#abuse-controls).

- [Security model](#security-model)
- [Signed PDFs and the verify page](#signed-pdfs-and-the-verify-page)
- [Webhooks](#webhooks)
- [Reporting a vulnerability](#reporting-a-vulnerability)

## Security model

- **Sessions.** Staff sessions live in Redis (8 h idle, 7 days absolute) behind an HttpOnly
  cookie, with a double-submit CSRF token and an Origin check on every state-changing request.
  OIDC is a confidential client with PKCE; no token reaches the browser.
- **Account linking.** OIDC sign-in links an existing account (or accepts invitations) by email
  only when the IdP vouches for the address (`email_verified: true`, or
  `JUSTFORMS_OIDC_TRUST_EMAIL` for an IdP whose addresses administrators manage), never from
  usernames unless configured, and never links superadmins by email unless trusted. Removing
  someone from an organisation (by an admin or IdP group mapping) also removes their form roles
  and ends their sessions; `app.cli revoke-sessions` signs someone out everywhere.
- **Public forms** use no cookies. Rate limits cover forms, submits, uploads, email codes and
  sign-in; CAPTCHA is optional per form (off, always, or only when busy).
- **Emailed codes** (staff sign-in, respondent and approver codes) are 6 digits, stored as
  HMACs, valid 10 minutes for 5 tries. Attempts and rate limits are counted atomically in Redis,
  so concurrent guesses can't exceed them. After 10 wrong guesses in a day
  (`JUSTFORMS_CODE_LOCKOUT_FAILURES`) the address (or approval step) is locked out until the day
  passes, whatever codes are requested meanwhile. Someone who knows an address can lock its
  email-code sign-in for that time; OIDC sign-in is not affected.
- **Client IP address.** The web container works out the visitor's address (trusting only the
  proxies in `JUSTFORMS_REAL_IP_FROM`) and sends it to the API as the only `X-Forwarded-For`
  hop; the API trusts that header only from `JUSTFORMS_TRUSTED_PROXIES` and takes the
  right-most untrusted hop, so a client can't choose the address used for rate limits or
  recorded with submissions and signatures. uvicorn's `FORWARDED_ALLOW_IPS=*` is refused in
  production.
- **CAPTCHA.** The built-in proof of work signs the challenge together with its salt and
  expiry, refuses expiries beyond the 30-minute lifetime and numbers above the maximum, and
  remembers each solved challenge until it expires, so a token works once. Turnstile and hCaptcha
  tokens must have been solved on the host of `JUSTFORMS_PUBLIC_URL` (and, for Turnstile, with
  the form widget's action).
- **Approvals.** When the respondent types the approver's address, it can't be their own
  address, and owners can limit it to their email domains (the builder warns until they do).
  The verify page shows who decided each step, masked.
- **Receipts** go to the confirmed respondent address. Sending them to an address typed into
  a question is an owner opt-in, rate limited, and such receipts carry only the reference unless
  the owner also allows answers, so a form can't be used to mail arbitrary text to anyone.
- **Staff-only forms** accept only signed-in people in the form's organisation (or with access
  to the form), not everyone who can sign in.
- **Headers.** The web container sends a Content-Security-Policy, `X-Content-Type-Options`,
  `Referrer-Policy`, `Permissions-Policy` and HSTS (behind HTTPS by default, or always with
  `JUSTFORMS_HSTS`) on every response, the API included. Public forms may be framed
  by the form's allowed websites (any site when the list is empty); the studio, verify and
  approver pages never.
- **Uploaded images** for branding and themes: SVGs are cleaned on upload and every image is
  served from JustForms' own origin.
- **AI assistant.** Only the form's questions go to the provider, never responses; paper forms
  must be confirmed blank each time. Give JustForms its own API key.
- **Ask your submissions.** Counts, and sums, averages and groups over at least 5 submissions,
  go to the provider; never a single submission's answers, free text or contact details
  (those only filter as answered/unanswered). A narrow filter's count is still exact, so it
  can say something about a few submissions. Answers (contact details and sensitive questions
  included, never files, signatures or IP addresses; at most 500 submissions per question)
  go only on forms whose owner turned on "Allow AI to read answers" (off by default), labelled
  as untrusted data; numbers in a reply that no counted result contains are flagged. Lists are
  read from the database and shown to the person; transcripts keep what was listed, not the
  values, and sensitive answers shown in a list are logged on the submission. Every read and
  list is audited without the values.
- **AI limits.** Token allowances are reserved before each provider call (parallel requests
  can't overshoot), a person runs one AI request at a time, every Ask query has a 10 s
  database statement timeout, and tool results, provider requests and the form outline are
  size-capped. Provider error bodies are not logged (status and error type only). Paper form
  pages are rendered at most 2048 px and images over 40 megapixels are refused before
  decoding.
- **Sensitive questions** are shown to everyone who can see the submissions; opening a
  submission that has them is recorded in its activity log. Only owners can turn the flag off
  on a published question, or change the websites allowed to frame the form.
- **Integrity.** Every submission has a SHA-256 content hash (RFC 8785 canonical JSON) and a
  hash-chained activity log; every change goes through that log.
- **Demo login** (`JUSTFORMS_DEMO_LOGIN_CODE`) is for demo instances only: the API refuses to
  start with it in production.
- **Secret key.** In production the API refuses to start without `JUSTFORMS_SECRET_KEY`, with
  one shorter than 32 bytes, or with a placeholder such as the `.env.example` value. It signs
  respondent and approver tokens and keys code HMACs, and encrypts the PDF signing key.
- **Cookies and caching.** Behind HTTPS the session and CSRF cookies use the `__Host-` prefix
  (Secure, whole site, no Domain), so a sibling subdomain can't plant them. OIDC sign-in binds
  its `state` to the browser with a short-lived cookie, best effort: a callback carrying the
  cookie of another sign-in is refused, so a callback link can't sign someone into another
  account from a browser that started its own sign-in. A callback without the cookie is
  accepted on the one-time server-side state (single use, 10 minutes, with the PKCE verifier
  and nonce), because on phones the IdP often finishes in another browser context (an
  authenticator broker, in-app browser or custom tab) that never saw the cookie. The API logs
  which path a sign-in took. Signing out sends `Clear-Site-Data: "cookies"`. Staff API responses,
  token links and authenticated downloads are `Cache-Control: no-store`. After signing in, only
  a same-origin path is followed (`next`); control characters, spaces and backslashes are
  refused.
- **Information.** API docs and the OpenAPI document are off in production
  (`JUSTFORMS_API_DOCS`); SQL errors never include bound values; access logs carry no query
  strings or link tokens.

## Error tracking

Optional (`JUSTFORMS_SENTRY_DSN`, see [Configuration](configuration.md#error-tracking)). When
it is on, the API, the worker and browsers report errors to a Sentry-protocol server (Sentry,
GlitchTip); nothing is sent otherwise.

- **What an event holds.** The exception type and message, stack frames (file, function,
  line, the source line), the route or page path, release, environment and runtime/browser
  versions. No user, no IP address (`send_default_pii` off), no cookies, headers, query
  strings or request bodies, no local variables, no breadcrumbs (they would carry typed text
  and clicked labels), no session replay, no profiling; tracing is off unless
  `JUSTFORMS_SENTRY_TRACES_SAMPLE_RATE` is set.
- **Scrubbing.** Every event passes a scrubber (`backend/app/telemetry/scrub.py` and its
  browser twin, sharing `spec/telemetry/scrub.json`) that keeps only those parts and masks
  emails, phone numbers, ID card numbers, long numbers, tokens (also in URL paths, e.g.
  verify and approver links), Pydantic input values, SQL parameters and PostgreSQL key
  details. Tests check that no answer value from a fixture survives.
- **Browser tunnel.** Browsers post to `/api/v1/telemetry/envelope` on the install itself,
  never to the tracker, so the tracker can stay internal and the CSP needs no extra origin.
  The tunnel only forwards to the configured DSN's host (the envelope must name that DSN's key
  and project; the request never chooses the destination), passes only `event` and
  `client_report` items (no replays, attachments, sessions, transactions or user feedback),
  scrubs every event again, refuses bodies over 200 KB and compressed bodies, and is rate
  limited per IP. `/api/v1/meta` gives browsers a DSN with the install's own host, so the
  tracker's address is not disclosed. The SDK is loaded after the page is idle.

## Where people get stuck (respondent friction)

The public form counts, per form, version and day: visits that reached each page, visits that
started answering, visits shown a validation problem (question key and problem code, e.g.
`pattern`) and submissions. It never sends answer values (the endpoint refuses unknown keys)
and reads no cookies or tokens. A random visit id lives in the tab's `sessionStorage` (memory
when storage is blocked) only so each thing counts once per visit; the server keeps a hash of
it in Redis for a day and stores nothing but daily counters. Reports are rate limited per IP.
Owners can turn it off per form (Settings › Access); it is on by default. Insights shows the
last 30 days.

## Signed PDFs and the verify page

Signatures are kept as raw strokes and re-rendered, with when, from which IP address and device
the form was signed, and the statement the signer saw. Every signed submission gets a PAdES PDF
signed with the install's key (or an organisation certificate, `JUSTFORMS_PDF_SIGNING_P12`, with
an optional RFC 3161 timestamp authority, `JUSTFORMS_PDF_TSA_URL`).

The verify page (`/v/{token}`) says only whether the document is genuine and unchanged, with its
reference, issue date and approval outcome, never the answers. The IP address, device and hashes
are not printed on the PDF; they stay in the studio and in the file's metadata.

- The signing key is created on first start (or `python -m app.cli init-signing-key`) and
  stored encrypted with `JUSTFORMS_SECRET_KEY`. If that secret changes, run
  `init-signing-key --rotate`. Publish the certificate fingerprint it prints so others can tell
  your PDFs from anyone else's.
- Check a PDF on its verify page (people can upload their copy there), in the studio
  (Submissions, "Check a PDF") or on the server with
  `python -m app.cli verify-pdf submission-0042.pdf`. Each checks the signature and recomputes
  the content hash from the database.

## Webhooks

Webhooks are HMAC-signed; outbound URLs are resolved, checked against private ranges and
pinned (allow private networks with `JUSTFORMS_WEBHOOK_ALLOWED_CIDRS`). Payloads, the signature
scheme and verifiers for Python, Node and PHP are in [webhooks.md](webhooks.md). Only owners
see a webhook's full URL; editors and viewers see the scheme and host, since catch URLs often
carry a secret in the path or query.

## Reporting a vulnerability

Please don't open a public issue for a security problem. Report it privately through GitHub's
**Report a vulnerability** button on the repository's Security tab, with steps to reproduce and
the version or commit you tested. You'll get an answer as soon as possible, and a fix will be
released before the details are made public.
