# JustForms Helm chart

Deploys JustForms on Kubernetes: the API (`backend`), the background `worker` and the `frontend`
(nginx serving the SPA and proxying `/api/` to the backend), plus a database migration Job.

- **Postgres and Redis are external.** The chart bundles neither; pass their URLs in a Secret.
- **File storage** is a PersistentVolumeClaim (`storage.backend: local`, the default) or an
  external S3-compatible service (`storage.backend: s3`). No object store is bundled.
- **The chart never renders secret values.** Every secret comes from a Secret you create
  beforehand, by hand or synced by an external secrets operator, referenced by name through an
  `existingSecret` value. Placeholders only in values files.

## Quick start

```sh
kubectl create namespace justforms
kubectl -n justforms create secret generic justforms \
  --from-literal=JUSTFORMS_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  --from-literal=JUSTFORMS_DATABASE_URL='postgresql+asyncpg://justforms:change-me@postgres:5432/justforms' \
  --from-literal=JUSTFORMS_REDIS_URL='redis://redis:6379/0'

helm install justforms oci://ghcr.io/alee-ibrahim/charts/justforms --version <version> -n justforms \
  --set publicUrl=https://forms.example.org \
  --set ingress.enabled=true

# Without OIDC, staff sign in with emailed one-time codes: configure smtp.* and create the
# first admin.
kubectl -n justforms exec deploy/justforms-backend -- python -m app.cli create-admin --email you@example.org
```

Released charts are published to `oci://ghcr.io/alee-ibrahim/charts/justforms` with the chart
version equal to the app version; the image tags default to it. From a checkout use
`deploy/helm/justforms` and set `image.*.tag`. Verifying signatures:
[docs/deployment.md](../../../docs/deployment.md#install-from-releases).

`ci/local-values.yaml` and `ci/s3-values.yaml` are complete examples (placeholders only) that
exercise every mode; `just helm-lint` lints and renders both.

## What gets deployed

| Resource | Notes |
|---|---|
| Deployment `<fullname>-backend` + Service | uvicorn on `backend.port` (8000). Probes on `/api/health`. |
| Deployment `<fullname>-worker` | `arq app.worker.WorkerSettings`. No probes by default (no HTTP). |
| Deployment `<fullname>-frontend` + Service | Unprivileged nginx image (uid 101), port 80. Probes on `/`. |
| Job `<fullname>-migrate` | `alembic upgrade head` as a `pre-install,pre-upgrade` hook. |
| PersistentVolumeClaim `<fullname>-storage` | Local storage only, unless `existingClaim`. Kept on `helm uninstall`. |
| ServiceAccount | Optional; token not mounted (the app never calls the Kubernetes API). |
| Ingress / HTTPRoute | Optional; both route everything to the frontend Service. |
| HorizontalPodAutoscaler | Optional, per component. |
| PodDisruptionBudget | Optional, per component. |
| NetworkPolicy | Optional (off by default). |

There is no ServiceMonitor: JustForms has no metrics endpoint yet.

### Migrations

The migration Job is a Helm hook (`pre-install,pre-upgrade`), so new pods start only after the
schema is migrated. Default `hook-delete-policy: before-hook-creation,hook-succeeded`: a
successful Job is removed, a failed one stays for `kubectl logs` until the next attempt. A GitOps
controller that understands Helm hooks runs it as a pre-sync step. Because a hook runs before the
chart's own resources exist, the Job does not use the chart-created ServiceAccount (see
`migrations.serviceAccountName`). The Secrets it reads must already exist, which is the case
with the existingSecret pattern. Set `migrations.enabled: false` to run migrations another way.

### Storage

- `local`: a PVC mounted at `storage.local.mountPath` in backend and worker, made writable for
  uid 10001 through `fsGroup`. With ReadWriteOnce (the default), the backend and worker use the
  `Recreate` strategy and the worker gets a required `podAffinity` to the backend's node; all
  pods sharing the volume must run on one node. Use a ReadWriteMany storage class or `s3` to
  scale across nodes.
