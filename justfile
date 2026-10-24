# JustForms task runner. Install just: https://just.systems (e.g. `uv tool install rust-just`).
# Run `just` to list recipes.

compose := "docker compose -f deploy/compose/docker-compose.yml"

# List recipes
default:
    @just --list --unsorted

# uv sync + pnpm install
install:
    cd backend && uv sync
    cd frontend && pnpm install --frozen-lockfile

# Start postgres and redis in Docker (for running the app outside Docker)
infra:
    {{ compose }} up -d postgres redis

# Stop the infra containers
infra-down:
    {{ compose }} stop postgres redis

# Apply database migrations (alembic upgrade head)
migrate:
    cd backend && uv run alembic upgrade head

# Create (or promote) the first administrator: just create-admin you@example.org
create-admin email:
    cd backend && uv run python -m app.cli create-admin --email {{ email }}

# Regenerate spec/form-schema.v1.json and the frontend types after changing the schema
spec:
    cd backend && uv run python -m app.schemas.export
    cd frontend && pnpm gen:schema

# Fail if any generated schema artifact is stale
check-spec:
    cd backend && uv run python -m app.schemas.export --check
    cd frontend && pnpm check:schema

# Run API, worker and Vite dev server together (Ctrl-C stops all)
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    just dev-backend &
    just dev-worker &
    just dev-frontend &
    wait

# API with reload on :8000
dev-backend:
    cd backend && uv run uvicorn app.main:app --reload --port 8000

# arq worker
dev-worker:
    cd backend && uv run arq app.worker.WorkerSettings

# Vite dev server on :5173 (proxies /api to :8000)
dev-frontend:
    cd frontend && pnpm dev

# Run all tests
test: test-backend test-frontend

# Backend tests (pytest). DB tests need JUSTFORMS_TEST_DATABASE_URL (a disposable database).
test-backend:
    cd backend && uv run pytest

# Frontend tests (vitest), including the shared logic vectors
test-frontend:
    cd frontend && pnpm test

# ruff + oxlint + type checks
lint: lint-backend lint-frontend

lint-backend:
    cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests

lint-frontend:
    cd frontend && pnpm lint && pnpm typecheck

# Mobile layout audit against a running stack (Playwright, real phone emulation, light + dark).
# Signs in with a local code read from Mailpit. Extra args go to the script, e.g.
#   just mobile-audit http://localhost:5173 admin@example.org --path /v/<token> --devices "Pixel 7"
# First run: cd frontend && pnpm exec playwright install chromium
mobile-audit base email *args:
    cd frontend && node scripts/mobile-audit.mjs --base {{ base }} --email {{ email }} {{ args }}

# Format backend code (ruff)
format:
    cd backend && uv run ruff format . && uv run ruff check --fix .

# Production build of the SPA
build-frontend:
    cd frontend && pnpm build

# Build and start the full stack
compose-up:
    {{ compose }} up -d --build

# Full stack plus the dev Keycloak (OIDC) and mailpit
compose-keycloak:
    cd deploy/compose && docker compose -f docker-compose.yml -f docker-compose.keycloak.yml --profile dev up -d --build

# Full stack behind a named Cloudflare Tunnel (CLOUDFLARE_TUNNEL_TOKEN in deploy/compose/.env)
tunnel:
    {{ compose }} --profile tunnel up -d --build

# Full stack behind a temporary trycloudflare.com URL (demos only), then print the URL
quick-tunnel:
    #!/usr/bin/env bash
    set -euo pipefail
    {{ compose }} --profile quick-tunnel up -d --build
    for _ in $(seq 30); do
        url=$({{ compose }} logs cloudflared-quick 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -n 1 || true)
        if [ -n "$url" ]; then
            echo "Tunnel URL: $url"
            echo "Set JUSTFORMS_PUBLIC_URL=$url and JUSTFORMS_COOKIE_SECURE=true in deploy/compose/.env, then:"
            echo "  {{ compose }} up -d backend worker"
            exit 0
        fi
        sleep 2
    done
    echo "No tunnel URL yet; check: {{ compose }} logs cloudflared-quick" >&2
    exit 1

# Stop the full stack (volumes are kept)
compose-down:
    {{ compose }} down

# Validate the compose file
compose-config:
    {{ compose }} config --quiet

# Lint the Helm chart and render it with the default and every ci/ values file
helm-lint:
    helm lint deploy/helm/justforms
    helm lint deploy/helm/justforms -f deploy/helm/justforms/ci/local-values.yaml
    helm lint deploy/helm/justforms -f deploy/helm/justforms/ci/s3-values.yaml
    helm template justforms deploy/helm/justforms > /dev/null
    helm template justforms deploy/helm/justforms -f deploy/helm/justforms/ci/local-values.yaml > /dev/null
    helm template justforms deploy/helm/justforms -f deploy/helm/justforms/ci/s3-values.yaml > /dev/null
