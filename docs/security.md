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
- **Ask your submissions.** Counts go to the provider; answers (contact details and sensitive
  questions included, never files, signatures or IP addresses) only on forms whose owner
  turned on "Allow AI to read answers" (off by default). Lists are read from the database and
  shown to the person; every read and list is audited without the values.
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
  its `state` to the browser with a short-lived cookie, so a callback link can't sign someone
  into another account. Signing out sends `Clear-Site-Data: "cookies"`. Staff API responses,
  token links and authenticated downloads are `Cache-Control: no-store`. After signing in, only
  a same-origin path is followed (`next`); control characters, spaces and backslashes are
  refused.
- **Information.** API docs and the OpenAPI document are off in production
  (`JUSTFORMS_API_DOCS`); SQL errors never include bound values; access logs carry no query
  strings or link tokens.

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