- `s3`: create the bucket, a CORS rule for `publicUrl`, and a lifecycle rule expiring `tmp/`
  after a day. Browsers upload and download through presigned URLs, so the bucket origin is
  added to the frontend's CSP `connect-src` automatically (see below).

### Frontend (nginx)

The frontend container gets:

| Env | Value |
|---|---|
| `BACKEND_URL` | `http://<fullname>-backend.<namespace>.svc.<clusterDomain>:<backend.port>`. Fully qualified because nginx resolves it at runtime with `resolver`, which ignores search domains. |
| `NGINX_ENTRYPOINT_LOCAL_RESOLVERS` | `1`: the nginx image exports `NGINX_LOCAL_RESOLVERS` from `/etc/resolv.conf`. |
| `NGINX_RESOLVER` | Only when `frontend.nginxResolver` is set; overrides the resolver. |
| `JUSTFORMS_THAANA_FONT_CSS_URL` | Same as the backend; its origin is allowed in the CSP. |
| `JUSTFORMS_CAPTCHA_PROVIDER` | Same as the backend; the provider's origins are allowed in the CSP. |
| `JUSTFORMS_CSP_EXTRA_CONNECT_SRC` | Space-separated origins: the S3 bucket origin (s3 only) plus `frontend.csp.extraConnectSrc`. |
| `JUSTFORMS_REAL_IP_FROM` / `JUSTFORMS_REAL_IP_HEADER` | `frontend.realIp.from` (comma-joined) / `frontend.realIp.header`. |
| `JUSTFORMS_HSTS` | `frontend.hsts`. |

S3 origins added to the CSP:

| Endpoint | `addressingStyle` | Origins |
|---|---|---|
| empty (AWS) | `virtual` / `auto` | `https://<bucket>.s3.<region>.amazonaws.com https://<bucket>.s3.amazonaws.com` |
| empty (AWS) | `path` | `https://s3.<region>.amazonaws.com` |
| `scheme://host[:port]` | `virtual` | `scheme://<bucket>.host[:port]` |
| `scheme://host[:port]` | `path` | `scheme://host[:port]` |
| `scheme://host[:port]` | `auto` | both of the above |

**Client IP address.** Per-IP rate limits, and the IP recorded with submissions, signatures and
audit entries, need the visitor's address. nginx works it out and sends it to the API as the only
`X-Forwarded-For` hop; whatever a client writes into that header itself is never used.

- `frontend.realIp.from`: what connects to the frontend pods (ingress controller, gateway,
  tunnel connector), as CIDRs. Only requests from these peers may name another client address.
  Empty (default): the peer is the client, so behind an ingress every visitor shares the
  ingress's address and per-IP limits act as global limits. Set it.
- `frontend.realIp.header`: `X-Forwarded-For` (default; the right-most address that is not in
  `from` is used), or a one-address header set by a CDN, e.g. `CF-Connecting-IP`. Use a CDN
  header only when every request reaches the cluster through that CDN (e.g. a tunnel), or a
  client going around it could set the header.
- `trustedProxies` (API side): the frontend pods' range. Default: the private ranges; narrow it
  to your pod CIDR. uvicorn's `FORWARDED_ALLOW_IPS` follows it unless `backend.forwardedAllowIps`
  is set. `*` is refused.

Behind a CDN with a tunnel or ingress in a cluster whose pod CIDR is `10.244.0.0/16`:

```yaml
trustedProxies: ["10.244.0.0/16"]
frontend:
  realIp:
    from: ["10.244.0.0/16"]
    header: CF-Connecting-IP
  hsts: "max-age=31536000; includeSubDomains"
```

*Upgrading:* `backend.forwardedAllowIps` used to default to `*`, which let any client choose its
address. Ingress addresses that were in `trustedProxies` now go in `frontend.realIp.from`.

**HSTS.** `frontend.hsts`: `auto` (default) sends `Strict-Transport-Security` only when the
request came over HTTPS according to `X-Forwarded-Proto`; set the header value to send it on
every response (pages, files and the API), or `off`.

**Access log.** nginx logs the method and path only: no query strings (OIDC codes, search terms),
no referrer, and the token in approver (`/a/`), verify (`/v/`) and invitation links replaced by
`[token]`.

