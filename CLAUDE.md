# JustForms — project conventions

## HARD RULE: official shadcn/ui only

**Never hand-roll shadcn components.** Every UI component in `frontend/src/components/ui/`
must come from the official shadcn CLI:

```sh
cd frontend && pnpm dlx shadcn@latest add <component>
```

- Do not write, copy-paste or "recreate" a component by hand, and do not edit generated
  files in `components/ui/` to change behaviour or look — theme via CSS variables in
  `src/index.css` instead.
- If something isn't in shadcn, **compose it from official components** in
  `src/components/<feature>/`. Don't build new primitives.
- `components/ui/` is excluded from oxlint because it is generated code.

## HARD RULE: no deploying-organisation references

**Never reference any specific deploying organisation or its infrastructure.** JustForms is a
generic OSS project. No file (docs, README, CLAUDE.md, Helm values/comments, compose comments,
code, comments, tests, UI strings, fixtures) and no commit message may name an organisation
that deploys it, its domains, clusters, internal tools or migration plans. Write generic
deployment notes instead ("a self-hoster", "an organisation", "a GitOps controller with an
external secrets operator").

## Project layout

- `backend/` — FastAPI + Pydantic v2 + SQLAlchemy 2 (async/asyncpg) + Alembic, arq worker.
- `frontend/` — Vite + React + TypeScript SPA, Tailwind v4, shadcn/ui, TanStack Query + Router.
- `deploy/compose/` — docker compose stack (postgres, redis, backend, worker, frontend). No object store is
  bundled: files go to the `storage-data` volume, or to external S3 when configured. `fonts/` holds
  operator-supplied fonts and is git-ignored.
- `deploy/helm/justforms/` — Helm chart (migration hook, hardening, optional HPA/PDB/HTTPRoute). Every value and Secret key is in its README. Local storage = PVC; S3 = `storage.s3.*` + `existingSecret`.
- `docs/` — design docs (`docs/DESIGN.md`).
- `spec/` — generated `form-schema.v1.json`, shared logic vectors (`logic/vectors`), cycle fixtures
  (`logic/cycles`) and examples. Run by both pytest and vitest.

## Tooling

- Python: **uv** only (`uv add`, `uv run`, `uv sync`). Lint/format with **ruff**, test with **pytest**.
- JavaScript: **pnpm** only (not npm, not yarn), pinned via `packageManager` in `frontend/package.json`
  and provisioned with corepack. Commit `pnpm-lock.yaml`; CI/Docker use `pnpm install --frozen-lockfile`.
  Lint with oxlint (`pnpm lint`).
- Common tasks live in the root `justfile` (`just dev`, `just test`, `just lint`, `just infra`, ...). No Makefile.

## Languages: English UI, Dhivehi form content

- **All system/interface text (studio, public form chrome, approver/verify pages, emails, PDF
  labels) is English only. Dhivehi appears only in form content and answers; dv forms render
  content RTL with Thaana fonts/keyboard.** No i18n layer: write English strings inline. No
  i18next, no locale bundles, no UI language/direction toggle; `<html>` stays `lang="en" dir="ltr"`.
  Inside a dv form sheet render English strings through `<En>` / `Msg` (`renderer/msg.tsx`)
  (see docs/DESIGN.md §16 for the direction rules).
- **Form content respects the form's language.** `settings.language` is `en` (default) or `dv`
  (Dhivehi, Thaana, RTL); direction derives from it. Wherever form text is edited or shown
  (title, labels, options, preview, renderer) spread `contentProps(formLanguage(form))` from
  `@/schema` to set `lang`/`dir`, so Thaana typing and rendering work. `:lang(dv)` uses the Thaana
  font stack.
- Use **logical** Tailwind classes in renderer/form components that display form content (the lint
  enforces them everywhere): `ms-*`/`me-*`, `ps-*`/`pe-*`, `start-*`/`end-*`, `text-start`/`text-end`,
  `border-s`/`border-e`, `rounded-s`/`rounded-e`. Never `ml/mr/pl/pr/left/right`.
- Wrap LTR-only fragments inside form content (versions, codes, emails) in `<bdi dir="ltr">`, and
  user-entered titles shown in English UI in `<bdi dir="auto">`.
- Dhivehi text in fixtures/examples is a draft until checked for spelling/register.

## Schema is the source of truth

- The form definition lives in `backend/app/schemas/form.py` (Form → pages → fields).
  Database tables, API payloads, the renderer, validation and importers derive from it.
  Change the schema first, then everything else. After changing it run `just spec` (exports
  `spec/form-schema.v1.json`, regenerates `frontend/src/schema/generated/`); CI fails on stale files.
- The rule engine has twins (`backend/app/logic`, `frontend/src/logic`). Change both together and add a
  vector to `spec/logic/vectors` for every behaviour change or fix.
- Answer validation also has twins (`backend/app/validation/answers.py`, `frontend/src/renderer/validation.ts`)
  returning the same problem codes; change both and add a case to `spec/validation/answers.json`
  (run by pytest and vitest).
- Form text is plain strings in the form's language (`settings.language`), never `{en, dv}` objects;
  field/page keys are snake_case and unique per form.
- Backend config comes from env vars with the `JUSTFORMS_` prefix (`app/config.py`). No secrets in the repo.

## File storage

- All file I/O goes through `app.storage.get_storage()` — never open paths or create boto3 clients
  directly. Backends: `local` (default, `JUSTFORMS_STORAGE_LOCAL_PATH`) and `s3` (external
  S3-compatible service via `JUSTFORMS_S3_*`). Do not add MinIO or any bundled object store.
- `local` has no presigned URLs (`presign_*` return `None`): the API accepts uploads and streams
  downloads itself. `s3` uses presigned POST/GET. Keys are relative paths checked by `validate_key`.

## Fonts

- Thaana stack: `Faruma, "MV Faseyha", "Noto Sans Thaana", sans-serif`. Only Noto Sans Thaana (OFL)
  is bundled. **Never commit Faruma/MV font files** — operators drop them into the fonts directory
  served at `/fonts/` (see README).
- The PDF renderer embeds TTFs from `backend/app/pdf/fonts/` (Atkinson Hyperlegible Next and Noto
  Sans Thaana, both SIL OFL, licence files alongside). Only add fonts there under a licence that
  allows embedding.
- Operators can supply a Thaana TTF/OTF for server rendering (PDFs and link-preview images) with
  `JUSTFORMS_THAANA_FONT_FILE`; it goes through `app.pdf.faces.thaana_face(settings, purpose)`,
  which falls back to the bundled Noto Sans Thaana. Tests use renamed copies of the bundled face.

## Signatures and signed PDFs

- Submissions carry a content hash (RFC 8785 JCS + SHA-256) and a hash-chained event log
  (`app/integrity.py`). Every change to a submission goes through `append_event`; never edit
  `submission_events` or the hashed columns directly.
- PDFs are rendered with fpdf2 + HarfBuzz and signed with pyHanko using the install's key
  (`app/signing/keys.py`, private key encrypted with `JUSTFORMS_SECRET_KEY`).

## Notifications, webhooks and abuse controls

- The API never sends email or webhooks inline. After committing a submission change it enqueues
  `dispatch_event` (`app/notifications/events.py`), which writes delivery rows for the worker.
  New events: add them to `app/notifications/webhooks.EVENTS`, the studio labels and `docs/webhooks.md`.
- Webhook signing is shared with the reference verifiers in `docs/webhooks/` through
  `spec/webhooks/signature-v1.json` (pytest and vitest); change all of them together.
- Outbound URLs go through `app/notifications/ssrf.py` (resolve, check, pin the address).
- Public endpoints get a rate limit from `app/ratelimit.py`; the access/CAPTCHA strings (English)
  live in `frontend/src/public/access-lib.ts`, loaded lazily to keep the public bundle within budget.

## License

AGPL-3.0-only. All contributions are under the same license; don't add dependencies with
incompatible licenses.
