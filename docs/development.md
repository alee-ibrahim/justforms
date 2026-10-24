# Development

How to run JustForms from source, check your changes and find your way around the code.
The full conventions are in [CLAUDE.md](../CLAUDE.md); the architecture is in the
[design document](DESIGN.md).

- [Stack](#stack)
- [Local setup](#local-setup)
- [Tests and checks](#tests-and-checks)
- [Mobile layout audit](#mobile-layout-audit)
- [Project structure](#project-structure)
- [Conventions](#conventions)
- [Contributing](#contributing)

## Stack

| | |
|---|---|
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 (async, asyncpg), Alembic; arq worker on Redis |
| Frontend | Vite, React, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query and Router |
| Data | PostgreSQL, Redis, files on a local volume or S3 |
| PDFs | fpdf2 with HarfBuzz shaping, signed with pyHanko |

## Local setup

Requirements: [uv](https://docs.astral.sh/uv/), Node.js 24+ with corepack (it provides the
pnpm version pinned in `frontend/package.json`), [just](https://just.systems) and Docker.

```sh
corepack enable                        # once
just infra                             # PostgreSQL and Redis in Docker
cp backend/.env.example backend/.env   # then adjust
just install                           # uv sync + pnpm install
just migrate
just create-admin you@example.org
just dev                               # API, worker and Vite together
```

The SPA runs on http://localhost:5173 and proxies `/api` to the API on http://localhost:8000
(OpenAPI docs at `/api/docs`). `just dev-backend`, `just dev-worker` and `just dev-frontend`
run them one at a time; `just` alone lists every recipe. `just infra-down` stops PostgreSQL
and Redis.

Without SMTP configured, sign-in codes are only useful with a mail catcher: run Mailpit from
the Compose `dev` profile (see [Deployment](deployment.md#docker-compose)) and point
`JUSTFORMS_SMTP_HOST` at it.

## Tests and checks

| Command | What it does |
|---|---|
| `just lint` | ruff (check and format) and mypy for the backend; oxlint, the logical-classes check and `tsc` for the frontend |
| `just test` | pytest and vitest, including the shared logic, validation and webhook-signature vectors in `spec/` |
| `just format` | Format and auto-fix the backend with ruff |
| `just spec` | Regenerate `spec/form-schema.v1.json` and the frontend types after a schema change |
| `just check-spec` | Fail if those generated files are stale |
| `just build-frontend` | Production build of the SPA |
| `pnpm check:bundle` | In `frontend/`, after a build: keeps the public form within its size budget |
| `just helm-lint` | Lint the Helm chart against the example values in `deploy/helm/justforms/ci/` |

Backend tests that need PostgreSQL run when `JUSTFORMS_TEST_DATABASE_URL` points at a disposable
database (it is wiped).

## Mobile layout audit

`just mobile-audit` drives a running stack (studio, public form, verify and approver pages) with
Playwright's phone emulation in light and dark, screenshots every state and flags sideways
scrolling, elements off screen, clipped text, cramped forms and small tap targets. It signs in
with a sign-in code read from Mailpit.

```sh
cd frontend && pnpm exec playwright install chromium   # first run only
just mobile-audit http://localhost:5173 admin@example.org --path /v/<token> --devices "Pixel 7"
```

It writes `report.json` and `report.md`, and exits with 1 when it finds an error. All options
are documented at the top of `frontend/scripts/mobile-audit.mjs`.

## Project structure

```
backend/          FastAPI app (app/): form schema, logic engine, auth, API, PDFs, importers, worker; Alembic; tests
frontend/         Vite + React SPA: studio, public form and document pages; TS logic engine
spec/             JSON Schema of the form format, shared logic and validation vectors, examples
deploy/compose/   Docker Compose stack, dev Keycloak overlay, .env.example, fonts/ (git-ignored)
deploy/helm/      Helm chart
docs/             these docs, DESIGN.md, UX notes, webhooks, brand assets, README images
justfile          task recipes
```

## Conventions

Read [CLAUDE.md](../CLAUDE.md) before changing code. The short version:

- **The schema is the source of truth.** Change `backend/app/schemas/form.py` first, then run
  `just spec` to regenerate `spec/form-schema.v1.json` and the frontend types.
- The logic engine and answer validation have Python and TypeScript twins. Change both and add
  a case to the shared vectors in `spec/`.
- UI components come from the official shadcn/ui CLI only; theme through CSS variables.
- System text is English; Dhivehi appears only in form content. Use logical CSS classes
  (`ms-*`, `ps-*`, `text-start`) so right-to-left forms work.
- Python with uv and ruff, JavaScript with pnpm (via corepack) and oxlint.
- Never name a specific deploying organisation anywhere in the project.

UI work follows the [design system](ux/DESIGN-SYSTEM.md) and the
[review checklist](ux/REVIEW-CHECKLIST.md). The logo and its usage rules are in
[docs/brand](brand/README.md).

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full guide. In short, run `just lint` and `just test` before opening a pull
request, and `pnpm check:bundle` in `frontend/` after a build when you touch the public form.
Contributions are accepted under the [AGPL-3.0](../LICENSE).