Self-hosted fonts: put `fonts.css` and the font files in a ConfigMap and set
`frontend.fontsConfigMap`; they are served at `/fonts/`.

Server-rendered Thaana (signed PDFs, link-preview images) uses the bundled Noto Sans Thaana
unless you supply a font whose licence allows it, e.g.:

```sh
kubectl create configmap justforms-server-fonts --from-file=Thaana-Regular.ttf
```

```yaml
fonts:
  server:
    configMap: justforms-server-fonts
    thaanaKey: Thaana-Regular.ttf
```

The file is checked when first used (it must cover the Thaana letters; for PDFs its OS/2
`fsType` must allow embedding a subset; link-preview images are rasterised and never contain
the font). A file that fails falls back to Noto Sans Thaana with one warning in the log.
Link-preview images are made again when the font changes. Restart the API and worker after
replacing the file.

### Security

- Backend, worker and migrate run as uid/gid 10001 (`runAsNonRoot`), with a read-only root
  filesystem (`/tmp` is an emptyDir), no privilege escalation, all capabilities dropped and the
  `RuntimeDefault` seccomp profile.
- The frontend runs unprivileged nginx as uid 101 with every capability dropped. It still
  listens on port 80: the pod sets the safe sysctl `net.ipv4.ip_unprivileged_port_start=0`
  (allowed by the `restricted` Pod Security Standard). Its root filesystem is read-only, with
  emptyDirs for `/etc/nginx/conf.d` (rendered templates), `/var/cache/nginx`, `/run` and
  `/tmp`. Backend, worker, migrate and frontend all satisfy `restricted`.
- NetworkPolicies (`networkPolicy.enabled`): the frontend accepts HTTP from
  `networkPolicy.frontend.from` (anyone when empty), the backend only from the frontend, the
  worker from nobody. With `networkPolicy.egress.enabled`, egress is limited to DNS, frontend to
  backend, and `networkPolicy.egress.to` for backend and worker (Postgres, Redis, SMTP, S3, IdP,
  timestamp authority, webhook receivers).

## Secrets

Create these before installing. Key names are the defaults; each is configurable.

| Secret (value) | Key (value that renames it) | Required | Used for |
|---|---|---|---|
| `existingSecret` | `JUSTFORMS_SECRET_KEY` (`existingSecretKeys.secretKey`) | yes | Signs tokens, encrypts app secrets and the PDF signing key. Keep it stable. |
| `existingSecret` | `JUSTFORMS_DATABASE_URL` (`existingSecretKeys.databaseUrl`) | yes | `postgresql+asyncpg://user:pass@host:5432/db` |
| `existingSecret` | `JUSTFORMS_REDIS_URL` (`existingSecretKeys.redisUrl`) | yes | `redis://host:6379/0` |
| `auth.oidc.existingSecret` | `JUSTFORMS_OIDC_CLIENT_SECRET` (`auth.oidc.existingSecretKey`) | with OIDC | OIDC client secret |
| `smtp.existingSecret` | `JUSTFORMS_SMTP_USERNAME` (`smtp.usernameKey`) | no (key optional) | SMTP relay user |
| `smtp.existingSecret` | `JUSTFORMS_SMTP_PASSWORD` (`smtp.passwordKey`) | no (key optional) | SMTP relay password |
| `storage.s3.existingSecret` | `JUSTFORMS_S3_ACCESS_KEY_ID` (`storage.s3.accessKeyIdKey`) | with s3 | S3 access key |
| `storage.s3.existingSecret` | `JUSTFORMS_S3_SECRET_ACCESS_KEY` (`storage.s3.secretAccessKeyKey`) | with s3 | S3 secret key |
| `pdf.signingP12.existingSecret` | `signing.p12` (`pdf.signingP12.fileKey`) | with a P12 | PKCS#12 file, mounted read-only at `<pdf.signingP12.mountPath>/signing.p12` |
| `pdf.signingP12.existingSecret` | `JUSTFORMS_PDF_SIGNING_P12_PASSWORD` (`pdf.signingP12.passwordKey`) | with a P12 | Its password |
| `captcha.existingSecret` | `JUSTFORMS_CAPTCHA_SECRET_KEY` (`captcha.existingSecretKey`) | turnstile, hcaptcha | Server-side verification key. Not used by `altcha`, which signs challenges with `JUSTFORMS_SECRET_KEY`. |
| `errorTracking.existingSecret` | `JUSTFORMS_SENTRY_DSN` (`errorTracking.existingSecretKey`) | no | Error-tracking DSN, when it is kept in a Secret rather than `errorTracking.dsn` |
| `ai.existingSecret` | `JUSTFORMS_AI_API_KEY` (`ai.existingSecretKey`) | gemini, anthropic (optional for openai_compat) | AI provider key. Use a key issued for JustForms only. |

