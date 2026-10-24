# Deployment

JustForms runs as an API, a background worker and a web container (nginx serving the SPA and
proxying `/api`), with PostgreSQL and Redis. Use Docker Compose on one server or the Helm chart
on Kubernetes. Settings are listed in [Configuration](configuration.md).

- [Docker Compose](#docker-compose)
- [Development Keycloak (OIDC)](#development-keycloak-oidc)
- [Cloudflare Tunnel](#cloudflare-tunnel)
- [Reverse proxies](#reverse-proxies)
- [Kubernetes (Helm)](#kubernetes-helm)
- [Upgrades and migrations](#upgrades-and-migrations)
- [Backups](#backups)

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
- set `JUSTFORMS_TRUSTED_PROXIES` so the recorded client IP is the real one.

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
JUSTFORMS_TRUSTED_PROXIES=172.16.0.0/12           # Docker networks, for the recorded client IP
CLOUDFLARE_TUNNEL_TOKEN=...                     # named tunnel only
```

```sh
docker compose --profile tunnel up -d --build         # or: just tunnel
docker compose --profile quick-tunnel up -d --build   # or: just quick-tunnel
docker compose logs cloudflared-quick | grep trycloudflare.com
docker compose up -d backend worker                   # after changing JUSTFORMS_PUBLIC_URL
```

nginx passes the tunnel's `X-Forwarded-Proto: https` on to the API and then sends HSTS. Add
`--profile dev` for Mailpit; its UI stays on localhost and is not published through the tunnel.

## Reverse proxies

Behind your own reverse proxy:

- forward `X-Forwarded-For` and `X-Forwarded-Proto`, and list the proxy in
  `JUSTFORMS_TRUSTED_PROXIES`;
- don't buffer `/api/v1/forms/*/ai/` (the AI assistant streams Server-Sent Events) and allow
  reads of a few minutes there. Details: [DESIGN.md §12](DESIGN.md#12-ai-design).

## Kubernetes (Helm)

`deploy/helm/justforms` deploys the API, worker and web frontend, with migrations as a
pre-install/pre-upgrade hook Job. PostgreSQL and Redis are external; files go to a PVC or S3.
The chart never renders secrets: create a Secret with `JUSTFORMS_SECRET_KEY`,
`JUSTFORMS_DATABASE_URL` and `JUSTFORMS_REDIS_URL` (plus optional Secrets for OIDC, SMTP, S3,
CAPTCHA, AI and a PDF signing certificate), then:

```sh
helm install justforms deploy/helm/justforms -n justforms \
  --set publicUrl=https://forms.example.org --set existingSecret=justforms --set ingress.enabled=true
```

Every value and Secret key is listed in
[deploy/helm/justforms/README.md](../deploy/helm/justforms/README.md). Optional HPA, PDB and
Gateway API HTTPRoute are included; `just helm-lint` lints the chart against the example values
in `deploy/helm/justforms/ci/`. Branding defaults are `branding.*` values; self-hosted Thaana
fonts go in a ConfigMap set as `frontend.fontsConfigMap`.

## Upgrades and migrations

Database migrations are Alembic revisions and run automatically:

- **Compose:** the `migrate` job runs on every `up`, and the API and worker start only after it
  succeeds. To upgrade, pull the new code and run `docker compose up -d --build` (with the same
  profiles as before).
- **Helm:** migrations run as a pre-upgrade hook Job; `helm upgrade` with the new chart.

Keep `JUSTFORMS_SECRET_KEY` the same across upgrades: it encrypts the PDF signing key. If it
must change, run `python -m app.cli init-signing-key --rotate` (see
[Security](security.md#signed-pdfs-and-the-verify-page)).

## Backups

Back up three things together:

- the PostgreSQL database;
- the files: the `storage-data` volume (Compose), the PVC (Helm) or your S3 bucket;
- `JUSTFORMS_SECRET_KEY`, without which the stored signing key can't be decrypted.
