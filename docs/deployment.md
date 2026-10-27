# Deployment

JustForms runs as an API, a background worker and a web container (nginx serving the SPA and
proxying `/api`), with PostgreSQL and Redis. Use Docker Compose on one server or the Helm chart
on Kubernetes. Settings are listed in [Configuration](configuration.md).

- [Install from releases](#install-from-releases)
- [Docker Compose](#docker-compose)
- [Development Keycloak (OIDC)](#development-keycloak-oidc)
- [Cloudflare Tunnel](#cloudflare-tunnel)
- [Reverse proxies](#reverse-proxies)
- [Kubernetes (Helm)](#kubernetes-helm)
- [Upgrades and migrations](#upgrades-and-migrations)
- [Backups](#backups)

## Install from releases

Every release (`vX.Y.Z` tag) publishes, from this repository's release workflow:

| Artifact | Reference |
|---|---|
| API, worker and migrations | `ghcr.io/alee-ibrahim/justforms-backend:X.Y.Z` |
| Web container (nginx + SPA) | `ghcr.io/alee-ibrahim/justforms-frontend:X.Y.Z` |
| Helm chart (version = app version) | `oci://ghcr.io/alee-ibrahim/charts/justforms`, version `X.Y.Z` |

Images are built for linux/amd64 and linux/arm64. Tags: `X.Y.Z` (one release), `X.Y` (newest
patch of that minor), `latest` (newest release) and `sha-<commit>`. A release is only cut from a
commit on `main` whose CI passed, and images with a critical vulnerability that has a fix are not
published (Trivy). The [releases page](https://github.com/alee-ibrahim/justforms/releases) lists
the changes and the image digests, with SPDX SBOMs attached.

Pin a full version (or `version@sha256:digest`) in production and upgrade by changing it: the
new release's migrations run automatically (see [Upgrades](#upgrades-and-migrations)).
JustForms follows semantic versioning; before 1.0 a minor release (0.X) may need a config change,
which its release notes say. A patch release (X.Y.Z) never changes the chart's templates or
values (the release workflow refuses it), so the chart of X.Y.0 runs every X.Y.Z image: it is safe
to pin the chart and let an image updater follow `X.Y.*` tags.

### Helm

```sh
helm install justforms oci://ghcr.io/alee-ibrahim/charts/justforms --version X.Y.Z \
  -n justforms --create-namespace -f values.yaml
helm show values oci://ghcr.io/alee-ibrahim/charts/justforms --version X.Y.Z   # every value
```

The chart's image tags default to its app version, so a chart version runs the images of the
same release. A GitOps controller can track the same OCI chart, and an image updater can follow
new `X.Y.Z` tags (semver constraint) for automatic upgrades.

### Docker Compose

```sh
cd deploy/compose              # from a checkout of the release tag
cp .env.example .env           # set JUSTFORMS_VERSION=X.Y.Z and the change-me values
docker compose -f docker-compose.yml -f docker-compose.release.yml pull
docker compose -f docker-compose.yml -f docker-compose.release.yml up -d
```

### Verify signatures and provenance

Images and the chart are signed with [cosign](https://docs.sigstore.dev/cosign/) without a
long-lived key: the signing certificate names this repository's release workflow and the tag it
ran for, and the signature is recorded in the public Sigstore transparency log.

```sh
cosign verify ghcr.io/alee-ibrahim/justforms-backend:X.Y.Z \
  --certificate-identity-regexp '^https://github\.com/alee-ibrahim/justforms/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
cosign verify ghcr.io/alee-ibrahim/charts/justforms:X.Y.Z \
  --certificate-identity-regexp '^https://github\.com/alee-ibrahim/justforms/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The same works for `justforms-frontend`. Build provenance (SLSA) and the SBOM are attestations;
check them with the GitHub CLI:

```sh
gh attestation verify oci://ghcr.io/alee-ibrahim/justforms-backend:X.Y.Z --repo alee-ibrahim/justforms
gh attestation verify oci://ghcr.io/alee-ibrahim/justforms-backend:X.Y.Z --repo alee-ibrahim/justforms \
  --predicate-type https://spdx.dev/Document/v2.3
```

A registry mirror or pull-through cache serves the same digests but may not carry the signatures
(OCI referrers): verify the digest you run against `ghcr.io/alee-ibrahim/...@sha256:<digest>`.

## Docker Compose

`deploy/compose/docker-compose.yml` runs PostgreSQL, Redis, the API, the worker, a one-off
migration job and the web container. Files go to the `storage-data` volume unless S3 is
configured.

```sh
git clone https://github.com/alee-ibrahim/justforms.git && cd justforms/deploy/compose
cp .env.example .env      # set JUSTFORMS_SECRET_KEY and the change-me passwords
docker compose --profile dev up -d --build
docker compose run --rm migrate python -m app.cli create-admin --email you@example.org
```

Open http://localhost:8080 and sign in with that email. The one-time code arrives in Mailpit at
http://localhost:8025 (started by the `dev` profile).

For a real install:

- drop the `dev` profile and point the `JUSTFORMS_SMTP_*` settings at your mail relay;
- put it behind a TLS proxy (or a [tunnel](#cloudflare-tunnel)), and set
  `JUSTFORMS_PUBLIC_URL` and `JUSTFORMS_COOKIE_SECURE=true`;
- if a proxy, load balancer or tunnel sits in front of the web container, tell it about that
  proxy (`JUSTFORMS_REAL_IP_FROM`, see [Client IP address](#client-ip-address)) so rate limits
  and the recorded client IP use the visitor's address.

| Profile | Adds |
|---|---|
| `dev` | Mailpit (SMTP catcher, UI on http://localhost:8025) |
| `tunnel` | A named Cloudflare Tunnel |
| `quick-tunnel` | A temporary trycloudflare.com URL |

`just compose-up`, `just compose-down` and `just compose-config` wrap the common commands.

## Development Keycloak (OIDC)

To try single sign-on, add the development Keycloak overlay. It imports a realm with users
`admin` and `member` (password `KEYCLOAK_DEV_USER_PASSWORD`) whose groups map to the org admin
and member roles. Set `KEYCLOAK_DEV_CLIENT_SECRET` and `KEYCLOAK_DEV_USER_PASSWORD` in `.env`,
then:

```sh
docker compose -f docker-compose.yml -f docker-compose.keycloak.yml --profile dev up -d --build
```

or `just compose-keycloak`. It is for development only.

## Cloudflare Tunnel

The compose file has two optional `cloudflared` services that publish the web container over
HTTPS without opening a port:

| Profile | Recipe | What you get |
|---|---|---|
| `tunnel` | `just tunnel` | A named tunnel. Create it in the Cloudflare dashboard, set its public hostname's service to `http://frontend:80` and put the token in `CLOUDFLARE_TUNNEL_TOKEN` |
| `quick-tunnel` | `just quick-tunnel` | A temporary `https://<random>.trycloudflare.com` URL, no account needed. For demos: the URL changes whenever the container restarts |

JustForms builds every link it sends (sign-in redirects, emails, approver links, the QR code on
signed PDFs) from `JUSTFORMS_PUBLIC_URL`, and checks the `Origin` of state-changing requests
against it, so it **must** be the tunnel's URL. In `deploy/compose/.env`:

```sh
JUSTFORMS_PUBLIC_URL=https://forms.example.org   # the tunnel hostname, no trailing slash
JUSTFORMS_COOKIE_SECURE=true
JUSTFORMS_REAL_IP_FROM=172.16.0.0/12              # the tunnel container (Docker networks)
JUSTFORMS_REAL_IP_HEADER=CF-Connecting-IP         # the visitor's address, set by the CDN
CLOUDFLARE_TUNNEL_TOKEN=...                     # named tunnel only
```

```sh
docker compose --profile tunnel up -d --build         # or: just tunnel
docker compose --profile quick-tunnel up -d --build   # or: just quick-tunnel
docker compose logs cloudflared-quick | grep trycloudflare.com
docker compose up -d backend worker                   # after changing JUSTFORMS_PUBLIC_URL
```

nginx passes the tunnel's `X-Forwarded-Proto: https` on to the API and then sends HSTS
(`JUSTFORMS_HSTS=auto`; set a value such as `max-age=31536000; includeSubDomains` to always send
it). With `CF-Connecting-IP` trusted from Docker networks, keep `JUSTFORMS_HTTP_PORT` off the
public network (e.g. a firewall), or a client reaching it through Docker's port proxy could set
that header. Add
`--profile dev` for Mailpit; its UI stays on localhost and is not published through the tunnel.

## Reverse proxies

Behind your own reverse proxy:

- forward `X-Forwarded-For` (appending, as proxies normally do) and `X-Forwarded-Proto`, and
  list the proxy in `JUSTFORMS_REAL_IP_FROM` on the web container (see below);
- don't buffer `/api/v1/forms/*/ai/` (the AI assistant streams Server-Sent Events) and allow
  reads of a few minutes there. Details: [DESIGN.md §12](DESIGN.md#12-ai-design).

### Client IP address

Per-IP rate limits and the IP address recorded with submissions, signatures and audit entries
need the visitor's address, which a client must not be able to choose. The web container (nginx)
works it out and sends it to the API as the only `X-Forwarded-For` hop:

| Variable (web container) | Default | Purpose |
|---|---|---|
| `JUSTFORMS_REAL_IP_FROM` | empty | Proxies in front of the web container (CIDRs, comma-separated). Only these peers may name another client address. Empty: the peer is the client |
| `JUSTFORMS_REAL_IP_HEADER` | `X-Forwarded-For` | Where those proxies put the address. With `X-Forwarded-For` the right-most address that is not one of the proxies is used, so entries a client wrote are ignored. A one-address CDN header such as `CF-Connecting-IP` is safe only when every request comes through that CDN |
| `JUSTFORMS_HSTS` | `auto` | `Strict-Transport-Security` on every response, the API included: `auto` (only when `X-Forwarded-Proto` is `https`), `off`, or the value to always send |

The API takes `X-Forwarded-For` only from `JUSTFORMS_TRUSTED_PROXIES` (compose default: the
private ranges, since only the web container reaches it; Helm: `trustedProxies`, narrow it to
the pod CIDR) and uses the right-most hop that is not a trusted proxy. uvicorn's
`FORWARDED_ALLOW_IPS` must list the same addresses or fewer; the API refuses to start in
production with `*`, which would let the client choose its address.

nginx logs the method and path only: no query strings (sign-in codes, searches), no referrer, and
the token in approver, verify and invitation links replaced by `[token]`.

## Kubernetes (Helm)

`deploy/helm/justforms` deploys the API, worker and web frontend, with migrations as a
pre-install/pre-upgrade hook Job. PostgreSQL and Redis are external; files go to a PVC or S3.
The chart never renders secrets: create a Secret with `JUSTFORMS_SECRET_KEY`,
`JUSTFORMS_DATABASE_URL` and `JUSTFORMS_REDIS_URL` (plus optional Secrets for OIDC, SMTP, S3,
CAPTCHA, AI and a PDF signing certificate), then:

```sh
helm install justforms oci://ghcr.io/alee-ibrahim/charts/justforms --version X.Y.Z -n justforms \
  --set publicUrl=https://forms.example.org --set existingSecret=justforms --set ingress.enabled=true
```

From a checkout, `deploy/helm/justforms` works the same way; set `image.*.tag` to images you built.

Every value and Secret key is listed in
[deploy/helm/justforms/README.md](../deploy/helm/justforms/README.md). Optional HPA, PDB and
Gateway API HTTPRoute are included; `just helm-lint` lints the chart against the example values
in `deploy/helm/justforms/ci/`. Branding defaults are `branding.*` values; self-hosted Thaana
fonts go in a ConfigMap set as `frontend.fontsConfigMap`.

## Upgrades and migrations

Database migrations are Alembic revisions and run automatically:

- **Compose:** the `migrate` job runs on every `up`, and the API and worker start only after it
  succeeds. With release images, set the new `JUSTFORMS_VERSION`, then `pull` and `up -d` with
  `docker-compose.release.yml`; from source, pull the new code and run `docker compose up -d --build`
  (with the same profiles as before).
- **Helm:** migrations run as a pre-upgrade hook Job; `helm upgrade` with the new chart version.

Migrations only go forward. Rolling back to an older release is safe only when the newer
release's migrations were additive (its release notes say so); otherwise restore the database
backup taken before the upgrade.

Keep `JUSTFORMS_SECRET_KEY` the same across upgrades: it encrypts the PDF signing key. If it
must change, run `python -m app.cli init-signing-key --rotate` (see
[Security](security.md#signed-pdfs-and-the-verify-page)).

## Backups

Back up three things together:

- the PostgreSQL database;
- the files: the `storage-data` volume (Compose), the PVC (Helm) or your S3 bucket;
- `JUSTFORMS_SECRET_KEY`, without which the stored signing key can't be decrypted.