Several of these may be the same Secret. For the signing certificate:

```sh
kubectl -n justforms create secret generic justforms-pdf-signing \
  --from-file=signing.p12=./org-signing.p12 \
  --from-literal=JUSTFORMS_PDF_SIGNING_P12_PASSWORD='change-me'
```

## Staff sign-in

- `auth.oidc.enabled: true`: OIDC with `issuer`, `clientId` and the client secret from
  `auth.oidc.existingSecret`. Register `{publicUrl}/api/v1/auth/callback` as the redirect URI.
  `adminGroups` / `creatorGroups` / `memberGroups` map IdP groups (claim `groupsClaim`) to roles
  in the default organisation (admin > form creator > member). Without group mapping, people get
  `defaultRole` (`creator`, `member` or `none`) the first time they sign in.
  `superadminGroups` (exact group names or IDs, independent of the role groups) makes people
  superadmins at sign-in and takes it away from those who left the groups, except superadmins
  created with `create-admin`. An SSO superadmin is also made admin of the default organisation
  (never demoted when the group is left; an admin can change it). With Entra ID, emit only groups assigned to the application to
  avoid group overage (the token then has no `groups` claim and nothing changes). Admins can also
  invite people from Organisation settings › People; invitations are accepted when that email
  signs in.
  `autoRedirect` (default `true`) sends signed-out visitors of the sign-in page and the studio
  straight to the IdP, with no button press; invitation links do the same with the invited
  address as the login hint. It never does so right after signing out ("You're signed out" page),
  after a failed sign-in (error page with "Try again"), with `/login?manual=1`, or twice within
  30 seconds. Public forms, approver and verify pages are not affected.
- Otherwise staff sign in with **one-time codes sent by email**, so configure `smtp.*`. Only
  existing users and people with an open invitation can sign in: create the first admin with
  `kubectl exec deploy/<fullname>-backend -- python -m app.cli create-admin --email you@example.org`.
- Demo installs only: `JUSTFORMS_DEMO_LOGIN_CODE` + `JUSTFORMS_DEMO_LOGIN_EMAILS` (via `extraEnv`,
  commented example in `values.yaml`) accept a fixed code for the listed addresses. The chart
  never sets them; don't use them on a real install.

## Values

Environment variables in the last column are set on backend, worker and the migration Job
unless noted.

### Core

| Value | Default | Env / notes |
|---|---|---|
| `nameOverride`, `fullnameOverride` | `""` | Resource naming |
| `commonLabels` | `{}` | Added to every resource |
| `clusterDomain` | `cluster.local` | Used in the frontend's `BACKEND_URL` |
| `image.backend.repository` / `.tag` | `ghcr.io/alee-ibrahim/justforms-backend` / appVersion | Backend, worker, migrate |
| `image.frontend.repository` / `.tag` | `ghcr.io/alee-ibrahim/justforms-frontend` / appVersion | Frontend |
| `image.pullPolicy` | `IfNotPresent` | |
| `imagePullSecrets` | `[]` | |
| `serviceAccount.create` / `.name` / `.annotations` / `.automountServiceAccountToken` | `true` / `""` / `{}` / `false` | |
| `publicUrl` | `https://justforms.example.com` | `JUSTFORMS_PUBLIC_URL`; default Ingress/HTTPRoute host |
| `environment` | `production` | `JUSTFORMS_ENVIRONMENT` |
| `timezone` | `UTC` | `JUSTFORMS_TIMEZONE` |
| `trustedProxies` | private ranges | `JUSTFORMS_TRUSTED_PROXIES` (comma-joined): the frontend pods, whose `X-Forwarded-For` the API trusts. Narrow it to your pod CIDR; see [Client IP address](#frontend-nginx) |
| `maxUploadMb` | `25` | `JUSTFORMS_MAX_UPLOAD_MB` |
| `trash.days` | `30` | `JUSTFORMS_TRASH_DAYS`: days deleted forms and submissions stay restorable before the worker erases them |
| `thaanaFontCssUrl` | dvfonts CDN | `JUSTFORMS_THAANA_FONT_CSS_URL` (also on the frontend) |
| `thaanaFonts` | `[]` (built-in list) | `JUSTFORMS_THAANA_FONTS` (comma-joined): Thaana fonts form themes can choose |
| `fonts.server.configMap` / `.secret` | `""` | ConfigMap (`binaryData`) or Secret holding a Thaana TTF/OTF for server rendering (signed PDFs, link-preview images), mounted read-only at `fonts.server.mountPath` (`/etc/justforms/fonts`) in the API, worker and migration job. Empty: the bundled Noto Sans Thaana |
| `fonts.server.thaanaKey` / `.thaanaBoldKey` | `""` | Keys (file names) in it; set `JUSTFORMS_THAANA_FONT_FILE` / `JUSTFORMS_THAANA_FONT_BOLD_FILE`. Bold is optional (the regular file is used for bold) |
| `cookieSecure` | `true` | `JUSTFORMS_COOKIE_SECURE`; `null` omits it (backend default: on in production) |
| `corsOrigins` | `[]` | `JUSTFORMS_CORS_ORIGINS`; empty means `[publicUrl]` |
| `existingSecret` | `justforms` | Main Secret (see [Secrets](#secrets)) |
| `existingSecretKeys.secretKey` / `.databaseUrl` / `.redisUrl` | env var names | Key names in the main Secret |

### Auth, email, storage, PDFs, abuse controls

| Value | Default | Env / notes |
|---|---|---|
| `auth.oidc.enabled` | `false` | Off: emailed one-time codes |
| `auth.oidc.issuer` | `""` | `JUSTFORMS_OIDC_ISSUER` |
| `auth.oidc.discoveryUrl` | `""` | `JUSTFORMS_OIDC_DISCOVERY_URL` (only if the issuer is unreachable from pods) |
| `auth.oidc.clientId` | `""` | `JUSTFORMS_OIDC_CLIENT_ID` |
| `auth.oidc.scopes` | `openid email profile` | `JUSTFORMS_OIDC_SCOPES` |
| `auth.oidc.groupsClaim` | `groups` | `JUSTFORMS_OIDC_GROUPS_CLAIM` |
| `auth.oidc.adminGroups` / `.creatorGroups` / `.memberGroups` | `[]` | `JUSTFORMS_OIDC_ADMIN_GROUPS` / `_CREATOR_GROUPS` / `_MEMBER_GROUPS` |
| `auth.oidc.superadminGroups` | `[]` | `JUSTFORMS_OIDC_SUPERADMIN_GROUPS` |
| `auth.oidc.defaultRole` | `creator` | `JUSTFORMS_OIDC_DEFAULT_ROLE` (`creator`, `member`, `none`) |
| `auth.oidc.autoRedirect` | `true` | `JUSTFORMS_OIDC_AUTO_REDIRECT`: signed-out studio visits go straight to the IdP |
| `auth.oidc.trustEmail` | `false` | `JUSTFORMS_OIDC_TRUST_EMAIL`: treat the IdP's email as verified without `email_verified` (single-tenant Entra ID with administrator-managed addresses; never multi-tenant/guest) |
| `auth.oidc.emailFallbackClaims` | `[]` | `JUSTFORMS_OIDC_EMAIL_FALLBACK_CLAIMS`: claims read when the token has no `email`, e.g. `[preferred_username]` |
| `auth.oidc.existingSecret` / `.existingSecretKey` | `""` / `JUSTFORMS_OIDC_CLIENT_SECRET` | `JUSTFORMS_OIDC_CLIENT_SECRET` |
| `smtp.host` | `""` | `JUSTFORMS_SMTP_HOST` (empty: no email) |
| `smtp.port` | `587` | `JUSTFORMS_SMTP_PORT` |
| `smtp.security` | `starttls` | `JUSTFORMS_SMTP_SECURITY`: `none`, `starttls`, `tls` |
| `smtp.from` | `JustForms <no-reply@example.com>` | `JUSTFORMS_SMTP_FROM` |
| `smtp.existingSecret` / `.usernameKey` / `.passwordKey` | `""` / env names | `JUSTFORMS_SMTP_USERNAME`, `JUSTFORMS_SMTP_PASSWORD` |
| `storage.backend` | `local` | `JUSTFORMS_STORAGE_BACKEND`: `local` or `s3` |
| `storage.local.mountPath` | `/data/storage` | `JUSTFORMS_STORAGE_LOCAL_PATH` |
| `storage.local.persistence.existingClaim` | `""` | Use an existing PVC |
| `storage.local.persistence.size` / `.storageClass` / `.accessModes` | `10Gi` / `""` / `[ReadWriteOnce]` | |
| `storage.s3.endpointUrl` | `""` | `JUSTFORMS_S3_ENDPOINT_URL` (empty: AWS) |
| `storage.s3.publicEndpointUrl` | `""` | `JUSTFORMS_S3_PUBLIC_ENDPOINT_URL`: endpoint in presigned URLs for browsers when it differs from `endpointUrl` (e.g. in-cluster Service for the backend, public hostname for browsers). The CSP then allows this origin instead |
| `storage.s3.region` | `us-east-1` | `JUSTFORMS_S3_REGION` |
| `storage.s3.bucket` | `""` | `JUSTFORMS_S3_BUCKET` (required for s3) |
| `storage.s3.addressingStyle` | `auto` | `JUSTFORMS_S3_ADDRESSING_STYLE`: `auto`, `path`, `virtual` |
| `storage.s3.existingSecret` / `.accessKeyIdKey` / `.secretAccessKeyKey` | `""` / env names | `JUSTFORMS_S3_ACCESS_KEY_ID`, `JUSTFORMS_S3_SECRET_ACCESS_KEY` |
| `pdf.signingP12.existingSecret` | `""` | Sets `JUSTFORMS_PDF_SIGNING_P12` and `JUSTFORMS_PDF_SIGNING_P12_PASSWORD` |
| `pdf.signingP12.fileKey` / `.passwordKey` | `signing.p12` / `JUSTFORMS_PDF_SIGNING_P12_PASSWORD` | Keys in that Secret |
| `pdf.signingP12.mountPath` | `/run/secrets/justforms-pdf` | Read-only mount |
| `pdf.tsaUrl` | `""` | `JUSTFORMS_PDF_TSA_URL` |
| `pdf.signerName` | `""` | `JUSTFORMS_PDF_SIGNER_NAME` (empty: app default) |
| `captcha.provider` | `none` | `JUSTFORMS_CAPTCHA_PROVIDER`: `none`, `altcha`, `turnstile`, `hcaptcha` (also on the frontend) |
| `captcha.siteKey` | `""` | `JUSTFORMS_CAPTCHA_SITE_KEY` (turnstile, hcaptcha) |
| `captcha.existingSecret` / `.existingSecretKey` | `""` / `JUSTFORMS_CAPTCHA_SECRET_KEY` | `JUSTFORMS_CAPTCHA_SECRET_KEY` |
| `rateLimits.enabled` | `true` | `JUSTFORMS_RATE_LIMIT_ENABLED` |
| `branding.name` / `branding.primaryColor` / `branding.supportUrl` | `""` | Instance defaults `JUSTFORMS_BRAND_NAME`, `JUSTFORMS_BRAND_PRIMARY_COLOR` (`#RRGGBB`), `JUSTFORMS_BRAND_SUPPORT_URL`; organisations override them in the studio |
| `branding.poweredBy` | `optional` | `JUSTFORMS_BRAND_POWERED_BY`: `always` keeps "Powered by JustForms" on every form |
| `branding.configMap` + `logoKey` / `logoDarkKey` / `iconKey` | `""` | ConfigMap of PNG/SVG files (use `binaryData` for PNG) mounted at `branding.mountPath`; sets `JUSTFORMS_BRAND_LOGO_FILE`, `_LOGO_DARK_FILE`, `_ICON_FILE` |
| `ai.provider` | `none` | `JUSTFORMS_AI_PROVIDER`: `none` (AI hidden), `gemini`, `anthropic`, `openai_compat` |
| `ai.model` / `ai.visionModel` | `""` | `JUSTFORMS_AI_MODEL` (required with a provider), `JUSTFORMS_AI_VISION_MODEL` (blank paper forms; default: the model) |
| `ai.baseUrl` | `""` | `JUSTFORMS_AI_BASE_URL` (required for `openai_compat`, e.g. a vLLM or Ollama `/v1` URL) |
| `ai.vision` | `""` | `JUSTFORMS_AI_VISION` (`true`/`false`; empty: on for gemini and anthropic, off for openai_compat) |
| `ai.providerLabel` | `""` | `JUSTFORMS_AI_PROVIDER_LABEL`: deprecated and ignored (the studio never names the provider) |
| `ai.dailyTokensPerUser` / `ai.dailyTokensPerOrg` | `""` | `JUSTFORMS_AI_DAILY_TOKENS_PER_USER` / `_PER_ORG` (empty: app defaults 300k / 3M) |
| `ai.existingSecret` / `.existingSecretKey` | `""` / `JUSTFORMS_AI_API_KEY` | `JUSTFORMS_AI_API_KEY` |
| `webhooks.allowedCidrs` | `[]` | `JUSTFORMS_WEBHOOK_ALLOWED_CIDRS` (comma-joined) |
| `errorTracking.dsn` | `""` | `JUSTFORMS_SENTRY_DSN`: Sentry-protocol DSN (Sentry, GlitchTip) for the API and worker; empty: off |
| `errorTracking.existingSecret` / `.existingSecretKey` | `""` / `JUSTFORMS_SENTRY_DSN` | Read the DSN from a Secret instead (used when `dsn` is empty; optional key: missing means off) |
| `errorTracking.browserDsn` | `""` | `JUSTFORMS_SENTRY_BROWSER_DSN`: empty = same as the DSN; `off` = no browser reports. Browsers send through the API's same-origin tunnel |
| `errorTracking.browserTunnel` | `true` | `JUSTFORMS_SENTRY_BROWSER_TUNNEL`: `false` sends browser reports straight to `browserDsn` (public host) and adds its origin to the CSP `connect-src` |
| `errorTracking.environment` / `.tracesSampleRate` | `""` | `JUSTFORMS_SENTRY_ENVIRONMENT` (default: `environment`), `JUSTFORMS_SENTRY_TRACES_SAMPLE_RATE` (default 0) |
| `config` | `{}` | Free-form non-secret `JUSTFORMS_*` env; don't repeat settings that have a value above |
| `extraEnv` / `extraEnvFrom` | `[]` | Extra `env` / `envFrom` entries |
| `extraVolumes` / `extraVolumeMounts` | `[]` | Extra volumes and mounts |

### Workloads

| Value | Default | Notes |
|---|---|---|
| `podSecurityContext` | uid/gid/fsGroup 10001, non-root, RuntimeDefault | Backend, worker, migrate |
| `containerSecurityContext` | read-only root, drop ALL, no escalation | Backend, worker, migrate |
| `backend.replicas` / `.port` | `1` / `8000` | |
| `backend.forwardedAllowIps` | `""` | uvicorn `FORWARDED_ALLOW_IPS` (backend only); empty: `trustedProxies`. `*` is refused |
| `backend.readinessProbe` / `.livenessProbe` | HTTP `/api/health` | |
| `backend.service.type` / `.annotations` | `ClusterIP` / `{}` | |
| `worker.replicas` | `1` | |
| `worker.affinity` | `{}` | Empty + RWO local storage: podAffinity to the backend's node |
| `worker.livenessProbe` | `{}` | |
| `frontend.replicas` / `.port` | `1` / `80` | |
| `frontend.fontsConfigMap` | `""` | ConfigMap served at `/fonts/` |
| `frontend.csp.extraConnectSrc` | `[]` | Extra CSP origins |
| `frontend.nginxResolver` | `""` | `NGINX_RESOLVER` |
| `frontend.realIp.from` / `.header` | `[]` / `X-Forwarded-For` | Proxies in front of the frontend and the header they put the client address in (see [Client IP address](#frontend-nginx)) |
| `frontend.hsts` | `auto` | `Strict-Transport-Security`: `auto`, `off` or the value to always send |
| `frontend.podSecurityContext` / `.securityContext` | see [Security](#security) | |
| `frontend.readinessProbe` / `.livenessProbe` | HTTP `/` | |
| `frontend.service.type` / `.annotations` | `ClusterIP` / `{}` | |
| `<component>.resources`, `.podAnnotations`, `.podLabels`, `.nodeSelector`, `.tolerations`, `.affinity`, `.topologySpreadConstraints`, `.priorityClassName` | empty | Per component (`backend`, `worker`, `frontend`) |
| `<component>.autoscaling.enabled` / `.minReplicas` / `.maxReplicas` / `.targetCPUUtilizationPercentage` / `.targetMemoryUtilizationPercentage` | `false` / … / `75` / `null` | HPA; `replicas` is then omitted |
| `<component>.pdb.enabled` / `.minAvailable` / `.maxUnavailable` | `false` / `null` / `1` | `minAvailable` wins when set |
| `migrations.enabled` | `true` | Hook Job |
| `migrations.backoffLimit` / `.activeDeadlineSeconds` | `3` / `600` | |
| `migrations.hookDeletePolicy` | `before-hook-creation,hook-succeeded` | |
| `migrations.resources` / `.podAnnotations` / `.nodeSelector` / `.tolerations` / `.priorityClassName` | empty | |
| `migrations.serviceAccountName` | `""` | Used when `serviceAccount.create` is true (otherwise `serviceAccount.name`); empty: namespace default |

### Exposure and network

| Value | Default | Notes |
|---|---|---|
| `ingress.enabled` / `.className` / `.annotations` | `false` / `""` / `{}` | |
| `ingress.host` | `""` | Empty: host of `publicUrl` |
| `ingress.tls` | `[]` | Standard Ingress TLS list |
| `httpRoute.enabled` / `.annotations` | `false` / `{}` | Gateway API `HTTPRoute` (v1) |
| `httpRoute.parentRefs` | `[]` | Required when enabled |
| `httpRoute.hostnames` | `[]` | Empty: host of `publicUrl` |
| `httpRoute.timeouts` | `{request: 60s}` | Timeouts of the catch-all rule. `{}`: the gateway's defaults (some end a request after 15 s) |
| `httpRoute.longRequests.matches` / `.timeouts` | AI streams, uploads, downloads, exports, PDFs / `{request: 300s}` | A rule before the catch-all for requests that may run long (AI answers stream for up to `JUSTFORMS_AI_TURN_SECONDS`). Gateway API `HTTPRouteMatch` list; `[]` disables it |
| `networkPolicy.enabled` | `false` | |
| `networkPolicy.frontend.from` | `[]` | NetworkPolicy peers allowed to reach the frontend (empty: any) |
| `networkPolicy.egress.enabled` | `false` | Restrict egress too |
| `networkPolicy.egress.dnsNamespaceSelector` | `kubernetes.io/metadata.name: kube-system` | Where cluster DNS runs |
| `networkPolicy.egress.to` | `[]` | NetworkPolicy egress rules for backend and worker |

`values.schema.json` validates types and enums; the templates also fail early on missing
required settings (bucket, OIDC issuer/client/secret, CAPTCHA site key/secret, …).
