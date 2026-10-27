# JustForms — Design Document

Status: Draft v1 (2026-10-23)
License: AGPL-3.0-only
Repository: https://github.com/alee-ibrahim/justforms

---

## 1. Overview

JustForms is an open-source, self-hostable forms builder in the same space as Jotform and Tally. People build forms in a drag-and-drop builder or by chatting with an AI assistant. Respondents fill them in on a fast public page, and form owners review, triage and export submissions in a web dashboard.

Some requirements are first-class from day one: Dhivehi (Thaana, right-to-left) form content, drawn signatures with an audit trail, and OIDC single sign-on (Entra ID, Keycloak and other providers). JustForms is a general-purpose OSS product: there is no organisation-specific code in the core, and anything specific to one installation lives in configuration and deployment values.

### 1.1 Goals (v1)

1. **One source of truth.** A versioned JSON form schema. The builder edits it, the renderer displays it, the backend validates submissions against it, and AI and importers produce it.
2. **Identical logic everywhere.** Show/hide/require/skip rules are evaluated by one small rule engine. It has a Python implementation and a TypeScript implementation, and both must pass a shared conformance suite.
3. **Owners can work with submissions easily.** Table view with filters and search, a detail view, a status workflow (New → In review → Approved/Rejected) with comments, and `.xlsx` export.
4. **Signatures you can defend.** Raw strokes, rendered images, timestamp, IP, user agent and a SHA-256 content hash, plus a tamper-evident signed PDF.
5. **Dhivehi and RTL forms as a first-class feature.** Each form is written in English or Dhivehi (`settings.language`). Dhivehi forms render right-to-left with Thaana fonts and a phonetic Thaana keyboard. The studio UI itself is English only (§16).
6. **AI that edits the schema, never code.** It works through tool calls that produce validated schema patches, previewed in the UI with undo. AI is optional and hidden when no provider is configured.
7. **Easy to self-host.** `docker compose up` for small installs and a Helm chart for Kubernetes.
8. **Import from Jotform.** Form structure comes from the pasted HTML source, and submissions from an Excel/CSV export with a column-mapping step. An optional API-key import adds conditions and bulk import.
9. **Official shadcn/ui only.** Components are added via the shadcn CLI, and nothing shadcn-like is hand-rolled (§18.1).

### 1.2 Non-goals (v1)

- Payments, quizzes/scoring, and calculated fields.
- Approval routing beyond a fixed sequence: v1 has up to three ordered approval steps per form (§15.3), but no parallel or conditional steps, reminders or deadlines.
- Live sync to Excel/Google Sheets. Webhooks and `.xlsx` export cover v1.
- A visual theme designer. v1 offers a small set of tokens: accent colour, logo, light/dark.
- Respondent accounts and "my submissions" portals.
- Save-and-resume of partially filled forms.
- Offline and native mobile apps.
- Running user-supplied code or scripts in forms, under any circumstances.

---

## 2. Architecture

```mermaid
flowchart LR
  subgraph Browser
    Studio["Studio SPA<br/>(builder + dashboard)<br/>React/TS, shadcn/ui"]
    Public["Public form bundle<br/>(renderer only, small)"]
  end

  subgraph Edge
    Web["web (nginx)<br/>static assets + /api proxy"]
  end

  subgraph Backend
    API["api (FastAPI)<br/>REST /api/v1"]
    Worker["worker (arq)<br/>exports, PDFs, webhooks,<br/>emails, AI import jobs"]
  end

  PG[("PostgreSQL<br/>forms, versions,<br/>submissions JSONB")]
  Redis[("Redis<br/>sessions, rate limits,<br/>arq queue")]
  Files[("File storage<br/>local volume (default)<br/>or external S3<br/>uploads, signatures,<br/>PDFs, exports")]
  IdP["OIDC IdP<br/>(Entra ID, Keycloak, ...)"]
  SMTP["SMTP relay"]
  LLM["LLM provider<br/>(Gemini, Claude,<br/>OpenAI-compatible, local)"]
  Hooks["Webhook receivers"]

  Studio --> Web
  Public --> Web
  Web --> API
  Studio -. presigned GET (s3 only) .-> Files
  Public -. presigned POST (s3 only) .-> Files
  API --> PG
  API --> Redis
  API --> Files
  API --> IdP
  API --> LLM
  API -- enqueue --> Redis
  Worker --> Redis
  Worker --> PG
  Worker --> Files
  Worker --> SMTP
  Worker --> Hooks
  Worker --> LLM
```

Processes:

| Process | Tech | Scales | Notes |
|---|---|---|---|
| `api` | FastAPI + Uvicorn, Pydantic v2, SQLAlchemy 2 (async, asyncpg) | Horizontally, stateless (with `local` storage: needs a ReadWriteMany volume to span nodes) | Sessions are kept in Redis |
| `worker` | arq | Horizontally | All slow or external work runs here: exports, PDFs, webhooks, email, AV scan (later), AI document import |
| `web` | nginx | Horizontally | Serves `studio` and `form` static builds and proxies `/api` |
| `migrate` | Alembic | One-shot | Compose `depends_on` / Helm pre-upgrade Job |

File storage sits behind a small backend interface (`app/storage`). The default `local` backend keeps files on a mounted volume (Compose named volume, Helm PVC) shared by `api` and `worker`, so a self-hosted install needs no object store. The optional `s3` backend points at any external S3-compatible service (AWS S3, Cloudflare R2, Ceph, Garage, ...). No object store is bundled. With `local`, uploads and downloads stream through the API; with `s3`, browsers use presigned URLs and bytes bypass the API (§10).

Request-path rule: the API never calls SMTP, webhooks, or the PDF renderer inline. It writes rows and enqueues jobs. The one exception is the AI chat endpoint, which streams from the LLM provider over SSE.

---

## 3. Repository layout

```
justforms/
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                    # migrations
│   └── justforms/
│       ├── main.py                 # FastAPI app factory
│       ├── config.py               # pydantic-settings, all env vars prefixed JUSTFORMS_
│       ├── db/                     # engine, session, base, models/
│       ├── schema/                 # CANONICAL form-schema Pydantic models + validators
│       ├── logic/                  # Python rule engine
│       ├── validation/             # submission validation against a schema version
│       ├── api/v1/                 # routers: auth, orgs, forms, submissions, uploads, ai, webhooks...
│       ├── auth/                   # OIDC, sessions, respondent OTP, CSRF
│       ├── permissions/            # role resolution + FastAPI dependencies
│       ├── storage/                # Storage interface: local volume (default) or S3; key layout
│       ├── signatures/             # stroke rendering, hashing, PDF signing
│       ├── pdf/                    # fpdf2 + HarfBuzz rendering, pyHanko signing, checks
│       ├── exports/                # openpyxl writer
│       ├── notifications/          # email templates + webhook delivery
│       ├── ai/                     # provider adapters, tools, orchestration
│       ├── importers/jotform/      # HTML-source + API form import, Excel/CSV submission import
│       ├── worker/                 # arq WorkerSettings + job functions
│       └── cli.py                  # `justforms` admin CLI (create-admin, rotate-keys, ...)
├── frontend/                       # pnpm workspaces
│   ├── package.json
│   ├── apps/
│   │   ├── studio/                 # builder + dashboard SPA (TanStack Router/Query, dnd-kit)
│   │   └── form/                   # public form page; renderer only, no router/query heavy deps
│   └── packages/
│       ├── ui/                     # official shadcn/ui components (generated via shadcn CLI) + Tailwind config
│       ├── schema/                 # TS types + zod, GENERATED from spec/form-schema.v1.json
│       ├── logic/                  # TS rule engine
│       ├── renderer/               # form renderer (react-hook-form + zod), used by studio preview and form app
│       └── thaana/                 # phonetic keyboard mapping + input hook, fonts
├── spec/
│   ├── form-schema.v1.json         # JSON Schema exported from backend Pydantic models (CI checks it is current)
│   └── logic/vectors/*.json        # shared logic conformance vectors (run by pytest AND vitest)
├── deploy/
│   ├── compose/                    # docker-compose.yml, .env.example, fonts/ (operator fonts, git-ignored)
│   └── helm/justforms/               # Helm chart
├── docs/
│   ├── DESIGN.md                   # this file
│   ├── self-hosting.md
│   └── schema.md                   # human-readable schema reference
├── justfile                        # task runner (just dev, just test, just lint, ...)
├── LICENSE                         # AGPL-3.0
└── .github/workflows/              # lint, test, conformance, image build
```

Source-of-truth chain: the Pydantic models in `backend/justforms/schema/` are canonical. `just spec` exports `spec/form-schema.v1.json`. `frontend/packages/schema` is then generated from that file (`json-schema-to-typescript` for types, `json-schema-to-zod` for structural validation). CI fails if any generated artifact is stale.

---

## 4. Form schema specification

### 4.1 Concepts

- **Form.** A long-lived entity with a stable `id`, an owner org, settings, and a sequence of versions.
- **Draft.** One mutable working copy per form. The builder and the AI both edit the draft.
- **Version.** An immutable snapshot that is created when the draft is published. Versions are numbered `1, 2, 3, ...`. Each submission stores the exact `form_version_id` it was filled against and is always rendered, validated and exported using that version.
- **`schemaVersion`.** The version of the spec format itself (`"1"`). It is separate from the form's version number. When the format changes, ordered migration functions upgrade stored documents on read.

### 4.2 Element tree

```
Form
 ├─ settings
 ├─ pages[]                      (≥1; a single-page form is one page)
 │   └─ elements[]
 │        ├─ field               (input that produces a value)
 │        ├─ content             (heading / paragraph / divider / image — no value)
 │        ├─ section             (visual group, has elements[], no value of its own)
 │        └─ repeater            (has elements[]; value = array of row objects)
 └─ (nothing else at top level)
```

Rules enforced by the Pydantic validators:

- Every element has an `id` that matches `^[a-z][a-z0-9_]{0,62}$` and is unique within the form. The id is the submission data key, the webhook payload key and the logic reference. It can be renamed while the form is unpublished and is **frozen after its first publish**. The builder generates it from a Latin label (`full_name`, `full_name_2`) or, for Thaana labels, from the field type (`short_text_1`).
- Repeaters cannot nest in v1. Sections can sit inside repeaters. Sections can nest at most 2 levels deep.
- `signature` fields cannot sit inside repeaters in v1.
- A form has exactly one language: `settings.language` is `"en"` (default) or `"dv"`. All user-facing text (titles, labels, descriptions, placeholders, option labels, messages) is a **plain string** in that language; there are no per-language translation objects. Text direction derives from the language (`dv` → `rtl`, `en` → `ltr`). Drafts may hold blank text; publishing requires a non-blank form title, field and repeater labels, option labels and heading/paragraph text (issue code `blank_text`).

### 4.3 Field types (v1)

| `type` | Value shape | Type-specific props |
|---|---|---|
| `short_text` | string | `inputScript: "auto" \| "latin" \| "thaana"`, `maxLength`, `pattern` |
| `long_text` | string | `inputScript`, `maxLength`, `rows` |
| `email` | string | — |
| `phone` | string (E.164) | `defaultCountry` (e.g. `"MV"`) |
| `number` | number | `min`, `max`, `step`, `integer` |
| `date` | string `YYYY-MM-DD` | `minDate`, `maxDate` (absolute or `"today"`, `"today+30"`) |
| `time` | string `HH:MM` | — |
| `single_choice` | string (option value) | `options[]`, `display: "radio" \| "dropdown"`, `allowOther` |
| `multi_choice` | string[] | `options[]`, `minSelected`, `maxSelected` |
| `yes_no` | boolean | — |
| `rating` | integer | `max` (3–10) |
| `file` | `FileRef[]` | `accept[]` (MIME or ext), `maxFiles`, `maxSizeMb` |
| `signature` | `SignatureRef` | `attestation: string` (the "I confirm..." text shown above the pad) |
| `hidden` | string | `prefillParam` (URL query param name) |

Common field props: `label`, `description`, `placeholder` (plain strings in the form's language), `required`, `requiredIf`, `visibleIf`, `prefillParam`, `sensitive` (marked with a lock in the studio, logged when a submission that has it is opened, left out of search, emails and webhooks unless explicitly opted in, and only counted by the AI unless the form allows AI to read answers), and `width: "full" | "half"`.

### 4.4 Concrete example

```json
{
  "schemaVersion": "1",
  "settings": {
    "language": "dv",
    "title": "ޒުވާނުންގެ ޕްރޮގްރާމަށް ހުށަހަޅާ ފޯމު",
    "submitLabel": "ހުށަހަޅާ",
    "successMessage": "ޝުކުރިއްޔާ!",
    "theme": { "accent": "#0f766e", "logoFileId": null }
  },
  "pages": [
    {
      "id": "p_applicant",
      "title": "އަމިއްލަ މައުލޫމާތު",
      "elements": [
        {
          "kind": "field", "id": "full_name", "type": "short_text",
          "label": "ފުރިހަމަ ނަން",
          "required": true, "inputScript": "auto", "maxLength": 120
        },
        {
          "kind": "field", "id": "national_id", "type": "short_text",
          "label": "އައިޑީ ކާޑު ނަންބަރު",
          "required": true, "pattern": "^A[0-9]{6}$",
          "patternMessage": "ފޯމެޓް: A123456",
          "inputScript": "latin", "sensitive": true
        },
        {
          "kind": "field", "id": "age", "type": "number",
          "label": "އުމުރު",
          "required": true, "integer": true, "min": 15, "max": 35
        },
        {
          "kind": "field", "id": "has_dependents", "type": "yes_no",
          "label": "ބަލަހައްޓަންޖެހޭ މީހުން ތިބިތޯ؟",
          "required": true
        },
        {
          "kind": "repeater", "id": "dependents",
          "label": "ބަލަހައްޓަންޖެހޭ މީހުން",
          "minRows": 1, "maxRows": 10,
          "addLabel": "އިތުރުކުރޭ",
          "visibleIf": { "field": "has_dependents", "op": "eq", "value": true },
          "elements": [
            { "kind": "field", "id": "dep_name", "type": "short_text",
              "label": "ނަން", "required": true },
            { "kind": "field", "id": "dep_relation", "type": "single_choice",
              "label": "ގުޅުން", "required": true,
              "display": "dropdown",
              "options": [
                { "value": "child",  "label": "ދަރިފުޅު" },
                { "value": "parent", "label": "މައިންބަފައިން" },
                { "value": "other",  "label": "އެހެނިހެން" }
              ] },
            { "kind": "field", "id": "dep_relation_other", "type": "short_text",
              "label": "ބަޔާންކުރައްވާ",
              "visibleIf": { "field": "dep_relation", "op": "eq", "value": "other" },
              "required": true }
          ]
        }
      ],
      "next": [
        { "if": { "field": "age", "op": "lt", "value": 18 }, "goto": "p_guardian" }
      ]
    },
    {
      "id": "p_guardian",
      "title": "ބެލެނިވެރިޔާ",
      "visibleIf": { "field": "age", "op": "lt", "value": 18 },
      "elements": [
        { "kind": "field", "id": "guardian_name", "type": "short_text",
          "label": "ބެލެނިވެރިޔާގެ ނަން", "required": true },
        { "kind": "field", "id": "guardian_phone", "type": "phone",
          "label": "ފޯނު ނަންބަރު", "defaultCountry": "MV",
          "required": true }
      ]
    },
    {
      "id": "p_docs",
      "title": "ލިޔެކިޔުން",
      "elements": [
        {
          "kind": "section", "id": "sec_docs",
          "title": "ލިޔެކިޔުން",
          "elements": [
            { "kind": "field", "id": "id_copy", "type": "file",
              "label": "އައިޑީ ކާޑުގެ ކޮޕީ",
              "required": true, "accept": ["application/pdf", "image/jpeg", "image/png"],
              "maxFiles": 2, "maxSizeMb": 10 },
            { "kind": "field", "id": "interests", "type": "multi_choice",
              "label": "ޝައުގުވެރިވާ ދާއިރާތައް",
              "minSelected": 1, "maxSelected": 3,
              "options": [
                { "value": "law",    "label": "ގާނޫނު" },
                { "value": "media",  "label": "މީޑިއާ" },
                { "value": "it",     "label": "އައިޓީ" }
              ] }
          ]
        },
        { "kind": "content", "id": "decl_text", "contentType": "paragraph",
          "text": "މަތީގައިވާ މައުލޫމާތަކީ ތެދު މައުލޫމާތުކަން ކަށަވަރުކުރަމެވެ." },
        {
          "kind": "field", "id": "applicant_signature", "type": "signature",
          "label": "ސޮއި", "required": true,
          "attestation": "އަޅުގަނޑު މި ފޯމުގައި ސޮއިކުރަމެވެ."
        },
        {
          "kind": "field", "id": "guardian_signature", "type": "signature",
          "label": "ބެލެނިވެރިޔާގެ ސޮއި",
          "requiredIf": { "field": "age", "op": "lt", "value": 18 },
          "visibleIf": { "field": "age", "op": "lt", "value": 18 }
        }
      ]
    }
  ]
}
```

### 4.5 Submission data shape

Submission data is a flat object keyed by field id. Repeaters are arrays of row objects. Sections, pages and content elements contribute no keys.

```json
{
  "full_name": "Aishath Ali",
  "national_id": "A123456",
  "age": 17,
  "has_dependents": true,
  "dependents": [ { "dep_name": "Ahmed", "dep_relation": "child" } ],
  "guardian_name": "Mariyam Hassan",
  "guardian_phone": "+9607000000",
  "id_copy": [ { "fileId": "01JB8Z...", "name": "id.pdf", "size": 183422, "mime": "application/pdf" } ],
  "interests": ["law", "it"],
  "applicant_signature": { "signatureId": "01JB90..." },
  "guardian_signature": { "signatureId": "01JB91..." }
}
```

The server removes keys for elements that are effectively hidden (§5.4), so stored data only ever contains answers the respondent could actually see.

---

## 5. Logic engine

### 5.1 Grammar

```
Condition :=
    { "all": [Condition, ...] }          # AND; empty list = true
  | { "any": [Condition, ...] }          # OR;  empty list = false
  | { "not": Condition }
  | { "field": FieldId, "op": Op, "value"?: JsonValue }

Op := eq | neq | gt | gte | lt | lte | in | not_in
    | contains | not_contains | empty | not_empty
    | count_eq | count_gte | count_lte
```

Where conditions attach:

| Location | Property | Effect |
|---|---|---|
| any element (field, section, repeater, content) | `visibleIf` | Element (and all descendants) hidden when false |
| field | `requiredIf` | Field required when true (OR'ed with static `required`) |
| page | `visibleIf` | Page skipped when false |
| page | `next: [{ "if": Condition, "goto": PageId \| "submit" }]` | First matching rule decides the next page; otherwise the next visible page in order |

The engine deliberately has **no regex operator, no arithmetic and no string functions**. Regex dialects differ between Python and JS and bring ReDoS risk. Arithmetic belongs to "calculated fields", which is backlog.

### 5.2 Operator semantics

Both implementations must match exactly:

- **Missing value.** A value is missing when the field is unanswered, hidden, `null`, `""`, `[]`, or a repeater with 0 rows. With a missing value, `empty` is true, `neq` and `not_in` and `not_contains` are true, and every other op is false.
- **No implicit coercion.** `"5" eq 5` is false. A `number` field holds a JSON number. A `yes_no` field holds a boolean.
- **Ordering ops** (`gt`, `gte`, `lt`, `lte`) work on numbers, on `date` (`YYYY-MM-DD`, compared lexicographically) and on `time` (`HH:MM`). If the types are incompatible the result is false, never an error.
- `in` / `not_in`: `value` is an array, and the test is whether the field's scalar value is a member.
- `contains` / `not_contains`: on `multi_choice` this is array membership. On text fields it is a case-sensitive substring test after Unicode NFC normalisation.
- `count_*`: on `multi_choice`, `file` and `repeater`, compares the length of the array.
- Strings are NFC-normalised before any comparison.

### 5.3 References and scope

- `field` must refer to a **value-producing field**. Referring to a section, page or content element is a validation error.
- Inside a repeater, a reference to a sibling child field resolves to **the same row**. A repeater child can also reference fields outside the repeater.
- Outside a repeater, conditions cannot reference repeater children. They can reference the repeater itself, but only with `empty`, `not_empty` or `count_*`.
- **Forward references are allowed but cycles are not.** At publish time the backend builds a dependency graph (element → fields its conditions read). Publishing is rejected if that graph has a cycle, such as A visible if B not empty and B visible if A not empty. `goto` may only jump forward, to a later page, so navigation always terminates.

### 5.4 Evaluation algorithm

`evaluate(schema, answers) -> { visible: Set<ElementId>, required: Set<FieldId>, path: PageId[] }`

1. Topologically sort conditional elements by their dependency graph.
2. Walk the sorted elements. For each one, evaluate `visibleIf` against an **effective answers** view, in which any field already determined to be hidden reads as missing. An element is effectively visible only if its own condition holds **and** its parent section, repeater and page are visible.
3. Evaluate `requiredIf` for visible fields only.
4. Compute the page path. Start at page 0. At each page, apply the first matching `next` rule, or otherwise move to the next page whose `visibleIf` holds. Pages that are jumped over are treated as hidden (step 2 is re-run with their fields treated as missing), and the path continues until `submit` or the end of the form.
5. Repeater children are evaluated once per row, with that row as the local scope.

Per-answer checks (type, length, pattern, ranges, options, dates, file references) are twins too: `backend/app/validation/answers.py` and `frontend/src/renderer/validation.ts` return the same problem codes with params (`{"field", "code", "params"?, "repeater"?, "row"?}` in a 422), the public renderer turns codes into English messages (system text, §16), and both run the shared cases in `spec/validation/answers.json`. Repeaters are padded to `minRows` before evaluation, as the renderer shows them. Relative date limits (`today+N`) allow one day of slack on the server for respondents in other time zones; staff-written patterns run with a timeout.

The client calls `evaluate` on every change (debounced through react-hook-form `watch`) to drive what is shown and the wizard navigation. The server calls it once per submission. It then **strips hidden keys** and validates visible fields only, using visible-only required rules. A client that tampers with visibility cannot get hidden data stored, and cannot get past a required field.

### 5.5 Shared conformance suite

`spec/logic/vectors/*.json`. Each file looks like this:

```json
{
  "name": "under-18 routes to guardian page and requires guardian signature",
  "schema": { "...": "minimal form schema" },
  "answers": { "age": 17, "has_dependents": false },
  "expect": {
    "visible": ["full_name", "age", "has_dependents", "guardian_name", "guardian_signature"],
    "hidden": ["dependents"],
    "required": ["guardian_signature"],
    "path": ["p_applicant", "p_guardian", "p_docs"],
    "strippedAnswers": { "age": 17, "has_dependents": false }
  }
}
```

The same vectors run in `backend/tests/test_logic_vectors.py` (pytest) and `frontend/packages/logic/vectors.test.ts` (vitest). CI requires both to pass. Any bug fix in either engine has to come with a new vector. Phase 1 targets 150 or more vectors covering every operator, missing-value case, repeater scoping and navigation case.

---

## 6. Data model

All primary keys are UUIDv7, so they sort by time. All tables carry `created_at` and `updated_at` (`timestamptz`). Soft deletion uses `deleted_at` where noted.

| Table | Key columns | Notes |
|---|---|---|
| `organizations` | `id`, `name`, `slug` (unique), `settings` jsonb | Workspace/tenant. Self-hosters usually run one. |
| `users` | `id`, `email` (citext unique), `display_name`, `oidc_issuer`, `oidc_subject`, `is_superadmin`, `superadmin_source` (`local`, `oidc`, null when not a superadmin), `last_login_at`, `appearance` (`light` default, `dark`, `system`) | Staff and builders. Unique on (`oidc_issuer`, `oidc_subject`). `superadmin_source`: `local` from `create-admin`, `oidc` from superadmin group mapping, which only takes away what it granted. |
| `org_memberships` | `org_id`, `user_id`, `role` enum(`admin`,`creator`,`member`), `idp_managed` | PK (`org_id`, `user_id`). `idp_managed`: granted by OIDC sign-in (group mapping or the first-sign-in default), so group mapping may take it away; invited or admin-added memberships are kept. |
| `org_invitations` | `id`, `org_id`, `email` (citext), `role`, `status` (`pending`,`accepted`,`cancelled`), `token_hash` (unique, SHA-256), `expires_at`, `invited_by`, `form_grants` jsonb (`[{formId, role}]`), `email_status`, `email_error`, `sent_at`, `send_count`, `accepted_at`, `accepted_user_id` | One pending invitation per (`org_id`, `email`) (partial unique index). Expiry is `JUSTFORMS_INVITE_DAYS` (14) from the last send; "expired" is computed. |
| `forms` | `id`, `org_id`, `slug` (unique across the install among forms not deleted; the public address `/{slug}`), `title` (denormalised, for listing), `status` enum(`draft`,`live`,`closed`,`archived`), `access_mode` enum(`public`,`otp`,`staff`), `draft_schema` jsonb, `draft_revision` int, `current_version_id`, `settings` jsonb (close date, response limit, captcha, retention days, embed origins), `deleted_at`, `deleted_by` (the trash, §14.5) | `draft_revision` provides optimistic concurrency for the builder and AI. |
| `form_versions` | `id`, `form_id`, `version` int, `schema` jsonb, `schema_hash` (sha256), `published_by`, `published_at` | Immutable. Unique (`form_id`, `version`). |
| `form_draft_history` | `id`, `form_id`, `revision`, `patch` jsonb (RFC 6902), `inverse_patch` jsonb, `actor_type` (`user`,`ai`), `actor_id`, `ai_session_id` | Server-side undo/redo and an audit trail of edits. Pruned to the last 200 entries per form. |
| `form_slug_aliases` | `id`, `form_id`, `slug` (unique), `created_at` | Earlier addresses of a form, answered with a 301 to the current one and reserved until the form is erased (§18.3). |
| `form_permissions` | `form_id`, `user_id`, `role` enum(`owner`,`editor`,`viewer`) | PK (`form_id`, `user_id`). |
| `submissions` | `id`, `org_id`, `form_id`, `form_version_id`, `seq` int (per-form human number, e.g. #142), `status` enum(`new`,`in_review`,`approved`,`rejected`), `data` jsonb, `search` tsvector, `language` (copied from the form version), `respondent_email` nullable, `respondent_user_id` nullable, `ip` inet nullable, `user_agent`, `content_hash` bytea, `signed_pdf_key` nullable, `pdf_status`, `verify_token` (unique, nullable; §9.5.2), `approval_state` enum(`pending`,`approved`,`rejected`,`stopped`) nullable, `approval_step`, `approval_outcome_to`, `submitted_at`, `deleted_at`, `deleted_by` (the trash, §14.5; outside the content hash) | Indexes: (`form_id`, `submitted_at` desc), (`form_id`, `status`), GIN(`data` jsonb_path_ops), GIN(`search`). Unique (`form_id`, `seq`). |
| `submission_events` | `id`, `submission_id`, `type` (`created`,`status_changed`,`comment`,`pdf_generated`,`exported`,`viewed`,`deleted`,`restored`,`approval_requested`,`approval_decided`,`approval_waiting`,`approval_stopped`), `actor_id`, `payload` jsonb, `prev_hash`, `hash` | Append-only. Hash chain per submission (§9.4). |
| `approval_steps` | `id`, `submission_id`, `step` (1-based), `name`, `source` (`field`,`fixed`,`editors`), `field_id`, `approver_email`, `notify_to` (jsonb), `state` (`waiting`,`pending`,`no_approver`,`approved`,`rejected`,`stopped`), `token_hash` (unique), `token_expires_at`, `requested_at`, `decided_at`, `decided_name`, `comment` | A form's approval settings copied onto one submission (§15.3). The event log is the record; these rows are the working state. |
| `files` | `id`, `org_id`, `form_id`, `submission_id` nullable, `field_id`, `storage_key`, `original_name`, `mime`, `size`, `sha256`, `state` enum(`pending`,`attached`,`orphaned`), `scan_status` enum(`not_scanned`,`clean`,`infected`) | `pending` rows that are never attached get purged after 24 h. |
| `signatures` | `id`, `submission_id`, `field_id`, `strokes` jsonb, `svg_key`, `png_key`, `strokes_sha256`, `signed_at` (client), `received_at` (server), `ip`, `user_agent`, `attestation_text`, `language` | One row per signature field. |
| `respondent_otps` | `id`, `email`, `form_id`, `code_hash`, `expires_at`, `attempts`, `consumed_at`, `ip` | Code stored as HMAC-SHA256. |
| `notification_rules` | `id`, `form_id`, `type` (`owner_email`,`respondent_receipt`), `recipients` jsonb, `include_answers` bool, `attach_pdf` bool, `email_field`, `to_unverified` bool, `unverified_answers` bool, `subject`, `message`, `reply_to`, `enabled` | |
| `webhooks` | `id`, `form_id`, `url`, `secret_enc` bytea, `events` text[], `enabled`, `include_sensitive` bool | Secret encrypted with the app key (§14.5). |
| `webhook_deliveries` | `id`, `webhook_id`, `event_id`, `event`, `payload` jsonb, `attempt`, `status` (`pending`,`succeeded`,`failed`), `response_code`, `response_snippet` (first 1 KB), `next_attempt_at`, `duration_ms` | Kept for 30 days. |
| `exports` | `id`, `form_id`, `requested_by`, `format` (`xlsx`), `filters` jsonb, `status`, `storage_key`, `row_count`, `expires_at` | File expires after 24 h. |
| `ai_sessions` | `id`, `org_id`, `form_id`, `user_id`, `provider`, `model`, `mode` (`create`,`edit`,`import`, and `ask` for "Ask your submissions", §12.6), `status` (`idle`,`proposal`,`closed`), `base_revision`, `base_schema`, `working_schema` (the pending suggestion), `flags`, `tokens_in`, `tokens_out` | One chat per person and form; other editors can't see it. Nothing in it reaches the draft until Apply. |
| `ai_messages` | `id`, `session_id`, `role` (`user`,`assistant`,`status`), `content` jsonb (request text or the uploaded file's name and page count, reply, tool steps, outcome), `created_at` | Erased after 90 days by the nightly job (Ask chats: after the form's `retentionDays` when shorter; answers written since an erased submission arrived become `removed`). Builder chats never contain submission data or the uploaded document; `ask` chats hold the questions, answers and the counts behind them, and lists only as their definition, never the text of answers the AI read or the listed values. |
| `audit_log` | `id`, `org_id`, `actor_id`, `action`, `target_type`, `target_id`, `ip`, `meta` jsonb | Org-level admin actions: permission changes, publishes, webhook edits, exports, deletions. |

Submission `search` is built at insert time. It is a `simple`-config tsvector over the text values of non-sensitive fields, so Thaana text gets whitespace tokenisation and no stemming.

---

## 7. Permissions model

Two layers.

**Organisation roles**

- `admin`: everything in the org, including all forms (acts as owner on every form), people, branding and org settings.
- `creator` ("Form creator"): can create, import and duplicate forms and becomes `owner` of each form they create. Sees the forms they created and the ones shared with them; no access to other forms unless granted.
- `member`: only the forms shared with them, in the form role they were given. Cannot create, import or duplicate forms.

Superadmins act as admins of every organisation. An organisation always keeps at least one admin: demoting or removing the last one is refused (`409 last_admin`; the admin rows are locked while counting). Removing someone from an organisation also deletes their roles on every form of that organisation (their forms stay; admins remain owners of them; comments and versions keep their name). The upgrade to three roles made every existing `member` a `creator`, so nobody lost the ability to create forms.

**Invitations** (docs/ux/PEOPLE-SCREENS.md). Admins invite addresses (up to 20 per request) with a role; re-inviting a pending address refreshes it (new role, new email). The worker mints the link token (192 random bits, stored as SHA-256) right before sending and commits it first, as for approval links (§15.3), so a resend or a retry replaces the link. The link `/login/invite/{token}` only opens a sign-in page prefilled with the address: an invitation is accepted when that address signs in while it is pending and not expired, with an emailed code (pending invitees can request one even without an account) or with OIDC when the ID token's email matches case-insensitively and the IdP vouches for it (`email_verified: true`, or `JUSTFORMS_OIDC_TRUST_EMAIL`). Accepting creates the membership (keeping a higher role someone already has) and the form roles in `form_grants`. Admins can resend, cancel (the link stops working) or change the role of pending invitations. Limits: 50 addresses an hour per admin, 200 a day per organisation, 3 resends an hour per invitation. Audit entries: `org.invite`, `org.invite_resend`, `org.invite_role`, `org.invite_cancel`, `org.invite_accept`, `org.member_role` (before and after), `org.member_remove` (with the number of form roles removed).

**Sharing with someone new.** Owners grant form roles only to organisation members. When an owner who is also an org admin adds an address from outside, the Share page offers "Invite and share": an invitation as `member` carrying the form role (`POST /forms/{id}/permissions/invite`), listed as pending access on the form until accepted. Other owners are told to ask an admin; inviting brings someone into the whole organisation, which is an admin decision.

**Notify by email** (docs/ux/PEOPLE-SCREENS.md 6.1). `PUT /forms/{id}/permissions` takes optional `notify` (default false) and `message` (plain text, up to 500 characters; control characters dropped). With `notify` and SMTP set up, each member who gets a role, or a higher one, gets an email (`email_deliveries` kind `form_shared`, sent by the worker after the change is committed): never the owner making the change, organisation admins, removals or lower roles. The email names the sharer (Reply-To is their address), the form and the role in plain words, quotes the note (escaped) and links to the builder (editors, owners) or the submissions (viewers). The role is read when the email is sent, so access removed meanwhile sends nothing; the note is kept in the row only until the email is sent or has failed for good. Limits: 50 people an hour per sharer and 200 a day per organisation (`share_notify_user`, `share_notify_org`); over them the request is refused and nothing changes. Audit entry: `form.permissions_notify` (who was emailed, whether there was a note). The response carries `smtpEnabled` for the Share page.

**Member suggestions** (docs/ux/PEOPLE-SCREENS.md 6.2). `GET /orgs/{id}/members/search?q=&limit=8` returns up to 20 members of that organisation whose name or email contains `q` (at least 2 characters; case and common Latin accents ignored, `%`/`_` literal): exact matches first, then names or emails starting with it, then a word of the name, then anywhere. Each match has the user id, display name, email, organisation role and initials. Org admins may search; a form's owners may search with `form_id` (that form must be in the organisation), and each match then carries `formRole`, the access they already have (organisation admins: owner). Others get 403, people outside the organisation 404. Limit: 120 searches a minute per user (`member_search`). The Share page's "Add someone by email" and the Invite people dialog use it as a combobox; `GET /forms/{id}/permissions` carries `orgId` for it.

**Form roles** (granted per form via `form_permissions`; the UI calls `viewer` "Submissions viewer": can view and export submissions, can't edit the form)

| Capability | viewer | editor | owner |
|---|:-:|:-:|:-:|
| View submissions, files, signatures, PDFs | yes | yes | yes |
| Comment on submissions | yes | yes | yes |
| Export `.xlsx` | yes | yes | yes |
| Change submission status | — | yes | yes |
| Edit draft, use AI, publish | — | yes | yes |
| View sensitive answers (never masked in the studio; opening a submission with them is logged) | yes | yes | yes |
| Turn off Sensitive on a published question (an editor's publish that would is refused, 403 `sensitive_owner_only`), change the allowed websites (403 `embed_origins_owner_only`) | — | — | yes |
| Manage notifications & webhooks | — | — | yes |
| Manage form permissions, close/archive/delete form, delete submissions | — | — | yes |
| See the trash, restore or permanently delete forms and submissions (§14.5) | — | — | yes |

Whoever may delete may restore. Organisation admins and superadmins are owners of every form in
the organisation, so they also restore (or erase) forms and submissions someone else deleted;
other people see in the forms trash only the deleted forms they own.

Implementation: a single resolver, `effective_form_role(user, form) -> owner|editor|viewer|None`, gives `superadmin > org admin > form_permissions`. It is exposed as a FastAPI dependency (`require_form_role("editor")`). Every submission and file query is scoped through it, and no endpoint fetches a submission by id without the form-role check. Presigned download URLs are only issued after the check passes.

Optional OIDC group mapping (config): `JUSTFORMS_OIDC_ADMIN_GROUPS`, `JUSTFORMS_OIDC_CREATOR_GROUPS`, `JUSTFORMS_OIDC_MEMBER_GROUPS`. These set the role in the default organisation at each sign-in (admin > creator > member). People in no mapped group lose memberships the IdP granted but keep ones an admin invited them to. Without group mapping, people get `JUSTFORMS_OIDC_DEFAULT_ROLE` (`creator` by default, `member`, or `none` for invitation only) in the default organisation the first time they sign in; someone an admin removes is not added back.

Optional superadmin group mapping: `JUSTFORMS_OIDC_SUPERADMIN_GROUPS`, independent of the role mapping. At each OIDC sign-in, someone in a listed group (exact string match, so group names or IdP object IDs) becomes superadmin with `superadmin_source = oidc`; when the setting is non-empty and they are in none of the groups, a superadmin with source `oidc` loses it. Superadmins with source `local` (`create-admin`) are never changed by sign-in, and an empty setting changes nobody. Audit entries: `user.superadmin_grant` (with the matching groups), `user.superadmin_revoke`. A sign-in that grants or confirms an `oidc` superadmin also makes the person admin of the default organisation (membership created or raised, not IdP-managed), audited as `org.member_role` with `source: oidc_superadmin`. That membership is marked (`superadmin_granted`, with the role before in `superadmin_prior_role`): when the IdP takes superadmin away, sign-in puts back the group-mapped role (with group mapping) or the prior role, or removes the membership and its form roles when there was none (`source: oidc_superadmin_revoke`); an admin changing the role clears the mark. Group mapping does not lower an admin role it did not grant. Removal by group mapping also removes the person's form roles in the organisation, and any removal or demotion ends their other sessions (each user's session token hashes are kept in the Redis set `user_sessions:{user_id}`). If the ID token carries `_claim_names`/`hasgroups` instead of the groups claim (Entra ID group overage), the backend logs a warning and leaves superadmin and group-mapped roles unchanged; operators should emit only groups assigned to the application. Reading groups from Microsoft Graph is a possible later addition.

---

## 8. Authentication flows

### 8.1 Staff and builders: OIDC

The backend acts as a confidential client (BFF pattern). No tokens reach the browser.

1. SPA → `GET /api/v1/auth/login?next=/forms`. The API creates `state`, `nonce` and a PKCE verifier, stores them in Redis for 10 minutes, sets a 10-minute HttpOnly cookie holding a hash of `state` (`__Host-justforms_oidc_state` behind HTTPS) that binds the sign-in to this browser, and redirects with 302 to the IdP authorize endpoint.
2. IdP → `GET /api/v1/auth/callback?code&state`. The API refuses a `state` whose hash doesn't match the browser's cookie (login CSRF, best effort: a callback without the cookie, as when a phone's authenticator broker or in-app browser finishes the sign-in, is accepted on the one-time Redis state), exchanges the code, validates the ID token (issuer, audience, nonce, signature via JWKS), and upserts the user by (`iss`, `sub`) with email and name. Group mappings (org roles and superadmin, §7) are applied at this point.
3. The API creates a server-side session in Redis (8 h idle, 7 d absolute) and sets the `justforms_session` cookie (`HttpOnly; Secure; SameSite=Lax; Path=/`) plus a non-HttpOnly `justforms_csrf` cookie. With secure cookies both are named with the `__Host-` prefix and only those names are read.
4. Logout clears the session, sends `Clear-Site-Data: "cookies"` and, if the IdP advertises `end_session_endpoint`, performs RP-initiated logout.
5. A successful sign-in redirects to `next` (a same-origin path without control characters, spaces or backslashes, checked by the API and again by the SPA), else `/forms`, never `/` (a redirect for `/` cached by an earlier app on the hostname is not followed). It sends no `Clear-Site-Data`: some mobile browsers hold the response, session cookie included, while clearing their cache. nginx answers 404 for common service-worker script paths so such a worker unregisters; JustForms has none.

**Automatic sign-in** (`JUSTFORMS_OIDC_AUTO_REDIRECT`, default on when OIDC is configured). OIDC is then the only staff method, so the `/login` route's `beforeLoad` (reached directly, or through the signed-out redirect of any studio route) sends the browser to `/api/v1/auth/login?next=…` with `location.replace` before anything renders; the page shows only "Signing you in…". A pending invitation link does the same with `next=/login/invite/{token}` and `login_hint` = the invited address. Escape hatches, so it never loops:

- Signing out sets a per-tab flag (sessionStorage); `/login` then shows "You're signed out" with a "Sign in again" button instead of signing straight back in. The flag clears on that button or when a session is seen.
- A failed callback lands on `/login?error=…`, which shows the error and a "Try again" button and never redirects by itself.
- `/login?manual=1` (and `/login/invite/{token}?manual=1`) shows the normal page.
- Each automatic attempt sets a 30-second cookie (`justforms_sso_attempt`; a cookie because the sign-in response clears storage); within that window the page is shown instead of redirecting again.

Public forms, approver and verify pages never redirect.

Fallback for OSS installs with no IdP: when `JUSTFORMS_OIDC_ISSUER` is unset, staff log in with an emailed one-time code using the same mechanism as §8.2. The first admin is created with `justforms create-admin --email`; everyone else is invited (§7). Only existing users and addresses with an open invitation get a code (the request answers the same way for any address). Only one of these modes is active at a time. When OIDC is configured, local login is disabled.

### 8.2 Respondents: email OTP (`access_mode = otp`)

1. `POST /api/v1/public/forms/{slug}/otp/request {email}`. The API generates a 6-digit code, stores its HMAC with a 10-minute TTL, and enqueues an email. The response is always 202 so the endpoint cannot be used to discover which emails exist.
2. `POST /api/v1/public/forms/{slug}/otp/verify {email, code}`. Each code allows 5 attempts and is then invalidated. On success the API returns a **respondent token**: a signed JWT (HS256 with the app key) with claims `{form_id, email, exp: 2h}`. The public bundle holds it in memory and sends `Authorization: Bearer`.
3. The submission records `respondent_email` as verified.

Optional per-form settings: an allowed email domain list (e.g. `@example.org`) and one submission per verified email.

### 8.3 Anonymous (`access_mode = public`)

No identity is required. Abuse is handled with rate limits and an optional CAPTCHA (§14). The public bundle does not use cookies at all.

### 8.4 Staff-only forms (`access_mode = staff`)

The respondent must have a staff session (OIDC) and belong to the form's organisation (or have access to the form, or be a superadmin); anyone else signed in gets 403 `not_in_organisation`. This is for internal forms. The public bundle detects the 401 and redirects to `/api/v1/auth/login?next=...`.

---

## 9. Signatures and the PDF audit trail

### 9.1 Capture (client)

- The signature pad is built on shadcn primitives (`Card`, `Button`), with a `<canvas>` driven by Pointer Events. It records strokes as `[[x, y, t, pressure], ...]` per stroke, in pad-normalised coordinates (0–1 on both axes) with `t` in milliseconds since the pad was first touched.
- Buttons: Clear and Undo stroke. The attestation text is displayed above the pad, in the form's language and direction.
- On submit the client sends the strokes, an `svg` (paths generated from the strokes on the client and used only for preview), the client timestamp, pad dimensions, device pixel ratio and the displayed attestation text.

### 9.2 Server processing

1. Validate the strokes: at least 1 stroke, at least 10 points, at most 20,000 points, coordinates in range, and a minimum bounding box so that a single dot is rejected.
2. **Re-render server-side** from the strokes to SVG (written directly) and to PNG (Pillow, 4× supersampled, deterministic: the same strokes always give the same bytes). The client's drawing is never trusted. Store `signatures/{submission_id}/{field_id}.svg|.png`. The answer value becomes `{"signatureId": ...}`; strokes and audit data live in `signatures`.
3. Compute `strokes_sha256` over the canonical JSON of the strokes.
4. Record `received_at`, IP (unless IP capture is disabled for the form), user agent, the attestation text, and the form's language.

### 9.3 Submission content hash

`content_hash = SHA-256( JCS({ form_id, form_version_id, schema_hash, submission_id, submitted_at, data, files: [{fileId, sha256}], signatures: [{fieldId, strokes_sha256, received_at}] }) )`

JCS is the RFC 8785 JSON Canonicalization Scheme (Python `rfc8785`). The hash covers the data, the exact schema version, every file's bytes (via each file's sha256, computed when the file is attached) and every signature. It is stored on the submission and printed in the PDF.

### 9.4 Event hash chain

Each `submission_events` row stores `hash = SHA-256(prev_hash || JCS(event_without_hash))`. The first event (`created`) uses `prev_hash = content_hash`. Status changes and comments therefore extend a chain, and `GET /submissions/{id}/verify` recomputes it. A direct database edit breaks the chain and the UI shows it as "integrity check failed".

### 9.5 Signed PDF

For any submission with at least one signature (and on demand for any submission), the worker job `render_submission_pdf` does the following:

1. Renders the document with **fpdf2** and HarfBuzz text shaping (`uharfbuzz`), so Thaana is shaped and laid out right to left with no system libraries (a pure-Python stack that also runs on developer machines; WeasyPrint needs Pango). Fonts are bundled in `app/pdf/fonts` under the SIL OFL: Inter (a Latin subset) and Noto Sans Thaana (Faruma is never bundled; an operator may supply a Thaana face for server rendering, §16 Fonts). The direction follows the form's language (`dv` → RTL); the fixed labels are English for every form (§16). **The PDF is the respondent's document and prints only** (decided):
   - the form title, the reference number (`#seq`) and the submission date;
   - every visible question and answer in schema order (repeaters as tables, files by name and size);
   - signature images, each under the statement the signer saw (form content, so it stays);
   - the approval record when the form uses approvals (§15.3): step number and name, outcome, approver name and email, and date. Rejection comments are not printed; they are in the outcome email and the studio;
   - a footer on every page: a QR code to the public verify page (§9.5.2), "Digitally signed. Verify at {url}", and the reference with "page n of N".

   It no longer prints the IP address, device, stroke or file hashes, the organisation header, the version or an audit page. That audit data stays in the studio (each signature's IP, device and stroke hash; "Audit details" in the detail sheet with the content hash, form version hash, activity log head and the PDF's SHA-256) and, for the hashes that tie the file to its record, in the signed document metadata: the PDF keywords carry `justforms-submission`, `justforms-content-hash`, `justforms-version-hash` and `justforms-log-head`, all covered by the signature. Mixed Dhivehi/Latin lines (reference, URL, page numbers) are drawn as separately shaped runs from the start edge, so the bidi algorithm never reorders them (this fixed "# …0001" coming out scrambled in dv PDFs), and the page total comes from a two-pass render instead of fpdf2's `{nb}` alias.
2. **Digitally signs** the PDF with **pyHanko** (PAdES-B-B, or B-T when a TSA is configured), using the org signing certificate:
   - **Default (decided):** each install has its own self-signed RSA-3072 signing key and certificate, generated by `justforms init-signing-key` (or automatically on first start). This is tamper-evident but not trusted by viewers unless the certificate or its fingerprint is published.
   - **Later:** an org can upload its own certificate (PKCS#12 from its PKI) in the admin UI, or the operator mounts one as a secret (`JUSTFORMS_PDF_SIGNING_P12`, `..._PASSWORD`). Not required for v1.
   - Optional RFC 3161 timestamping: `JUSTFORMS_PDF_TSA_URL`.
3. Stores the result at `pdfs/{form_id}/{submission_id}.pdf`, sets `signed_pdf_key`, and appends a `pdf_generated` event (including the sha256 of the PDF). A finished approval makes and signs the PDF again with the approval record; the newest copy replaces the stored one, and older copies still check as genuine but "older".

Anyone can verify a PDF in Acrobat, through the signature panel, or with `justforms verify-pdf file.pdf`. The CLI checks the PDF signature and recomputes `content_hash` against the database.

#### 9.5.1 Signing trust options

How much a PDF viewer trusts the signature depends on where the signing certificate comes from. Tamper detection works the same in every option; what changes is whether the viewer can name the signer.

1. **Self-signed per-install key (default).** Created on first start, nothing to set up. Any edit to the PDF breaks the signature, but Acrobat reports the signer's identity as unknown, because no trusted authority vouches for the key. People check a PDF instead through JustForms: "Check a PDF" in the studio, `justforms verify-pdf`, and the verify page reached from the QR code on the PDF (§9.5.2).
2. **An organisation's internal CA.** An organisation that runs its own certificate authority (for example Active Directory Certificate Services on Windows) issues a document-signing certificate and loads it through the existing PKCS#12 option (`JUSTFORMS_PDF_SIGNING_P12`, `JUSTFORMS_PDF_SIGNING_P12_PASSWORD`). On managed PCs where Acrobat is set by policy to trust the Windows certificate store, the signature then shows as valid with the organisation's name (a green tick). Outside those PCs it is still reported as untrusted.
3. **Publicly trusted signatures (backlog).** Certificates on the Adobe Approved Trust List (AATL) are trusted by Acrobat everywhere, but their keys must live in certified hardware, so they cannot be loaded as a PKCS#12 file. This needs a pluggable remote-signer adapter that sends the PDF digest to a cloud signing service, for example one built on the Cloud Signature Consortium (CSC) API such as GlobalSign DSS or SSL.com eSigner (§21).

#### 9.5.2 Public verify page

Every signed PDF carries a QR code to `/v/{token}`. The token is 128 random bits (`secrets.token_urlsafe(16)`), created with the submission's first PDF and kept, so every signed copy points at the same page. The page (and `GET /public/verify/{token}`) is **status only** (decided): "Genuine document" or "This document was changed" (the content hash or the activity log no longer verifies), the issuing organisation's name, the reference number, the date the latest copy was signed and, when the form uses approvals, the outcome ("Approved on …", "Rejected on …", "In progress (step n of N)", "Stopped"). It never returns answers, names, email addresses or the form's title. Unknown tokens, deleted submissions and submissions without a signed PDF are "Document not found". "Check your copy" uploads the PDF (`POST /public/verify/{token}/check`, 20 MB, rate limited) and answers: genuine; genuine but an older copy; changed after signing; a different document; the record changed since signing; or not signed by this install. Responses send `Referrer-Policy: no-referrer`; the pages are `noindex` and refuse framing.

The page is a separate entry (`doc.html`, built on its own so it never changes how the public form is chunked) with a 95 KB gzip budget for its initial load (86 KB today, mostly React). Its strings are English for every form (§16); only the form title and the approver's view of the answers take the form's language and direction.

---

## 10. File uploads

Files are stored through the storage backend selected by `JUSTFORMS_STORAGE_BACKEND`:

- **`local` (default).** Files live under `JUSTFORMS_STORAGE_LOCAL_PATH` (`/data/storage` in the image) on a Compose named volume or a Helm PVC that `api` and `worker` both mount. Works out of the box with no extra services. Writes go to a temp file and are renamed into place, so readers never see partial objects.
- **`s3`.** Any external S3-compatible service, configured with `JUSTFORMS_S3_ENDPOINT_URL` (empty for AWS), `JUSTFORMS_S3_BUCKET`, `JUSTFORMS_S3_REGION`, `JUSTFORMS_S3_ACCESS_KEY_ID`, `JUSTFORMS_S3_SECRET_ACCESS_KEY` and `JUSTFORMS_S3_ADDRESSING_STYLE`. The operator creates the bucket, its CORS rule (allow the app origin) and a lifecycle rule expiring `tmp/` after 1 day.

Object keys are the same on both backends (`tmp/...`, `files/...`, `pdfs/...`, `exports/...`) and are validated as safe relative paths, so moving from `local` to `s3` is a plain copy of the directory tree into the bucket.

Flow for the public form and studio alike:

1. **Init.** `POST /api/v1/public/forms/{slug}/uploads {fieldId, name, size, mime}`. The server checks the field exists in the **live version**, that `size ≤ maxSizeMb` (capped globally by `JUSTFORMS_MAX_UPLOAD_MB`, default 25), and that the mime or extension is in `accept`. It also enforces per-IP and per-form upload rate limits. It creates a `files` row with state `pending` for key `tmp/{form_id}/{file_id}` and returns an upload target:
   - `s3`: an **S3 presigned POST** (valid 15 min) with conditions `content-length-range [1, maxBytes]` and an exact `Content-Type`. Presigned POST is used instead of PUT because only POST policies can enforce a size range.
   - `local`: the API's own upload URL `PUT /api/v1/public/uploads/{file_id}` with a short-lived upload token bound to the file row (sent in the `X-Upload-Token` header).
2. **Upload.** The browser sends the file and shows progress.
   - `s3`: posts directly to the bucket. Bytes never pass through the API.
   - `local`: the API streams the body to disk in chunks, counting bytes and aborting with 413 as soon as `maxBytes` is exceeded (nothing is left behind). nginx `client_max_body_size` is set just above the global cap.
3. **Reference.** The form value holds `{fileId}`. On submit, the server checks for each referenced file that the row is `pending`, belongs to this form and field, and was created by this upload session. Upload sessions use a per-page-load nonce issued with the form, which stops files being stolen across sessions. The server then stats the object to confirm size, reads the first 4 KB to **sniff magic bytes** (a small built-in signature table in `app/uploads/sniff.py`, no libmagic) and reject files whose bytes contradict their name or type, or that `accept` does not allow, and streams the object once to compute its sha256. Finally it moves the object to `files/{org_id}/{form_id}/{submission_id}/{file_id}` (a rename on `local`, copy + delete on `s3`) and marks the row `attached`.
4. **Cleanup.** A nightly worker job marks stale `pending` rows `orphaned` and deletes their objects. On `s3` the bucket lifecycle rule on `tmp/` is a second safety net.
5. **Download.** `GET /api/v1/files/{id}` runs the form-role check, then either returns 302 to a presigned GET (5 min, `s3`) or streams the file itself (`local`). Both use `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`. The one exception is `?preview=1` for studio thumbnails: raster images only (PNG, JPEG, GIF, WebP, by sniffed type), streamed by the API with `Content-Security-Policy: default-src 'none'; sandbox`. Answers keep the server's own file metadata (`fileId`, name, size, sniffed type); whatever the client sent is replaced on submit.

Antivirus scanning comes later. `scan_status` already exists in the schema. A later phase adds a ClamAV sidecar and a `scan_file` worker job, and unscanned or infected files will then be blocked from download based on org policy.

---

## 11. Notifications and webhooks

### 11.1 Email

- SMTP only (`JUSTFORMS_SMTP_*`). Messages are sent by the worker and rendered from Jinja2 templates as both HTML and text. Template wording is English for every form, `dv` ones included (§16); form content in an email (title, labels, answers, `successMessage`, approval step names) is shown in the form's language and direction inside the English, left-to-right message.
- **Owner notification.** Sent to the configured recipients (up to 10 addresses, inside or outside the organisation; empty = the form's owners) with a summary and a link to the submission. Answers are included only if `include_answers` is on, and sensitive fields are never included.
- **Respondent receipt.** Sent to the verified OTP email (or the signed-in staff address), or to the value of a designated `email` question (not in a repeater). A typed address counts as confirmed only when it equals the confirmed one; any other typed address gets a receipt only when the owner turns on `toUnverified` ("Send to addresses nobody confirmed"; upgraded forms that already sent to a question have it on). Those receipts are limited to 3 an hour per address and form and `JUSTFORMS_RECEIPT_UNVERIFIED_PER_HOUR` (default 100) per form; over a limit the row is logged as failed and nothing is sent. They carry only the confirmation, the reference and the owner's wording with `{answer:…}` placeholders left empty; the answers and the signed PDF go too only with `unverifiedAnswers`. A receipt can attach the signed PDF, in which case the job waits for the PDF job to finish.
- **Custom wording.** Each rule can replace the subject and the opening text (plain text, not HTML; the receipt's replaces the thank-you or the form's success message, the owner's goes above the link) and set a Reply-To address. Placeholders: `{reference}`, `{form_title}`, `{submitted}` and `{answer:<question key>}` for a question outside a repeater that isn't sensitive, a signature or a file. Saving refuses any other placeholder; an unanswered question fills in as empty. The reference, the answers and the PDF note stay as they are. The owner writes this text, so it is not system text and may be in any language.
- **Test emails.** `POST /forms/{formId}/notifications/test` (owners, rate limit `notify_test`, 5 an hour per person) queues both emails rendered with the current settings, sample answers (each question's label in brackets), reference `#0000`, no PDF and "[Test]" before the subject. They go only to the person asking, read no submission and appear in the email log as `test_owner_new` / `test_receipt`.
- **Form shared.** When an owner shares a form with members and ticks "Notify by email" (§7), each person who gets a role or a higher one is emailed (kind `form_shared`), with the owner's optional note and Reply-To set to the owner.
- **OTP emails.** These go on a priority queue.

Retries: 5 attempts with exponential backoff starting at 30 seconds. After that the failure is logged and shown on the form's Notifications page.

### 11.2 Webhooks

Events: `submission.created`, `submission.status_changed`, `submission.comment_added`, `submission.pdf_ready`, `submission.approval_step` (§15.3; `change.action` is `requested`, `approved`, `rejected`, `stopped` or `waiting`). A status set by an approval sends `submission.status_changed` with `change.via: "approval"`.

Payload:

```json
{
  "id": "evt_01JB...",
  "type": "submission.created",
  "createdAt": "2026-10-23T08:15:02Z",
  "form": { "id": "...", "slug": "youth-programme", "url": "https://forms.example.org/youth-programme", "version": 3 },
  "submission": {
    "id": "...", "seq": 142, "status": "new", "language": "dv",
    "submittedAt": "...", "contentHash": "sha256:...",
    "data": { "full_name": "Aishath Ali", "national_id": "[redacted]" },
    "url": "https://forms.example.org/forms/0192.../submissions?open=0192..."
  }
}
```

File values carry download URLs that point at the authenticated app endpoint. Presigned S3 URLs are never sent. Sensitive fields are redacted unless `include_sensitive` is set.

**Signing** follows the Stripe/Standard-Webhooks style:

```
JustForms-Webhook-Id: evt_01JB...
JustForms-Webhook-Timestamp: 1761207302
JustForms-Webhook-Signature: v1=<hex(HMAC_SHA256(secret, f"{id}.{timestamp}.{raw_body}"))>
```

- The secret is 32 random bytes shown once (`whsec_...`) and can be rotated. During rotation both the old and new signatures are sent (`v1=...,v1=...`) for 24 h.
- Receivers should reject timestamps older than 5 minutes. The docs include verification snippets for Python, Node and PHP.

**Delivery:**

- 10 s timeout. Any 2xx counts as success. Redirects are not followed.
- On failure, retries follow this schedule: 1 m, 5 m, 30 m, 2 h, 6 h, 12 h, 24 h (8 attempts in total) via arq deferred jobs, and the delivery is then marked `failed`. After 20 consecutive failed deliveries the webhook is auto-disabled and the owners are emailed.
- The delivery log UI shows request, response code, snippet and duration, and has a "Redeliver" button and a "Send test event" button.
- **SSRF guard.** The URL is resolved at delivery time, and private, loopback, link-local and metadata IP ranges are rejected unless they match `JUSTFORMS_WEBHOOK_ALLOWED_CIDRS`. Installations with internal receivers add their ranges to this allowlist. Only `https` is allowed, except `http` to allowlisted CIDRs.

---

## 12. AI design

### 12.1 Principles

- The LLM **only calls tools**. Each tool maps to a deterministic schema operation implemented in Python, and the LLM never emits raw schema JSON, code, HTML or CSS.
- Every tool call is applied to an **in-memory working copy** of the draft and validated with the full Pydantic schema validators plus the logic validator (unknown references, cycles). If validation fails, the error goes back to the model as the tool result so it can correct itself.
- The builder's model sees the **form schema only**; submission data never goes to the provider from the builder. The only path that sends anything about submissions is "Ask your submissions" (§12.6): counts always, and answers only when the form's owner turned on "Allow AI to read answers".
- The result is a **proposal**: an RFC 6902 patch plus a natural-language summary. Nothing reaches the draft until the user clicks **Apply**. Apply writes one `form_draft_history` entry, which a single **Undo** reverts.
- If `JUSTFORMS_AI_PROVIDER` is unset or `none`, `/ai/*` returns 404 and `GET /api/v1/meta` reports `ai: false`, so the studio hides every AI entry point.

### 12.2 Tools

All ids are element ids from the current working copy. `field` objects use the same JSON shape as the schema in §4, with the server filling in missing ids.

| Tool | Arguments | Notes |
|---|---|---|
| `get_form` | — | Returns a compact outline (ids, types, labels, logic) for orientation on long chats |
| `update_settings` | `title?`, `description?`, `language?`, `submitLabel?`, `successMessage?` | |
| `add_page` | `title`, `afterPageId?` | Returns the new page id |
| `update_page` | `pageId`, `title?` | |
| `remove_page` | `pageId`, `moveElementsTo?` | |
| `add_field` | `parentId` (page/section/repeater id), `index?`, `field` | Covers `field`, `content`, `section` and `repeater` kinds |
| `update_field` | `id`, `changes` (partial object; `null` deletes a prop) | `id` cannot be changed after publish |
| `remove_field` | `id` | Fails if other elements' logic references it, and returns the list of referencing elements |
| `move_field` | `id`, `parentId`, `index` | |
| `set_options` | `id`, `options[]` | Replaces the choice options |
| `set_logic` | `targetId`, `kind: "visibleIf" \| "requiredIf"`, `condition \| null` | |
| `set_page_navigation` | `pageId`, `rules: [{if, goto}]` | |
| `flag_uncertain` | `targetId`, `note` | Used by document import to mark low-confidence items. Shown as warnings in the preview |

Tool JSON Schemas are generated from Pydantic argument models, so the definitions given to the provider always match what the validator accepts.

### 12.3 Flows

**Describe → form** (`mode=create`, on an empty draft):
User prompt → system prompt (role, schema rules summary, field type catalogue, the form's language, "use tools only") → tool loop → proposal → preview → Apply.

**Chat edits** (`mode=edit`): the same loop seeded with `get_form` output for the current draft (at `draft_revision`). If the draft revision has changed by the time the user clicks Apply, because someone else edited it, the server rebases the patch when it applies cleanly and otherwise asks the user to re-run.

**Paper / PDF / photo → form** (`mode=import`). **Blank forms only (decided):** this flow exists to recreate the structure of an empty paper form. The upload dialog names the provider the pages go to, and the person must tick "This form is blank" for every upload (the API refuses requests without `blankConfirmed=true`). Filled-in forms never leave the server for an AI provider, and the builder's assistant never sends respondent data; the one path that sends anything about submissions is "Ask your submissions" (§12.6), under its own rules.
1. The studio posts the file itself to `POST /forms/{formId}/ai/sessions/{id}/import` (raw body, at most 20 MB; PDF, JPEG, PNG or WebP). It is read in memory for that request and never stored. HEIC is not accepted (no licence-clean decoder in the image); phones can share JPEG.
2. The API rasterises PDF pages with `pypdfium2` (150 dpi, at most 10 pages, scaled down so a page is never more than 2048 px on its longer side, page boxes over 200 in refused) and normalises photos (EXIF orientation, max 2048 px, JPEG; JPEGs are decoded at a reduced scale, and an image over 40 megapixels after that is refused before decoding with 413 `image_too_large`), so a tiny file can't make the server allocate gigabytes. This takes a second or two, so import runs in the request like a chat turn (same SSE stream, Stop and limits) instead of a worker job.
3. It calls a vision-capable provider with the images, instructing the model to recreate the structure (sections, fields, choices, signature boxes, labels as printed, in the form's language) using the tools, and to call `flag_uncertain` wherever it is unsure.
4. The suggestion is stored on the `ai_session` and streamed to the studio, where the person reviews it, including flagged items, before applying. If the model sees a filled-in document it calls `report_filled_in` instead, and nothing is added.

**Loop limits:** at most 40 tool calls per request (`JUSTFORMS_AI_MAX_TOOL_CALLS`), 12 rejected tool calls, a 120 s wall clock (`JUSTFORMS_AI_TURN_SECONDS`), daily token allowances per person and per organisation (`JUSTFORMS_AI_DAILY_TOKENS_PER_USER`, `_PER_ORG`: every provider call first reserves its worst case, input characters / 3 plus the output limit, atomically against both and is refused when that would pass either; the reservation is then settled with the real usage, estimated from characters when the provider reports none; the day's first call always goes), one running AI request per person (a newer request on any form, or reopening a chat with `fresh`, stops the older one within half a second), rate limits `ai_request` (per person and per organisation) and `ai_import`, requests of at most 4,000 characters, and forms of at most `JUSTFORMS_AI_MAX_FORM_CHARS` of JSON. Requests stream to the studio over SSE, with events `message.delta`, `tool.applied`, `tool.error`, `proposal`, `error`, `cancelled`, `filled_in` and `done`. A request that fails, times out or is stopped keeps nothing.

### 12.4 Provider interface

```python
class AIProvider(Protocol):
    name: str
    capabilities: set[Literal["tools", "vision", "streaming"]]

    async def run_turn(
        self,
        system: str,
        messages: list[ChatMessage],          # provider-neutral: text, images, tool calls, tool results
        tools: list[ToolSpec],                # name, description, JSON Schema params
        *,
        max_output_tokens: int,
        stream: Callable[[ProviderEvent], Awaitable[None]] | None = None,
    ) -> TurnResult: ...                      # assistant text + list[ToolCall] + usage
```

The orchestrator (`justforms/ai/orchestrator.py`) owns the loop: it calls `run_turn`, executes the tool calls against the working copy, appends tool results and repeats until the model stops calling tools. Adapters only translate formats.

Adapters in v1:
- `gemini` (Gemini API `generateContent`; the model's parts, including thought signatures, are replayed unchanged)
- `anthropic` (Messages API)
- `openai_compat` (any Chat Completions + tools endpoint: OpenAI, Azure OpenAI, vLLM, Ollama, LM Studio, OpenRouter). This one also covers "local".

Configuration:
- `JUSTFORMS_AI_PROVIDER` (`none`, `gemini`, `anthropic`, `openai_compat`; `fake` plays scripted tool calls in development and tests and is refused in production), `JUSTFORMS_AI_MODEL`, `JUSTFORMS_AI_API_KEY`, `JUSTFORMS_AI_BASE_URL`.
- Optionally `JUSTFORMS_AI_VISION_MODEL`, which lets import use a different model, and `JUSTFORMS_AI_VISION` (unset: on for gemini and anthropic, off for openai_compat, since local models often can't read images). Import is hidden and refused when the model can't read images. `JUSTFORMS_AI_PROVIDER_LABEL` names the provider in the upload dialog.

Operators should give JustForms its own provider credentials rather than sharing keys with other applications.

### 12.5 As built

- **Adapters use plain HTTPS (httpx), not the vendor SDKs.** Each adapter is a small request/response translation, tested against recorded shapes without network access, and JustForms carries no extra SDK dependency trees. Transient failures (429, 5xx, timeouts) are retried once.
- **Tools** (`app/ai/tools.py`) are the §12.2 set. `update_settings` cannot change the language or theme (the person picks the language; the AI writes in it), `update_field` cannot change ids, kinds or child elements, and the AI can't set image or logo file ids. Missing ids are made from labels (or the type, for Thaana labels) and options get values from their labels. Every call is validated by the full `Form` model, including reference and cycle checks; a failing call changes nothing and its error goes back to the model.
- **Suggestions.** Each request starts from the pending suggestion (follow-ups refine it) or from the saved draft. The studio flushes autosave first, shows the suggestion on the canvas from a read-only builder store with added and changed questions marked, and locks the draft (no edits, no undo) until Apply or Discard. Apply writes one `form_draft_history` entry with `actor_type = ai` and the session id, so one Undo reverts it. When the draft moved on since the suggestion, the server applies the patch with `test` operations guarding everything it touches (whole lists where it adds or removes items); a clash returns 409 `proposal_stale` and the studio offers "Ask again".
- **Language.** The system prompt asks for content in the form's language (Dhivehi in Thaana, formal register, for `dv` forms); the reply to the person and all assistant UI are English. Suggestions flag added or changed questions written in the wrong script, and `dv` suggestions always carry "Check the Dhivehi wording before you publish."
- **Privacy.** Only the form schema and the person's requests go to the provider: no submissions, no approval or notification settings. A test submits answers and checks they never appear in anything sent. Audit entries (`ai.session_create`, `ai.request`, `ai.import`, `ai.apply`, `ai.discard`, `ai.cancel`) record counts, outcome and tokens, not the text.
- **Permissions.** Editors and owners only; each chat is visible to the person who started it. With `JUSTFORMS_AI_PROVIDER` unset every `/ai` endpoint returns 404 and `GET /meta` reports `features.ai = false` (plus `aiVision` and `aiProviderLabel`).

---

### 12.6 Ask your submissions (built)

A panel on the Submissions pages (docs/ux/INSIGHTS-SCREENS.md §4; the form bar's "Ask about
submissions", or the card on Insights) that answers
questions about a form's submissions ("how many organisations want to know about disability
rights?") for anyone who can see them (viewers, editors, owners). Hidden, and every
`/forms/{id}/ask` endpoint 404, when no provider is configured. Code: `app/insights/ask.py`,
`app/api/v1/insights.py`.

- **Tools, run on the server with the asker's access.**
  - `query_submissions`: the submissions query language (`app/insights/dsl.py`, below) for
    counts, groups (`groupBy` up to two questions, or `_status`, `_submitted` by day/month/year,
    `_version`) and aggregates (`count`, `sum`, `avg`, `min`, `max`, `median`, `distinct`),
    optionally listing up to 50 matching submission numbers with chosen answers. Returns
    numbers, option labels and references; each result gets an id (`q1`, `q2`, …).
  - `list_submissions`: a table of the matching submissions for the person, with the answers
    to up to 8 chosen questions or submission details (`_status`, `_submitted`, `_respondent`,
    `_approval`), newest (or oldest) 500. The server reads the values from the database and
    shows them exactly as answered (sortable, copy as tab-separated text, CSV download), so
    the model never writes a listed value. The model gets the row count and how many rows
    answered each column; with "Allow AI to read answers" on it also gets the values (within
    the size budget below, `rowsTruncated` beyond). Works with reading off: the values then
    go to the person only. It is how "contact number of all CSOs" is answered; the prompt
    tells the model never to call permitted data restricted.
  - `read_answers`: every textual answer for at most 500 matching submissions (newest first):
    chosen questions or, with no `fields`, all of them, including contact details, sensitive
    questions, repeater rows (a repeater's key reads its rows), "Other" texts, and each
    submission's reference, status, submitted time, respondent email and approval state.
    Files and signatures only say whether one was provided ("1 file provided", "signed"),
    never names or content; IP addresses never go. Each answer is cut to `maxChars` (≤ 2000).
    At most 150,000 characters go to the model per question, shared by every
    `read_answers` and `list_submissions` call; a cut result has `truncated: true` and a note
    telling the model to say how many submissions it covers. Offered only when the form's
    `settings.aiReadAnswers` is on.
  - `show_result`: shows an earlier result (by id) as a bar chart or a table under the answer,
    or (`display: "list"`) the submissions it counted, like `list_submissions` (default
    column: the form's name question). The server builds it from the stored result or the
    database, so its numbers are never the model's.
- **Query language.** JSON validated by Pydantic (`extra="forbid"`, keys matching the question
  key pattern, bounded lists) and compiled to SQLAlchemy Core over the JSONB answers: keys and
  values are bound parameters and every key must be a question of the form, so nothing the
  model writes becomes SQL. Conditions: `eq`, `neq`, `in`, `not_in`, `contains`, `gt`, `gte`,
  `lt`, `lte`, `between` (numbers; dates by prefix `YYYY`, `YYYY-MM`, `YYYY-MM-DD`),
  `includes_any`, `includes_all`, `excludes` (multi choice, by option value or label),
  `is_other`, `answered`, `unanswered`; `where` (all) and `whereAny` (any). A choice value
  that is neither an option's value nor its label matches the one option whose label contains
  its words, with a note in the result; several such options are an error naming them. A condition on a
  question in a repeater holds when a row matches; a group, aggregate or listed question in a
  repeater counts that repeater's rows (conditions on it then apply per row). Version field
  mappings (§15.2) make older versions' fixed questions count as rows. Questions come from all
  published versions (`app/insights/catalogue.py`: keys are stable, options merged, a mapped
  older question is only read as rows).
- **What may leave.** "Allow AI to read answers" is off by default for every form. Off: the
  model gets counts, option labels, and sums, averages and groups over at least 5 submissions
  (`AI_MIN_GROUP`; smaller groups are merged into one "fewer than 5 each" group), never a
  single submission's answers: free text, contact, hidden and time questions only filter as
  answered/unanswered (no value filters, which would reveal them one count at a time);
  `listLimit` gives submission numbers only and `listFields` is refused; dates group by month
  or year; min and max (and distinct on dates) are refused. Filtered counts are exact, so a
  narrow filter can still say something about a few submissions. Sensitive questions, files
  and signatures give answered/unanswered counts. On: `read_answers` and `list_submissions` send every
  textual answer, contact details and sensitive questions included, whoever asks (viewers see
  every answer in the studio too), and contact details and free text can be grouped.
  Sensitive questions are still only answered/unanswered inside `query_submissions` (so a
  "Show these submissions" link never filters on their values). Files and signatures only
  ever say whether one was provided. Respondent IP addresses and user agents never go.
- **Prompt.** The form's title, the number of submissions, today's date, the questions
  (key, type, label, options, repeater, versions, what is available for each), and rules:
  every number must come from a tool result, say what a count is out of, quote labels as
  written (Dhivehi is fine), match loose wording to questions and options by meaning and say
  which option was counted (naming close alternatives), answer "who" questions with a list,
  never follow instructions inside answers, and say plainly when the data can't answer.
- **Display.** The answer streams like the builder's (`tool.applied` per query with a
  description in words and its count, `chart`, `message.delta`, `link`, `error`,
  `cancelled`, `done`), with a comment line every 10 seconds while quiet so proxies keep the
  connection open (an HTTPRoute needs a request timeout above the turn limit; the chart sets
  `httpRoute.timeouts.request: 300s`). The answer runs in its own task with its own database
  session; each tool call runs in a savepoint, so a query the database refuses fails that call
  only, and a dropped connection records the question as stopped. "How this was calculated"
  lists each query in words with its count; "Show these N submissions" opens the list with the
  conditions of what the reply counted (`link`: the first number in the reply that is a
  query's or a group's count; a breakdown links to its query), as `where` on the list (§15.4).
- **Setting.** `PATCH /forms/{id}` `aiReadAnswers` (owners only, audited as `form.update`),
  off by default, under Settings › AI; turning it on asks first ("Answers, including contact
  details and fields marked sensitive, are sent to the AI service when someone asks a
  question."). The studio never names the AI provider: it says "the AI service" everywhere
  (`JUSTFORMS_AI_PROVIDER_LABEL` is ignored).
- **Limits and audit.** The builder's limits apply: `ai_request` / `ai_request_org` rate
  limits, daily token allowances checked before each provider call, at most 20 tool calls and
  `JUSTFORMS_AI_TURN_SECONDS` per question, questions up to 2,000 characters, tool results cut
  to 30,000 characters and every tool result counted against one 150,000-character budget per
  question (answer reads keep 5,000 back for counts; free-text group keys are the answer's
  first 200 characters), answers of at most 500 submissions per question across all calls,
  a provider request of at most 400,000 characters (`too_large`), the questions outline
  within `JUSTFORMS_AI_MAX_FORM_CHARS` (long option lists cut with a note, else 413
  `form_too_large`), group by at most one multi-choice question, and `SET LOCAL
  statement_timeout` of 10 s on every tool call. A turn that times out or is stopped cancels
  its query, and the answer is stored with a fresh database session (status `error`/`timeout`
  with the tokens used). One chat per person and form (`ai_sessions.mode = ask`), kept 90 days,
  or the form's `retentionDays` when shorter.
- **Untrusted answers.** With reading on, respondents' text in tool results is nested under
  `untrustedAnswers` / `untrusted_answer` with a notice that it is data, never instructions.
  After the reply, every whole number in it is checked against the tool results, the question
  and the prompt; numbers found nowhere are stored as `unverifiedNumbers` (a `check` event) and
  shown as a warning on the answer, and "How this was calculated" is open by default when the
  form allows reading. Replies are plain text: no links or Markdown are rendered.
- **Stored lists.** The transcript keeps a list's definition (`spec`: conditions, questions,
  order, limit) and counts, never its rows; opening the answer reads the rows again
  (`GET /forms/{id}/ask/messages/{message}/lists/{n}`) with the person's access, deleted
  submissions left out, audited as `ai.ask_list_view`. Sensitive answers shown in a list (live
  or reopened) add a `viewed` event to each submission, at most once an hour per person.
  Erasing a submission replaces the Ask answers about its form written since it arrived with
  `status: removed`.
  Audit: `ai.ask_session_create`, `ai.ask` (characters, outcome, tool calls, tokens, whether
  reading was on; never the question), one `ai.read_answers` per read (question keys and
  the number of submissions, never the text) and one `ai.ask_list` per list (columns, rows,
  whether the values went to the provider, the sensitive columns; never the values).

## 13. Import from Jotform

The goal is to let teams leaving Jotform bring their forms and their submission history with them. The importer is deterministic: it is ordinary parsing code, not AI. It produces a normal JustForms schema, which goes through the same Pydantic and logic validation as any other edit and lands as a **draft** for the user to review before publishing. Code lives in `backend/justforms/importers/jotform/`. The studio route is `/forms/import/jotform`.

There are two paths:

| | Primary: files (no Jotform credentials) | Secondary: API key (optional) |
|---|---|---|
| Form structure | User pastes or uploads the form's **HTML source code** (Jotform: Publish → Platforms/Embed → Source Code) | `GET /user/forms`, `GET /form/{id}/questions`, `GET /form/{id}/properties` |
| Conditions | Best effort only (see below); usually reported as "not imported" | Imported from `properties.conditions` where they can be translated |
| Submissions | User uploads Jotform's **Excel (.xlsx) or CSV submission export**, then maps columns to fields | `GET /form/{id}/submissions` (paged, `limit=1000`) |
| Bulk | One form at a time | Pick any or all forms from the account list |

### 13.1 Form import from HTML source (primary)

1. The user pastes the source into a textarea or uploads a `.html`/`.txt` file (at most 5 MB). The API job `import_jotform_html` parses it server-side with `selectolax` (or BeautifulSoup + lxml). Nothing in it is ever executed or rendered, and `<script>` content is read as text only.
2. **Field extraction.** Each question is an `li.form-line` element whose `data-type="control_*"` gives the question type and whose `id="id_{qid}"` gives the Jotform question id. Within it the parser reads:
   - the label from `label#label_{qid}`, with the required-marker `span.form-required` stripped;
   - `required` from the `form-required`/`jf-required` classes on the line or the `validate[required]` class on the input;
   - sub-labels and descriptions from `.form-sub-label` and `.form-description`;
   - options from radio/checkbox `input[value]` with their `label`s, or from `select > option`;
   - `maxlength`, `min`/`max`, `placeholder` and `accept` attributes;
   - the field name from `name="q{qid}_{slug}"`, which seeds the JustForms `id` (`slug` normalised to snake_case, deduplicated).
3. **Pages.** Each `control_pagebreak` line closes the current page and starts a new one. Page titles come from the next `control_head` if present, and otherwise "Page N". `control_collapse` becomes a step (a page titled with the section's text) or an open section; see "Collapsible sections" in §13.6.
4. **Conditions.** If the source contains an inline `JotForm.setConditions([...])` call, the parser extracts that JSON and translates the supported subset: `field` show/hide → `visibleIf`, `require` → `requiredIf`, and page skip → `next`. Operators map as `equals`→`eq`, `notEquals`→`neq`, `isEmpty`→`empty`, `isFilled`→`not_empty`, `lessThan`→`lt`, `greaterThan`→`gt`, `contains`→`contains`, and `any`/`all` link → `any`/`all`. Anything else is listed in the report as "not imported". This includes calculations, email routing, `startsWith`/`endsWith`, and conditions that reference unsupported fields. Expect that many embeds carry no conditions at all, in which case the report says so.
5. **Labels.** The import dialog sets the form's `language` (en or dv) and labels are imported as plain strings. Thaana text is detected by Unicode range, and when a form is mostly Thaana the dialog suggests `dv`.
6. **Import report.** This is shown before the draft is created and stored on the import record. It lists:
   - every question with its Jotform type → JustForms type, and its status (`imported`, `imported with changes`, `skipped`), each with a reason;
   - every condition as `imported` or `not imported`, with its reason;
   - form-level settings that were dropped (themes, autoresponders, payment, integrations).

   The user clicks **Create draft**. The result is then an ordinary draft, fully editable, and the AI chat can help finish it.

### 13.2 Question type mapping

| Jotform `control_*` | JustForms | Notes |
|---|---|---|
| `textbox` | `short_text` | `maxlength` and validation `Email`/`Numeric` hints are mapped where present |
| `textarea` | `long_text` | Rich-text mode is flattened to plain text |
| `email` | `email` | Confirmation-email sub-field is dropped (reported) |
| `phone` | `phone` | Split country/area/number inputs become one E.164 field |
| `number`, `spinner` | `number` | `min`/`max`/`step` |
| `datetime` | `date` | When a time part is present, an extra `time` field `{id}_time` is added (reported) |
| `time` | `time` | |
| `dropdown` | `single_choice` (`display: dropdown`) | |
| `radio` | `single_choice` (`display: radio`) | The "Other" option becomes `allowOther` |
| `checkbox` | `multi_choice` | Min/max selection limits are kept |
| `fileupload` | `file` | `accept` from the extensions list; size limit capped to the JustForms max |
| `signature` | `signature` | |
| `fullname` | `section` with `short_text` per enabled part (`prefix`, `first`, `middle`, `last`, `suffix`) | |
| `address` | `section` with `short_text` per enabled part (line 1, line 2, city, state, postal, country) | |
| `rating`, `scale` | `rating` | Scale range starting other than 1 is normalised (reported) |
| `yesno` / two-option radio Yes/No | `yes_no` | Only when the options are exactly Yes/No |
| `head` | `content` (heading) | |
| `text` | `content` (paragraph) | HTML reduced to the allowed Markdown subset |
| `divider` | `content` (divider) | |
| `collapse` | page (step) or `section` | A page by default when the form has no page breaks (§13.6). |
| `pagebreak` | new page | |
| `hidden`, `autoincrement` | `hidden` | Autoincrement values are not generated (reported) |
| `button` | — | The submit text becomes `settings.submitLabel` |
| `captcha` | — | Enables form CAPTCHA (`auto`) |
| `matrix`, `inline`, `widget` (incl. configurable list), `appointment`, `payment`/product lists, `image`, `mixed`, any unknown type | skipped | Reported as **unsupported**, with the original label so the user can rebuild it by hand |

The same table drives both the HTML parser and the API path, because the API's `questions[].type` values use the same `control_*` names.

### 13.3 Submission import from Excel/CSV (primary)

This works only against a form that has at least one **published** version. The user picks the target version, defaulting to the version created from the Jotform import.

1. **Upload.** The user uploads the Jotform submission export (`.xlsx` or `.csv`, at most 50 MB). The worker parses it with openpyxl in read-only mode, or with `csv` (sniffing the delimiter and decoding as UTF-8 with BOM, falling back to cp1252), and stores the header row and the first 20 rows.
2. **Column-mapping step (UI).** One row per source column, each with a shadcn `Select` target: a field id, or a sub-part of a section built from `fullname`/`address` (each part is its own field), or one of the metadata targets `submitted_at`, `respondent_email`, `ip`, or `(ignore)`. The server pre-fills the mapping by matching normalised column headers to field labels and ids. Jotform's `Submission Date`, `Submission ID` and `IP` columns are recognised. A preview table shows the first 20 converted rows with per-cell errors. The mapping is saved, so re-uploads reuse it.
3. **Conversion per type:**
   - numbers are parsed with `.` or `,` decimals;
   - dates in Jotform formats (`YYYY-MM-DD`, `MM/DD/YYYY`, `DD-MM-YYYY`, `Mon D, YYYY`, choosable in the UI when ambiguous);
   - `multi_choice` is split on newline or `, ` and matched to option labels, then to option values; unknown values are kept only if `allowOther` is set;
   - `yes_no` is matched against Yes/No in English or Dhivehi;
   - `file` and `signature` cells contain Jotform URLs, which are stored as an `importedLinks` note on the submission. Jotform serves those files only to a signed-in session or with an API key; with a key they can be copied in afterwards (see "Imported files" in 13.6).
4. **Commit.** The worker job `import_submissions` inserts submissions in batches of 500, with:
   - `source = 'jotform_import'`, `status = new` (or another status chosen in the dialog);
   - `submitted_at` from the mapped column, falling back to the import time;
   - a `created` event whose payload carries `{imported: true, importId, sourceRowNumber, jotformSubmissionId}`;
   - `content_hash` computed as usual.

   Cells that fail conversion are omitted and recorded per row. Rows that fail entirely, for example on a required metadata parse, are skipped. Logic-hidden stripping does **not** apply to imported rows, because historic data is kept as provided for mapped fields. Re-importing the same file skips rows whose `jotformSubmissionId` already exists, so imports are idempotent.
5. **Signatures.** Imported signatures are **not** part of the JustForms signature audit trail. No strokes, hash claims or signed PDF attestation are made for them. Such PDFs carry an "Imported from Jotform — signature not captured by JustForms" note.
6. **Import report.** Rows imported, rows skipped, and cells dropped (by column), downloadable as `.xlsx`.

### 13.4 API-key import (secondary, optional)

- **Key handling.** The user enters a Jotform API key and region (`api.jotform.com`, `eu-api.jotform.com`, `hipaa-api.jotform.com`). The key is used for this import job only. It is held in the job payload encrypted with the app key, deleted when the job ends, and never written to Postgres or logs.
- **Form selection.** `GET /user/forms` lists the account's forms, and the user ticks one or many.
- **Structure.** For each form, `GET /form/{id}/questions` and `GET /form/{id}/properties` go through the same mapping (§13.2). Ordering comes from `order`, and pages from `control_pagebreak`. Conditions are taken from `properties.conditions`, using the same translator and reporting as §13.1 step 4. This path gives the most complete condition import.
- **Submissions (optional checkbox).** `GET /form/{id}/submissions` is paged, and answers are keyed by question id, so **no column-mapping step is needed**. The importer publishes the imported schema as version 1, then imports into it with the same conversion and idempotency rules as §13.3.
- **Rate limits.** Jotform's daily API limits are respected by throttling to 1 request per second. On a 429 response the job pauses and resumes later, and progress is shown in the UI.

### 13.5 Data model and API additions

- **Data model.** New table `imports` (`id`, `org_id`, `form_id` nullable, `kind` enum(`jotform_html`,`jotform_api`,`jotform_submissions`), `status`, `source_file_id`, `mapping` jsonb, `report` jsonb, `created_by`, `stats` jsonb). `submissions` gains `source` enum(`justforms`,`jotform_import`) defaulting to `justforms`, plus `external_id` text, with a unique index on (`form_id`, `source`, `external_id`).
- **API:**
  - `POST /orgs/{orgId}/imports/jotform/html`: `{fileId | html, language}` → import with report preview; `POST /imports/{id}/commit` → creates the form draft.
  - `POST /orgs/{orgId}/imports/jotform/api/forms`: `{apiKey, region}` → form list (not persisted).
  - `POST /orgs/{orgId}/imports/jotform/api`: `{apiKey, region, formIds, includeSubmissions}` → job.
  - `POST /forms/{formId}/imports/submissions`: `{fileId, versionId}` → parsed headers + suggested mapping; `PUT /imports/{id}/mapping`; `GET /imports/{id}/preview`; `POST /imports/{id}/commit`.
  - `GET /imports/{id}`: status, stats and report.
- **Permissions.** Org members can import forms, and they become owner of each imported form. Importing submissions requires the **owner** role on the target form.

### 13.6 As built

- **Code.** `backend/app/importers/`: `dom.py` (a small read-only HTML tree on the standard library parser; nothing is executed), `jotform/html_source.py` and `jotform/api_source.py` (both read into the same `JfQuestion` list), `jotform/convert.py` (the §13.2 mapping, conditions and the report), `jotform/fetch.py`, `jotform/submissions.py` and `service.py`. API in `app/api/v1/imports.py`; studio screens in [docs/ux/JOTFORM-IMPORT-SCREENS.md](ux/JOTFORM-IMPORT-SCREENS.md) (`/forms/import/jotform`, `/forms/{id}/submissions/import`).
- **Form import.** `POST /orgs/{orgId}/imports/jotform/html` takes `{html}` (pasted, or an uploaded file read in the browser, at most 5 MB) or `{url}`, plus an optional `collapseAsPages` (see below) and `language` (otherwise detected: mostly Thaana letters → `dv`). The preview (schema + report) is stored on an `imports` row; `POST /imports/{id}/form {title?, language?}` creates the draft once. A form-level CAPTCHA question turns the form's CAPTCHA on (`auto`).
- **Fetch by URL.** Only `https` URLs on Jotform's form hosts (`form.jotform.com`, `www.jotform.com`, the EU and HIPAA hosts); every redirect hop is checked again (at most 3), every address goes through the SSRF guard and the request is pinned to it; 10 s timeout and a 5 MB cap. A form number alone is accepted.
- **Pages, titles, sections.** A heading before any question becomes the form title (its sub-heading the description); a heading right after a page break becomes the page title. Half-width questions (`form-line-column`) become `width: half`. Text blocks that are a single short heading become headings; other rich text is reduced to the renderer's Markdown subset. Jotform's calendar limits (`future`/`past`, `start`/`end`) become `minDate`/`maxDate`; a phone mask's calling code becomes `defaultCountry`. Field keys come from Jotform's field names (`q3_csoName` → `cso_name`); names Jotform makes up for Thaana labels are ignored and keys come from the type (`short_text_1`).
- **Collapsible sections.** Jotform shows `control_collapse` sections one at a time, like steps, and many forms use them instead of page breaks. The import option "Collapsible sections become steps (pages)" (`collapseAsPages`) decides what they become; it is on by default when the form has collapsible sections and no `control_pagebreak`, and off when it has page breaks. On: each collapse starts a page titled with its text, and the questions up to the next collapse or page break sit on it; page breaks still start pages. Questions before the first collapse keep a page of their own (Jotform shows them above every section); headings or text alone there join the first step. Off: each collapse is an open section that lasts until the next collapse or page break, which matches Jotform's markup (`ul.form-section-closed`). Question ids are the same either way. A show/hide rule on a collapse applies to its page or section, and page-skip rules count Jotform's pages, so they still land on the right page. The preview keeps both conversions on the import row; `PATCH /imports/{id}/options {collapseAsPages}` switches between them until the draft is created (409 afterwards, 422 when the form has no collapsible sections). The preview carries `collapseSections` and `collapseAsPages`, and the report says in its notes which one was used.
- **Conditions** are applied one at a time and each result is validated; a condition that would make the form invalid (loop, backwards jump) is reported as not imported.
- **Submissions.** `POST /forms/{formId}/imports/submissions?filename=` takes the raw file body, stores it under `imports/{id}/` and returns the columns with a suggested mapping (repeated labels map in order onto the questions with that label). `PUT /imports/{id}/mapping` saves the mapping and returns the first 20 rows converted; `POST /imports/{id}/start {status}` queues the `import_submissions` worker job, which runs in one transaction (all or nothing) and deletes the stored file afterwards. Metadata targets: submission date, Jotform submission ID (dedupe key, unique per form) and IP. File and signature cells are kept as links in `submissions.imported_links` (outside the answers and the content hash); imported rows send no notifications or webhooks and start no approvals.
- **Logo.** The form's cover logo (`#formCoverLogo img.form-page-cover-image`, or a
  `header-logo` image) is downloaded during the preview through the same SSRF guard (resolve,
  check, pin), https only, from Jotform's hosts (`www.jotform.com`, `form.jotform.com`, the EU
  and HIPAA hosts, `files.jotform.com`, `cdn.jotfor.ms`), every redirect re-checked (at most 3),
  10 s and 512 KB caps. JPEG, WebP and GIF are converted to PNG (≤ 1024 px); everything is then
  cleaned like an uploaded logo, kept at `imports/{id}/logo.{ext}` and set as the new draft's
  logo when it is created. The report carries `logo: {status, reason, source}`; an imported logo
  leaves the "Not imported" list.
- **API-key path.** Form structure and conditions only (`/user/forms`, `/form/{id}`, `/questions`, `/properties`), one form per request, key sent in the `APIKEY` header and never stored. Submissions through the API are not imported yet: use the export file.
- **Exact times and numbering.** Export files carry dates only (or times in the account's zone). When `JUSTFORMS_JOTFORM_API_KEY` is set and the form came from a Jotform import (`forms.settings.jotformFormId`), the submissions job reads `GET /form/{id}/submissions` (paged, 1000 at a time) and uses each row's `created_at`, which Jotform's API gives in US Eastern time (`JUSTFORMS_JOTFORM_API_TIMEZONE`), converted to UTC; the file's value is the fallback and the report's `exactTimes` says which was used. Rows get reference numbers in submitted-time order, oldest first, after the form's highest number; live submissions keep counting on from there.
- **Correcting an import** (`justforms rebuild-jotform-import --form <id|slug> [--jotform-form <id>] [--dry-run] [--actor <email>]`). `submitted_at` is part of the content hash and never changes on a row, and event history is never rewritten, so imported rows that nobody has worked on are rebuilt instead: each old row is removed (audit `submission.import_rebuilt`, with the new id, old/new number and time) and re-created with the exact API time, the reference numbers the imported rows already held handed out again oldest first, a fresh content hash and a `created` event carrying the original import payload plus `rebuiltFrom`, `previousSeq`, `previousSubmittedAt` and `timeSource`. Answers and imported links are carried over unchanged. It refuses the whole form when any imported row has moved on: any event besides `created` (status, comment, view of a sensitive answer), a PDF or verify page, an approval, uploaded files or drawn signatures, email deliveries, or a soft delete. Running it again changes nothing.
- **Imported files** (`justforms fetch-imported-files --form <id|slug> [--dry-run] [--actor <email>] [--report <file>]`, key in `JUSTFORMS_JOTFORM_API_KEY`). Every link without a stored copy is downloaded: `https` and Jotform's hosts only (the logo list above), every hop resolved, checked and pinned by the SSRF guard (at most 3 redirects, each re-checked), the key sent in the `APIKEY` header to the link's own host only (Jotform redirects to a short-lived file URL, fetched without it), 60 s per file. Files are capped at the question's size limit (itself capped by `JUSTFORMS_MAX_UPLOAD_MB`) and must pass the same type sniffing as uploads against the question's `accept`; signature images are capped at 2 MB and 4096 px, decoded and re-encoded as PNG. Copies are stored at `imported/{formId}/{submissionId}/{fieldId}-{n}{ext}` and recorded in place of the link in `submissions.imported_links` (`{url, key, name, mime, size, sha256, kind, fetchedAt}`), outside the answers and the content hash. Imported signatures are images only: no `signatures` row, strokes or attestation, so they are never part of the signature audit trail, and the studio marks them "Imported". Staff with access to the submission download them from `GET /submissions/{id}/imported-files/{fieldId}/{n}` (attachment; `?preview=1` shows images inline under a sandbox CSP). Each submission is committed on its own, stored copies are skipped on the next run and failures stay links to retry; the per-file report lists positions, kinds, sizes and reason codes (`auth`, `not_found`, `too_large`, `bad_type`, `host`, `fetch`), never names or links, and the run is audit-logged (`submissions.import_files`). Erasing a submission deletes its copies.

---

## 14. Security

### 14.1 Rate limiting

A Redis sliding-window limiter is applied as FastAPI dependencies. Limits are configurable, with these defaults:

| Endpoint | Limit |
|---|---|
| Public form fetch | 120/min per IP |
| Public submit | 10/min per IP per form; 1000/hour per form (then CAPTCHA forced on) |
| Upload init | 30/min per IP |
| OTP request | 3 per 10 min per email; 10/hour per IP |
| OTP verify | 5 attempts per code; 30/hour per IP; 10 failures a day per address (per approval step for approver codes, per address for staff sign-in), then locked out until the day passes |
| Auth callback / login | 30/min per IP |
| Invitations | 50 addresses/hour per admin; 200/day per organisation; 3 resends/hour per invitation; invitation page 60/min per IP |
| Share emails ("Notify by email") | 50 people/hour per sharer; 200/day per organisation |
| AI chat | 20/min per user, plus the token budget |

Checks are atomic: the limiter trims, counts and adds a hit in one Lua script, and a code check reserves an attempt (`HINCRBY`) in one script before comparing, so concurrent requests can't all pass a check before any is counted. At most `max_attempts` guesses are compared per code.

The client IP comes from `X-Forwarded-For` only when the request arrives from `JUSTFORMS_TRUSTED_PROXIES`, and is then the right-most hop that is not a trusted proxy (hops to its left are written by the client). The web container works the address out with nginx's real-IP module (`JUSTFORMS_REAL_IP_FROM`, `JUSTFORMS_REAL_IP_HEADER`) and sends it as the only hop; uvicorn's `FORWARDED_ALLOW_IPS` lists the same addresses (never `*`).

### 14.2 CAPTCHA (optional, per form)

There is a pluggable verifier interface:
- **ALTCHA** (self-hosted proof-of-work, no third party). This is the default when CAPTCHA is enabled, because it fits privacy-focused self-hosters.
- **Cloudflare Turnstile**.
- **hCaptcha**.

The CAPTCHA is verified server-side on submit and on OTP request. A form can choose `off`, `always`, or `auto`. With `auto`, the CAPTCHA turns on when the rate-limit soft threshold is hit.

The proof-of-work salt is `<random>?expires=<unix>&` (the trailing `&` ends it, as in the ALTCHA library) and the HMAC covers the challenge and the salt. The server refuses an expiry later than now + 30 minutes and a number above the maximum, and keeps the used-marker until the challenge expires. Siteverify answers must report the public host (`JUSTFORMS_PUBLIC_URL`) and, for Turnstile, the action `justforms`.

### 14.3 CSRF and CORS

- Staff APIs use the session cookie with `SameSite=Lax`. Every unsafe method also requires `X-CSRF-Token` matching the `justforms_csrf` cookie (double-submit), and the `Origin` header is checked against `JUSTFORMS_PUBLIC_URL`.
- Public endpoints use no cookies, take bearer respondent tokens, and need no CSRF. CORS is the same-origin default. Cross-origin embedding uses an iframe, not cross-origin XHR.

### 14.4 Content Security Policy

- Studio: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' <font-origin>` (Radix/Tailwind runtime styles), `font-src 'self' <font-origin>`, `img-src 'self' data: blob: <s3-origin>`, `connect-src 'self' <s3-origin>` (`<s3-origin>` only with the `s3` storage backend), `frame-ancestors 'none'`. `<font-origin>` is the origin of `JUSTFORMS_THAANA_FONT_CSS_URL` (e.g. `https://dvfonts.yashau.com`), added only when that URL is absolute; a self-hosted `/fonts/...` URL needs nothing extra.
- Public form: the same, except `frame-ancestors` is set per form from `settings.embedOrigins` (default `'self'`). nginx gets the value through an API-served header. The public bundle has no inline scripts.
- Form descriptions and content blocks are restricted Markdown (bold, italic, links, lists), rendered with a strict allowlist sanitiser. Raw HTML is never stored or rendered.

### 14.5 PII and data protection

- **Encryption.** Encryption at rest is the operator's responsibility (Postgres volume, the file storage volume, or S3 SSE). Application secrets such as webhook secrets and SMTP passwords are encrypted with Fernet using `JUSTFORMS_SECRET_KEY`.
- **Sensitive fields.** Shown as given to everyone who can see the submissions (viewers process the data; they just can't edit the form): lists, the submission page, Insights examples, exports and Ask lists, with a lock icon. Opening a submission that has sensitive answers is logged as a `viewed` event (fields only, at most once an hour per person). `POST /submissions/{id}/reveal` stays for API clients (viewers and above, logged). Excluded from search, email and webhooks; exports carry a warning banner.
- **Collection controls.** IP and user-agent capture can be disabled per form, except on signature forms, where they form part of the audit trail.
- **Retention.** `retentionDays` per form. A nightly job hard-deletes expired submissions together with their files, signatures and PDFs, and logs a tombstone in `audit_log`.
- **Deletion and the trash** (docs/ux/SUBMISSIONS-SORT-AND-TRASH.md). Deleting a submission or a form moves it to the trash (`deleted_at`, `deleted_by`): it disappears from lists, counts, Insights, Ask, exports, notifications, the public form and the verify page at once (the files of a deleted submission download for owners only, like the trash), and the studio shows an Undo toast. Items stay restorable for `JUSTFORMS_TRASH_DAYS` (default 30; Helm `trash.days`), then the nightly job (`nightly_cleanup`, `app/submissions/retention.py`) erases them for good with their stored objects (files, signatures, signed PDFs, imported copies; for a form also its logo, link previews, pending uploads, exports and import files) and leaves a tombstone in `audit_log` (`submission.erased`, `form.erased`, reason `deleted`). A form's retention period still applies to its submissions in the trash: when it runs out first, it wins, and the trash shows that earlier date ("Permanently deleted on …"). Owners can erase from the trash at once ("Delete permanently", typed confirmation; reason `owner`); `DELETE /submissions/{id}?hard=true` stays for API clients. Upgrading: forms deleted before the trash existed were never erased; they now are once they have been in the trash for the period, counted from their original deletion (check `forms.deleted_at` before upgrading if that matters).
  - *Submissions.* Delete appends a `deleted` event and restore a `restored` event to the hash-chained log (the content hash and the hashed columns are untouched), so the activity log shows both and still verifies. A restored submission keeps its reference number, answers, files, PDF, approval and verify link. Audit: `submission.delete`, `submission.restore`.
  - *Forms.* Deleting a form puts its submissions in the trash with it: they stay as they are (no per-submission event, the form's audit entry records it) and are hidden because the form is. Restoring the form brings back exactly those; submissions deleted on their own before stay in its Deleted tab. Erasing the form erases all of them. A restored form keeps its address unless another form took it meanwhile: then restore answers `409 slug_taken` with a free suggestion and the studio asks for a new address. Audit: `form.delete`, `form.restore` (with the new address when it changed), `form.erased`.
- **Logging.** Logs never contain submission data, OTP codes, tokens or secrets. structlog has a redaction processor for this.
- **Dependencies.** Pinned, with Renovate/Dependabot. Images are built non-root and distroless-ish (python-slim). Trivy runs in CI.

---

## 15. Submissions UI and export

### 15.1 Dashboard

- **Table view.** shadcn Table with server-side pagination and sorting. Unsorted lists page newest first by reference number (cursor = the last `seq`). `sort=<column>&dir=asc|desc` orders by `_seq`, `_submitted`, `_status`, `_approval`, `_respondent` or a top-level question key (files and signatures excluded); anything else is `422 invalid_sort`. Answers sort by type (`app/submissions/sort.py`): text with the ICU root collation when the database has it (Unicode order; Thaana in alphabet order), numbers and ratings numerically, dates and times as ISO text, choices by option order ("Other" after), multiple choice by the first chosen option, phones by digits, yes/no as No then Yes; empty answers last in both directions and the id as the tiebreaker. A sorted list pages by offset (the cursor is the next offset). The sort is in the URL, so Previous/Next on a submission and "Show these submissions" links keep it; exports keep oldest first unless asked for the table's order (`sort`/`dir` in the export filters). JSONB answers have no per-question index: the sort runs over the form's rows (filtered first), which is fine at the expected sizes.
  - Columns are chosen from the latest version's fields plus `#`, `status`, `submitted_at` and `respondent_email`. A column picker is persisted per user per form.
  - Filters: status, date range, form version, full-text search, and per-field filters (choice equals/in, number range, date range, yes/no, text contains). These compile to JSONB predicates against GIN-indexed `data`.
  - Bulk actions: change status, export selection, delete (owner only, Undo toast). Owners also get a **Deleted** tab (the form's trash) with restore and delete permanently (§14.5).
  - Filters, the status tab and the search live in the URL. The per-question filter (`filter=<json>`) is a list of `{field, op, value}` with `op` one of `contains`, `eq`, `neq`, `gte`, `lte`, `includes`, `answered`, `unanswered` (`app/submissions/query.py`); search runs over a `search_text` column holding the non-sensitive answers. Column choices are kept per user per form in the browser.
- **Detail view** (sheet or page). Answers are rendered with the **submission's own schema version**, in that form's language and direction. Files show inline previews for images and PDFs via presigned URLs. Signature images appear with their audit metadata. The detail view also shows the integrity badge (hash chain verified), the status control, the comment thread and the event timeline, plus buttons for Download PDF and Previous/Next within the current filter.
- **Status workflow.** `new → in_review → approved | rejected`. Any of these may be changed back to `in_review` by an editor or owner. A comment is required when moving to `rejected` and optional otherwise. Each change emits a `status_changed` event, a webhook and (optionally) an owner email. On forms with approvals, the approval sets the status while it runs (§15.3).

### 15.2 `.xlsx` export (worker, openpyxl `write_only=True`)

- **Sheet "Submissions".** One row per submission. Fixed columns are `#`, `Submitted at` (local TZ from `JUSTFORMS_TIMEZONE`, `UTC` by default), `Status`, `Version`, `Respondent email` and `Locale`.
  - One column follows for each field, across the **union of all versions**: fields are ordered by the latest version, and removed fields are appended at the end with "(version N)" after the label, N being the last version that asked them.
  - Header row is `Label (id)`, with labels in the form's language.
- **Value formatting.** Multi-choice values are joined with `; ` using option labels. Files are app download links, and signatures are a "Signed <timestamp>" link to the PDF.
- **Repeaters.** Each repeater gets its own sheet named after the repeater, with columns `Submission #`, `Row` and then its child fields.
- **Version field mappings.** When a newer version turns fixed questions ("Member 1 name", "Member 2 name"…) into a repeater, older submissions keep their version. `forms.settings["versionMappings"]` (`PATCH /forms/{id}` `versionMappings`, editors and owners; an empty list removes it) lists, per repeater, which older question fills each repeater question in row 1, 2…: `[{"repeater": "members", "rows": [{"member_name": "member1_name", "member_role": "member1_role"}, …]}]`. In the export, a submission whose version has no such repeater gets rows on the repeater's sheet read from those questions in order (a row whose questions are all empty is skipped), linked by its `#`, and the mapped questions get no columns on the Submissions sheet. Answers and hashes are never changed. Saving checks the mapping against the draft and the published versions (`bad_version_mapping` with the problems: not a repeater, a question not in the repeater, a source that is not a top-level question of a published version or is still on the form, anything mapped twice); malformed stored values are ignored. Code: `app/submissions/version_map.py`. The submission page and cards show each submission in its own version, so they need no mapping.
- **Thaana and RTL.** Cells are stored as text, and sheets are set to `rightToLeft` when the form's language is `dv`.
- **Formula injection.** Cells starting with `= + - @` are prefixed with `'`.
- **Implementation notes.** Headers use the form's own language (forms have one language, so there is no per-export language choice). Numbers and ratings stay numeric; everything else is text. A `Language` fixed column replaces `Locale`; `Respondent email` arrives with OTP access in Phase 4. Progress (`rowsDone` of `rowCount`) is reported while the worker writes in batches of 500.
- **Delivery.** The file goes to the storage backend at `exports/{id}.xlsx` with a 24 h expiry. The UI shows progress and offers a download, and an `exported` audit event is written. Exports up to 2000 rows are generated inline-fast, meaning the job still runs in the worker but the UI waits on it. Larger exports send a notification when ready.

### 15.3 Approvals (built)

Per form, optional ordered approval steps (1–3), set on the **Settings** page by owners. Each step has a name ("Supervisor", in the form's language) and an approver: the answer to a top-level email question, a fixed address, or **people with edit access, in the studio**. Decisions:

- **Where the settings live.** In `forms.settings["approvals"]`, not the form schema: the public form receives the schema, and fixed approver addresses must not reach respondents; changing an approver needs no publish. The steps are copied onto each submission when it arrives (`approval_steps`, approver addresses resolved then), so later changes never affect responses already in approval.
- **Checks.** On save and at publish. A step whose question is missing, isn't an email question or sits inside a repeater is an error: saving is refused and publishing is blocked (`approval_source_missing` / `approval_source_not_email`; the builder's publish dialog lists it with "Open settings"). An optional question, a question only some respondents see (a show-if on it, its section or its page, or an earlier page that can jump past it) and a question not published yet are warnings, shown on the step and in the publish confirmation.
- **Flow.** A response on a form with approvals becomes **In review** (`status_changed` with `via: "approval"`) and step 1's approver is emailed a link (`/a/{token}`: 192 random bits stored as SHA-256, valid `JUSTFORMS_APPROVAL_LINK_DAYS`, default 14). The email has **Approve** and **Reject** buttons, which are the same link with `?decision=approve|reject`: they only open the approver page with that decision chosen. Opening a link never changes anything (mail scanners prefetch links); the approver still confirms the address with the code, and the page then asks for one confirmation (name, and a comment to reject). The plain link stays in the email. The link is minted when the email is sent, so "Send the email again" replaces it. The approver confirms the address with a one-time code (the respondent code machinery keyed by the step: Redis HMAC, 10 minutes, 5 tries, rate limited) and gets a 2-hour bearer token bound to the step and the current link. Approve moves to the next step; reject (comment required) ends the approval. After the last step the status becomes **Approved** or **Rejected**, the PDF is made and signed again with the approval record, and, when turned on, the respondent gets the outcome by email (to the confirmed address or an email question) with that PDF attached, or without it if the PDF fails. A rejection's comment is in that email.
- **Steps decided in the studio** (decided). Approver type `editors`: the step has no approver address, no link (none is ever minted; every `/public/approvals/{token}` endpoint answers 404 for such a step) and no code. Only people with edit access to the form (editors, owners, organisation admins, superadmins), signed in, decide it through the studio's Approve / Reject (below). The step's optional **notify addresses** (up to 10, `notify`) and, with "Also email people with edit access" (`notifyEditors`, off by default), the form's editors, owners and organisation admins, resolved when the step is reached and kept in `approval_steps.notify_to`, get an `approval_notice` email: "New response to review: {title} ({reference})" (or the form's request subject), kicker "Waiting for a decision", the form's request message in place of the built-in sentence (then "Reference {ref}"), the non-sensitive answers when the request email includes them, an "Open in {product}" button to the submission page (sign-in required; the product name is `JUSTFORMS_BRAND_NAME` or JustForms) and "Sign in to approve or reject it. Only people with edit access to the form can decide." No Approve / Reject buttons. The `approval_requested` event carries `approvers: "editors"` and `notified`. "Send the email again" re-sends the notices; nothing is sent once the step is decided. The studio shows "Waiting for a decision by someone with edit access".
- **Respondent-chosen approvers** (security). A `field` step can list `allowedDomains` (exact domain match; empty = any domain). At submit, an approver answer outside them is refused (answer problem `approver_domain`, with the domains), and so is the respondent's own address (`approver_is_respondent`): the confirmed address (email code or staff sign-in) or any other email answer in the same response, compared case-insensitively and without a `+tag`. The step start repeats both checks; a refused address leaves the step waiting for staff. A `field` step without allowed domains gets the warning `approver_any_domain` (the approval isn't independent). Staff see the approver's full address; the verify page lists who decided each step, masked (`b•••@example.org`).
- **No approver.** If the answer with a step's address is empty when the step is reached, the step waits (`no_approver`, an `approval_waiting` event, "In progress" on the verify page) until staff decide it in the studio or stop the approval.
- **Deciding in the studio** (decided). Editors and owners of the form (so organisation admins and superadmins too) can approve or reject the current step from the submission page or, for several submissions, from the selection bar. It is that step's decision, recorded as the staff member (`decided_via = "studio"`, their user id and address on the step; the `approval_decided` event carries `decidedVia: "studio"`, `decidedByEmail` and the actor; audit entry `submission.approval_decide`), and the workflow moves on exactly as after a link decision: the next approver is emailed, or the final status is set, the PDF is made and signed again and the outcome email goes out. A rejection needs a comment; bulk rejections share one. The request names the step it decides (`{step}`), so a stale page can't decide a later step. The approver's link then shows "This approval is done" with who decided and when, and can't send codes or decide. Viewers can't decide.
- **Concurrency.** Every decision (link or studio) takes a row lock on the submission, re-reads the step and changes it with a conditional update (`WHERE state IN ('pending', 'no_approver')`); if nothing changed, the decision is refused with 409 `approval_done` (the studio's carries who decided, when and how). So when an approver and a staff member act at once, exactly one decision counts and the other person is told it was already decided.
- **Wording.** In the approval settings owners can set the request email's subject and message and list its non-sensitive answers, the approved and not-approved messages of the outcome email and the outcome's Reply-To address. Same placeholders and checks as the notification wording (§11.1); errors come back as issues with `field`. "Send test emails" (`POST /forms/{formId}/approvals/test`, owners, `notify_test` rate limit) sends the request (and/or, for steps decided in the studio, the "to review" notice) and both outcome emails with sample answers and "[Test]" to the person asking only; the test request's buttons open the submissions instead of an approver link.
- **What approvers see** (decided). An English page; the response in the form's language and direction with **sensitive answers hidden** ("Hidden"): approvers are outside the studio's roles, and sensitive answers never leave the app in emails or webhooks either. Non-sensitive files can be downloaded and signatures are shown; earlier steps' decisions are listed. The request email carries no answers.
- **Manual status** (decided). While an approval runs nobody sets the status by hand: `PATCH` returns 409 `approval_in_progress`, bulk status changes skip those submissions, and the studio's status control is disabled with "The status changes when the approval finishes." Editors can **send the approver's email again** or **stop the approval** (reason required; an `approval_stopped` event; the link stops working), after which the status is theirs again. Once an approval finishes or stops, the status works as before; later changes are logged but never edit the approval record.
- **Record.** Every step goes through the hash-chained event log (`approval_requested`, `approval_decided`, `approval_waiting`, `approval_stopped`) and the `submission.approval_step` webhook. The studio shows the steps in the detail sheet ("Approval"), "Step n of N" in the table and the events in the activity log.

### 15.4 Insights (built)

Submissions › Insights (docs/ux/INSIGHTS-SCREENS.md) summarises every question under the
list's filters (status, dates, version, question filters, conditions):
`GET /forms/{id}/insights` (viewers and above; `insights` rate limit, 120 an hour per person).
Every number comes from the submissions query language (§12.6), so Insights, the AI and the
filtered list count the same way, and every bar carries the conditions (`where`) that select
its submissions.

- Choices and yes/no: count and share per option (of the people who answered), "Other" with
  its 20 most common texts, "No answer". Options are merged across versions.
- Numbers and ratings: min, average, median, max, sum and a histogram (one bin per value for
  small integer ranges and ratings, otherwise up to 8 "nice" bins).
- Dates: per month, per year when the answers span more than three years.
- Text, email, phone: answered count and the newest three answers.
- Sensitive questions: answered count and the newest three answers, marked sensitive.
- Files and signatures: answered count.
- Repeaters: rows, submissions with rows, average rows, and the same summaries per row for
  their questions; mapped older questions count as rows. With a version filter only that
  version's questions (and mapped repeaters) are listed.

**List conditions.** `GET /forms/{id}/submissions`, Insights and exports take
`where=<json {where, whereAny}>` in the query language (people's policy: sensitive questions
answered/unanswered only); a condition that doesn't fit the form is a 422 `invalid_filter`
(checked before an export is queued). The studio keeps them in the URL with a label for the
chip.

---

## 16. Languages, RTL and Thaana

- **All system text is English only (decided, strict).** Every string JustForms itself writes is English, for every form: the studio, the public form's chrome (buttons, navigation, "Step 2 of 3", "(optional)", validation and error messages, file and signature controls, "Yes"/"No", the CAPTCHA, email-code and sign-in steps, success / closed / not-found screens), the approver and verify pages, every email (receipts, codes, approval requests, outcomes, staff notifications), the PDF's fixed labels (reference, submitted, the approval record, the footer "Digitally signed. Verify at") and the Excel export's fixed headers. There is no UI internationalisation, no translation bundle and no language switcher.
- **Dhivehi lives only in form content and answers.** The form builder writes the form title, description, page titles, question labels, help text, options, headings and paragraphs, the Back / Next / Submit button texts (`settings.backLabel`, `nextLabel`, `submitLabel`) and the success message; respondents write the answers. Those are in the form's language. When the builder leaves a button text or the success message empty, the English default is shown.
- **One language per form.** `settings.language` is `"en"` (default) or `"dv"` (§4.2). Every user-facing schema string (title, labels, descriptions, option labels, messages) is a plain string written in that language. There are no per-language translations; a bilingual paper form becomes one form in one language (or two forms).
- **Direction derives from the language.** `dv` → `rtl`, `en` → `ltr`; there is no separate direction setting. In the studio, every place that edits or shows form content (form title, field labels, options, the preview canvas) sets `lang`/`dir` from the form's language so Thaana typing and rendering are correct, while the surrounding UI stays English/LTR.
- **Where a page's direction comes from (decided).** A region takes the direction of what it mostly holds:
  - *The form sheet* (public form, studio preview, the PDF) is mostly questions and answers, so it follows the form: for `dv` the renderer sets `lang="dv" dir="rtl"` on the form root (Radix `DirectionProvider` too), lines start at the right and the layout mirrors. Every English string inside it is rendered through `<En>` (`renderer/msg.tsx`), a `<bdi dir="ltr" lang="en">` run: punctuation and numbers stay in place ("Step 2 of 3", "Enter a number between 1 and 5."), the Latin face is used, screen readers switch voice, and the run still sits at the start (right) edge of its RTL block. Plain-text slots that can't hold markup (an `<option>`, a placeholder) wrap the English in LRI…PDI (`ltrRun`). The date picker's calendar is English, so it is LTR. Error summary links isolate the (Dhivehi) question label and the (English) message separately.
  - *System-only screens* (the email-code gate, "already responded", closed / not found, the verify page, the approver page) are English and LTR. Form content shown on them (the form title, the approver's view of the questions and answers) is a block with the form's `lang`/`dir`.
  - *Emails* are English and LTR (`<html lang="en">`); the form title, the success message and the answers table carry the form's `lang`/`dir` (and `align` for clients that ignore `dir`), and content inside an English sentence (step name, form title) is a `<bdi>` with the form's language. Subjects are plain text ("Your response to {title} ({reference})").
  - *The PDF* follows the form like the sheet: in a `dv` PDF every line starts at the right; content is shaped right to left, and each English label line (reference and date, "Approval", "No answer", "Yes"/"No", the footer) is one left-to-right run placed against that edge.
- **Styling.** Components that display form content (renderer, preview, builder inputs for form text) use Tailwind **logical properties only** (`ms-*`, `me-*`, `ps-*`, `pe-*`, `start-*`, `end-*`, `text-start`). A lint script bans `ml-/mr-/pl-/pr-/left-/right-/text-left/text-right` in app code. Directional icons such as chevrons and arrows flip with `rtl:rotate-180`.
- **Fonts.** The Thaana font stack is `Faruma, "MV Faseyha", "Noto Sans Thaana", sans-serif` (Latin text uses Inter first). **Noto Sans Thaana** (SIL OFL) is bundled and self-hosted as woff2 and is always available as the fallback. Faruma and MV-series fonts are **not** shipped in the repo or images: their licence is unclear (listed as "Unspecified" on dvfonts). Faruma is loaded **at runtime** from a configurable stylesheet URL, `JUSTFORMS_THAANA_FONT_CSS_URL` (served to the SPA by `GET /meta` and to the public form with its schema):
  - Default: the public dvfonts CDN, `https://dvfonts.yashau.com/css2?family=Faruma&display=swap` (unicode-range subsets, so Latin pages download nothing). Trade-off: a third-party host then sees respondents' IP addresses and the page they load from.
  - Self-hosted: put the font files plus a CSS file with matching `@font-face` rules in a directory mounted at `/srv/fonts` in the web container (Compose: `deploy/compose/fonts/`, git-ignored; Helm: `frontend.fontsConfigMap`) and set the URL to e.g. `/fonts/faruma.css`. nginx serves them at `/fonts/`, and the SPA also always loads `/fonts/fonts.css` (an empty file in the image), so the older drop-in mechanism keeps working.
  - Empty: only fonts installed on the device and the bundled Noto Sans Thaana are used.
  - Server rendering (signed PDFs, link-preview images) can't use browser fonts: it uses the bundled Noto Sans Thaana unless the operator supplies a TTF/OTF with `JUSTFORMS_THAANA_FONT_FILE` (optional `_BOLD_FILE`; Helm `fonts.server.*`), shaped with HarfBuzz like the bundled face (`app/pdf/faces.py`). The file is checked once per process: it must cover U+0780 to U+07B0, and for PDFs its OS/2 `fsType` must allow subset embedding (images are rasterised, so embedding rules don't apply there). A failing file falls back to Noto Sans Thaana with one warning. The supplied face is used only for the characters Noto Sans Thaana covers, so Latin words in Dhivehi text keep the Latin face (the web rule, DESIGN-SYSTEM 4.1). Link-preview image versions include a hash of the font file, so cached images are remade when it changes.
  - Later, orgs may upload a licensed font in the admin UI (stored via the storage backend, referenced by `theme.thaanaFontFileId`).
- **Numerals and dates.** Western digits everywhere, because that is Maldivian practice in forms. Dates are system text: English month names ("1 January 2026") in messages, the date picker (an LTR calendar), emails and PDFs.
- **Phonetic Thaana keyboard** (`@yashau/thaana-react`, MIT, from dvfonts):
  - Applies to `short_text` and `long_text` with `inputScript: "thaana"`. With `"auto"` it is enabled when the form's language is `dv`. It ships with the public renderer in Phase 2. A small toggle (shadcn `Toggle`, label "ތ / A") lets the respondent switch per field.
  - The package's `attachKeyboard` / `useThaanaKeyboard` is attached to the **official shadcn `Input`/`Textarea`** (its own `<ThaanaInput>` components are not used: shadcn only). It maps Latin keystrokes to Thaana with the standard Divehi Phonetic layout (Microsoft kbddiv1: `h→ހ`, `S→ށ`, `n→ނ`, `r→ރ`, `b→ބ`, `L→ޅ`, `k→ކ`, `w→އ`, `a→ަ`, `A→ާ`, `i→ި`, `I→ީ`, `u→ު`, `U→ޫ`, `e→ެ`, `E→ޭ`, `o→ޮ`, `O→ޯ`, `q→ް`, ..., plus `,` → `،`, `;` → `؛`, `?` → `؟`). The public renderer loads it lazily (`src/thaana/phonetic.ts`).
  - The builder uses the same keyboard on every input that edits form text of a `dv` form (labels, help text, options, titles), with the same "ތ / A" toggle.
  - Display: form text shown in a `dv` form (labels, titles, options, help text) goes through the package's `isolateNumbers`, so numbers, phone numbers and percentages keep their order inside RTL text. System strings are English `<En>` runs (above), so they need no number isolation of their own.
  - Composition events (IME) and paste pass through unchanged. Cursor position and undo are preserved.
  - Unit tested with a keystroke → output table (`src/thaana/phonetic.test.ts`). Users who already have a system Thaana keyboard can turn the toggle off.
- **Validation messages.** The server returns error codes plus params; the public renderer turns them into English messages (`renderer/messages.ts`, one English set) for every form. A Dhivehi label is never put inside an English sentence ("Enter full name" becomes "Answer this question"); the builder's own `patternMessage` is content and is shown as written.

---

## 17. API surface (`/api/v1`)

All endpoints are JSON. OpenAPI is served at `/api/v1/openapi.json` (with `/api/docs`, `/api/redoc`) outside production, or with `JUSTFORMS_API_DOCS=true`, and the TS client for the studio is generated from it with `openapi-typescript`.

**Meta and auth**
- `GET /meta` — version and enabled features (`ai`, `oidc`, `captcha` providers)
- `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`, `GET /auth/me`
- `POST /auth/local/request`, `POST /auth/local/verify` — only when OIDC is disabled

**Orgs and members**
- `GET /orgs`, `POST /orgs`, `GET|PATCH /orgs/{orgId}`
- `GET|POST /orgs/{orgId}/members`, `PATCH|DELETE /orgs/{orgId}/members/{userId}` (last admin can't be demoted or removed; removal revokes form roles)
- `GET /orgs/{orgId}/people` (members with status, last sign-in and form count, plus pending invitations; admins)
- `POST /orgs/{orgId}/invitations` `{emails, role}`, `PATCH|DELETE /orgs/{orgId}/invitations/{id}`, `POST /orgs/{orgId}/invitations/{id}/resend`
- `GET /public/invitations/{token}` (status for the invitation page), `POST /invitations/{token}/accept` (signed in as the invited address)

**Forms (studio)**
- `GET /orgs/{orgId}/forms`, `POST /orgs/{orgId}/forms` (blank, from template, or from an import file)
- `GET|PATCH|DELETE /forms/{formId}` (settings, status, access mode; DELETE moves it to the trash)
- `GET /orgs/{orgId}/forms/trash` (deleted forms the person may restore, with `deletedBy`, `purgeAt`, `submissionCount`, `slugTaken`, `slugSuggestion`), `POST /forms/{formId}/restore` with `{slug?}` (owners; `409 {detail: "slug_taken", suggestion}` when the address was taken), `DELETE /forms/{formId}/permanent` (owners; erases a form in the trash now)
- `GET /forms/{formId}/draft` → `{schema, revision}`
- `PATCH /forms/{formId}/draft` with `{baseRevision, patch: RFC6902[]}`. Returns 409 on revision mismatch.
- `POST /forms/{formId}/draft/undo`, `POST /forms/{formId}/draft/redo`
- `GET /forms/{formId}/draft/changes` → what publishing would change against the live version
  (pages, sections and questions added/removed/moved, property changes before → after, versioned
  form settings; docs/ux/REVIEW-CHANGES-SCREENS.md)
- `POST /forms/{formId}/draft/discard` `{baseRevision}` → the draft reset to the live version as
  one undoable edit (owner/editor, audit `form.draft_discard`; 409 `never_published`)
- `POST /forms/{formId}/publish` → new version (validates, cycle check)
- `GET /forms/{formId}/versions`, `GET /forms/{formId}/versions/{n}`
- `POST /forms/{formId}/duplicate`
- `GET|PUT /forms/{formId}/permissions` (any role reads; owners replace the explicit grants with `{grants: [{email, role}], notify?, message?}`; only organisation members can be granted, org admins are listed as implicit owners; the response also lists `pending` invited access and `canInvite`), `POST /forms/{formId}/permissions/invite` (owner who is an org admin), `DELETE /forms/{formId}/permissions/invitations/{id}`
- `GET /forms/{formId}/notifications` (both rules, the email questions and the last 10 emails), `PUT /forms/{formId}/notifications/{owner_email|respondent_receipt}` (`{enabled, recipients, includeAnswers, attachPdf, emailField, toUnverified, unverifiedAnswers, subject, message, replyTo}`), `POST /forms/{formId}/notifications/test`
- `GET /forms/{formId}/approvals` (any role: settings, issues, email questions), `PUT /forms/{formId}/approvals` (owners)
- `GET|POST /forms/{formId}/webhooks` (non-owners get the URL masked to scheme and host), `PATCH|DELETE .../{id}`, `POST .../{id}/rotate-secret`, `POST .../{id}/test`, `GET .../{id}/deliveries?before=`, `POST .../{id}/deliveries/{deliveryId}/redeliver`
- `PATCH /forms/{formId}` also takes `accessMode`, `otpAllowedDomains`, `otpOneResponse`, `captcha` (`off|always|auto`), `retentionDays`, `saveProgress` and `saveProgressDays` (1-90). With `otpOneResponse`, a confirmed address submits once (409 `already_responded`); the submit checks again while it holds the form row lock, so concurrent submits with the same code can't both succeed. A form that has been published can't go back to `status: draft` (422 `cannot_return_to_draft`); a form whose status is `draft` is never served publicly.

**Submissions (studio)**
- `GET /forms/{formId}/submissions?status=&from=&to=&q=&version=&filter=<json>&where=<json>&cursor=&limit=&sort=&dir=`
- `GET /forms/{formId}/submissions/deleted?cursor=&limit=` (owners): the trash, most recently deleted first, with `deletedAt`, `deletedBy`, `purgeAt`
- `GET /forms/{formId}/insights?status=&from=&to=&q=&version=&filter=&where=` — per-question summaries (§15.4)
- `GET /forms/{formId}/ask` (the person's chat, `readAnswers`, `providerLabel`), `POST /forms/{formId}/ask/sessions` with `{fresh?}`, `POST /forms/{formId}/ask/sessions/{id}/messages` with `{content}` (SSE), `POST /forms/{formId}/ask/sessions/{id}/cancel` — "Ask your submissions" (§12.6; viewers and above; 404 without an AI provider)
- `GET /forms/{formId}/submissions/stats` — counts by status, `all` and `deleted`
- `GET /submissions/{id}` — includes its schema version, events, files and signatures
- `PATCH /submissions/{id}` with `{status, comment?}`
- `POST /submissions/{id}/comments` (viewers too; plain text, part of the hash-chained activity log)
- `POST /submissions/{id}/reveal` with `{fieldId, row?}` (viewers and above; logged; the studio no longer needs it)
- `GET /signatures/{id}/image`
- `POST /pdf-checks` (raw PDF body) → verdict, signer and the submission's current hash
- `GET /submissions/{id}/pdf` (302 presigned; triggers generation if missing → 202)
- `GET /submissions/{id}/verify` — hash and chain check
- `POST /submissions/{id}/approval/resend`, `POST /submissions/{id}/approval/stop` with `{reason}` (editors)
- `POST /submissions/{id}/approval/decide` with `{step, decision: approve|reject, comment}` (editors; 409 `{code: "approval_done", state, decidedName, decidedAt, decidedVia}` when the step was decided first)
- `POST /forms/{formId}/submissions/approval/decide` with `{items: [{id, step}], decision, comment}` (editors) → a result per submission: `approved`, `rejected`, `already_decided` (with `decidedName`) or `not_found`
- `POST /forms/{formId}/approvals/test` (owners): test approval emails to the person asking
- `DELETE /submissions/{id}` (to the trash; `?hard=true` erases now), `POST /submissions/{id}/restore` (owners)
- `POST /forms/{formId}/submissions/bulk` with `{ids, action: status|delete|restore|purge}` (restore and purge act on the trash; owners)
- `POST /forms/{formId}/exports` with `{format: "xlsx", filters}`; `GET /exports/{id}`
- `GET /files/{fileId}` (302 presigned)

**Public (respondent; no cookies)**
- `GET /public/forms/{slug}` → live version schema, settings, upload nonce, captcha config. Returns 410 if closed. (Slugs are unique across the install; the public page is `/{slug}`.)
- `POST /public/forms/{...}/otp/request`, `POST /public/forms/{...}/otp/verify`; for email-code forms the form `GET` returns the title and language but `schema: null` until a respondent token is sent
- `GET /public/forms/{...}/captcha` (fresh proof-of-work challenge), `GET /public/frame-ancestors` (used by nginx for the per-form CSP and the link-preview tags, §18.4)
- `POST /public/forms/{...}/uploads`
- `POST /public/forms/{...}/submissions` with `{versionId, data, signatures, uploadNonce, captchaToken?}` → `{seq, receiptAvailable}`. A 409 is returned if the live version changed mid-fill, and the client re-fetches and re-validates while keeping compatible answers.

**Document pages (public; no cookies)**
- `GET /public/verify/{token}`, `POST /public/verify/{token}/check` (raw PDF), §9.5.2
- `GET /public/approvals/{token}`, `POST .../code`, `POST .../verify` with `{code}` → bearer token, `GET .../submission`, `GET .../files/{fileId}`, `GET .../signatures/{fieldId}`, `POST .../decision` with `{decision: approve|reject, name, comment}`, §15.3

**Addresses, appearance and form themes** (§18.3)
- `GET /forms/slug-check?slug=&formId=` → `{available, problem: invalid|reserved|taken, suggestion, url}` (`taken` includes other forms' earlier addresses; invalid input such as Thaana is suggested romanised)
- `PATCH /auth/me` with `{appearance}`
- `GET|PUT /orgs/{orgId}/form-theme` (members read, admins change), `GET|PUT /forms/{formId}/theme` (viewers read, editors change), `POST /themes/preview` (unsaved values → tokens, fonts, options, adjustments), `PUT /orgs/{orgId}/theme-images` (raw PNG/JPEG/WebP body)
- Public: `GET /public/forms/{slug}/theme.css`, `GET /public/theme-images/{orgId}/{ref}`

**Link previews** (§18.4)
- `GET|PUT /forms/{formId}/sharing` (viewers read, editors change: `{title, description}`), `PUT|DELETE /forms/{formId}/sharing/image` (raw PNG/JPEG/WebP body), `GET /forms/{formId}/sharing/image?v=` (current image for the studio)
- Public: `GET /public/forms/{slug}/og.png?v=` (`og.jpg` for an uploaded image), `GET /public/og/site.png?v=`; the page tags travel in `X-JustForms-Head` on `GET /public/frame-ancestors`

**AI (studio; feature-flagged)**
- `POST /forms/{formId}/ai/sessions` with `{fresh?}`: the person's current chat on the form (or a new one); `GET /forms/{formId}/ai/sessions/{id}` (transcript and suggestion)
- `POST /forms/{formId}/ai/sessions/{id}/messages` with `{content}` (SSE stream)
- `POST /forms/{formId}/ai/sessions/{id}/import?blankConfirmed=true&name=` (raw PDF/JPEG/PNG/WebP body; SSE stream)
- `POST /forms/{formId}/ai/sessions/{id}/cancel` (stop the running request)
- `POST /forms/{formId}/ai/sessions/{id}/apply` with `{baseRevision}` → `{draft, session}`, 409 `proposal_stale`; `POST /forms/{formId}/ai/sessions/{id}/discard`

**Imports (studio):** Jotform HTML, API and submission-file endpoints, listed in §13.5.

**Ops:** `GET /healthz` (liveness), `GET /readyz` (DB, Redis and file storage checks), `GET /metrics` (Prometheus, on a separate port).

---

## 18. Frontend

**`apps/studio`**
- Built with TanStack Router (file-based routes) and TanStack Query.
- Main routes: forms list, builder (`/forms/$id/edit`), logic view, share/embed, submissions table/detail, settings (notifications, webhooks, permissions), org admin.
- **Builder.**
  - A three-pane layout of field palette, canvas and inspector, made from shadcn `ResizablePanelGroup`, `Sheet`, `Tabs`, `Form`, `Select`/`NativeSelect`, `Switch`, `Command` and the other official components.
  - Drag and drop uses dnd-kit (`@dnd-kit/core` + `sortable`) for palette → canvas, reordering, and moving between sections and repeaters. Keyboard sorting comes along for accessibility.
  - State is the draft schema in a Zustand store with local undo. Edits become RFC 6902 patches, which are autosaved (debounced 800 ms) with `baseRevision`.
  - **Inline editing** ([ux/INLINE-EDIT-AND-LOGO-SCREENS.md](ux/INLINE-EDIT-AND-LOGO-SCREENS.md) §1). Every piece of form text on the canvas is edited in place: title and description, page titles and descriptions, labels, help text, placeholders, options (Enter adds the next one, Backspace on an empty one removes it, Alt+↑/↓ or the grip reorders, "Add "Other""), headings, paragraphs, section and repeater texts, the Back / Next / Submit buttons and the message after submitting. Idle text is the renderer's own output inside a focusable `role="button"` ("Edit question label: …"); a click, tap, Enter or F2 swaps in the official `Input`/`Textarea` (with the phonetic keyboard and "ތ / A" toggle in dv forms) in the text's typography (`components/builder/inline-text.tsx`). Which text is open is `editing` in the builder store (keys from `textKey`, `inline-edit.ts`); Enter or blur commits once through `store.edit` (one undo step, one autosave patch, the server's schema validation), Esc cancels, Shift+Enter is a line break. Prompts for empty optional texts show only on the selected block. The public renderer only gained override slots (`QuestionView` `description`/`control`, `SectionFrame`/`RepeaterFrame` `description`/`addText`, `FormHeader` `title`/`description`), so the editor stays out of the public chunk.
  - The preview tab mounts `packages/renderer` with the draft.
- **Logic editor.** A condition builder (field → operator → value) built from shadcn `Select`/`Input`/`Button`, with `all`/`any` grouping one level deep in the UI. Deeper nesting is possible via AI or JSON but is shown read-only.
- **AI panel.** A chat in a `Sheet`. It streams messages, shows tool-call steps, and renders the proposal as a structured diff (added, changed and removed elements highlighted on the canvas) with Apply/Discard buttons.

**`apps/form` (public)**
- Contains `packages/renderer` and `packages/logic` with react-hook-form and zod. There is no TanStack Router or Query, a single route parsed from `location`, and the shadcn components it needs.
- Budget: **≤ 120 KB gzipped JS** for the initial load. The signature pad and phonetic keyboard are lazy-loaded chunks.
- **Saved progress** ([ux/SAVED-PROGRESS-SCREENS.md](ux/SAVED-PROGRESS-SCREENS.md)). Answers and the current page are kept in `localStorage` (debounced 500 ms, flushed on page change and when the page is hidden), keyed by form and, on email-code and staff forms, a hash of the respondent's email. Sensitive questions, signatures, files (upload references belong to one page load's upload session, §10) and hidden values are never stored. On reopening the form restores them (only answers whose question and type still exist when the version changed) with a polite notice and Start over; submit clears them. The per-form setting (`saveProgress`, `saveProgressDays`, default on and 7 days) comes with the public form as `saveProgress: {days} | null`. The code is a lazy chunk fetched in parallel with the form; storage errors are ignored.
- Serves `/{slug}` and an `?embed=1` mode with transparent background, plus a `postMessage` height-resize protocol for iframe embeds. Old `/f/{org}/{slug}` links get a 301 to `/{slug}`; any other unknown path shows the public "couldn't find this form" screen with a 404. Slugs are unique across the install and may not be one of the app's own top-level words (`app/services/slugs.py`, `frontend/nginx.conf`).

**Document pages (`doc.html`)**
- `/v/{token}` (verify, §9.5.2) and `/a/{token}` (approver, §15.3, a lazy chunk). A separate Vite build (`vite.doc.config.ts`) so it never changes the public form's chunks; 95 KB gzip budget for the initial load (`pnpm check:bundle` checks both pages). nginx sends `Referrer-Policy: no-referrer` and `frame-ancestors 'none'` for them.

**Renderer.**
- Builds a zod schema dynamically from the version schema and the current logic evaluation, so hidden fields are dropped and required fields come from `required ∪ requiredIf`.
- Wizard pages follow the evaluated `path`. The progress indicator uses shadcn `Progress`.
- Per-page validation runs on "Next".

### 18.1 UI conventions (binding)

- **Official shadcn/ui only.** Every UI component comes from the official shadcn/ui registry and is added with the shadcn CLI (`pnpm dlx shadcn@latest add <component>`) into `frontend/packages/ui`. Updates are pulled the same way.
- **Never hand-roll shadcn-style components.** Nobody writes their own Button, Dialog, Select, Table, Combobox, DatePicker, etc., or copies look-alike markup. No third-party component kits such as MUI, Mantine or Chakra are used either.
- **If shadcn has no such component, compose one from official components.** Examples:
  - the condition builder is `Select` + `Input` + `Button` + `Card`;
  - the column-mapping step is `Table` + `Select`;
  - the import report is `Table` + `Badge` + `Alert`;
  - the signature pad is `Card` + `Button` around a bare `<canvas>`;
  - the phonetic keyboard is a `beforeinput` behaviour on the official `Input`/`Textarea` plus a `Toggle`.

  Only the minimal unstyled behavioural element (canvas, input handler) is custom.
- **Code review rule.** Any new file under `packages/ui/components` that did not come from the shadcn CLI is rejected in review. CI diffs `packages/ui/components` against `pnpm dlx shadcn@latest diff` to catch drift.
- pnpm is the package manager, pinned through the `packageManager` field and provisioned with corepack. Do not use npm or yarn.
- **Touch screens.** On `pointer: coarse` every studio control is at least 44×44px (rules in
  `index.css`, matched by `data-slot`/`data-size`, so generated components stay untouched).
  `just mobile-audit` checks every screen on real phone emulation (DESIGN-SYSTEM §6,
  REVIEW-CHECKLIST).

### 18.2 Branding (white-label)

Screens and copy: [ux/BRANDING-SCREENS.md](ux/BRANDING-SCREENS.md).

- **Where it lives.** `organizations.settings["branding"]`: display name, primary colour,
  support link, hide-"Powered by" flag and image refs (`logo`, `logo_dark`, `icon`: storage
  key, type, SHA-256, size). No migration: the JSONB column already exists. Images go through
  `app.storage` under `branding/{org_id}/{kind}-{sha}.{ext}`; the old object is deleted when
  replaced.
- **Resolution** (`app/branding/service.py`): organisation value, else the instance default
  (`JUSTFORMS_BRAND_NAME`, `_PRIMARY_COLOR`, `_SUPPORT_URL`, `_LOGO_FILE`, `_LOGO_DARK_FILE`,
  `_ICON_FILE`, `_POWERED_BY`), else JustForms. The display name falls back to the instance name,
  then the organisation's name. `JUSTFORMS_BRAND_POWERED_BY=always` stops organisations hiding
  "Powered by JustForms". Pages without an organisation (sign-in) use the default organisation
  through the pseudo-slug `_`.
- **Images** (`app/branding/images.py`): PNG (decoded and re-encoded with Pillow, ≤ 4096 px)
  or SVG (parsed with defusedxml, rebuilt from an allow-list; scripts, handlers, `<style>`,
  `foreignObject`, `<image>`, external `href`/`url()` are refused), ≤ 512 KB; the icon must be
  square. Served from the app's origin (`/api/v1/public/branding/{slug}/{kind}?v={sha}`) with
  `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`, `nosniff`,
  `Cross-Origin-Resource-Policy: cross-origin` (mail clients show the logo) and a year's cache
  for the versioned URL. CSP of
  the pages is unchanged (`img-src 'self'`).
- **Colour** (`app/branding/colors.py`): one `#RRGGBB` becomes light and dark values of
  `--primary`, `--primary-foreground`, `--ring`, `--sidebar-primary*`, `--chart-1`, darkened or
  lightened until the primary reads at 4.5:1 on sheet and desk and its label at 4.5:1 on it.
  The API reports when it adjusted. Served as `/api/v1/public/branding/{slug}/theme.css`; a
  form's own accent still overrides the primary inside that form.
- **Pages.** `frontend/src/lib/branding.ts` links the theme stylesheet (the public form does it
  from the URL before the form loads), swaps favicon/apple-touch icon and the manifest
  (`/api/v1/public/branding/{slug}/manifest.webmanifest`) and titles the tab. Before any script
  runs, the fixed `/favicon.ico`, `/favicon.svg`, `/apple-touch-icon.png`, `/manifest.webmanifest`
  and `/form.webmanifest` the HTML links already carry the default organisation's icon and
  manifest: nginx proxies them to `/api/v1/public/site/{name}` (5-minute cache, then ETag
  revalidation) and serves the bundled JustForms files when that answers 404 (no icon or no
  branding) or fails. Public form,
  approver and verify responses carry `brand`; the studio reads `/public/branding/{slug}` for
  the user's organisation. Logo above the form title, "Get help" and "Powered by JustForms" under
  the sheet (`components/brand/brand-parts.tsx`); embedded forms skip both.
- **Emails** carry `From: "{name}" <address of JUSTFORMS_SMTP_FROM>`, a PNG logo (an SVG-only
  logo shows the name as text: mail clients don't render SVG), the brand colour on buttons and
  a footer with the support link and "Powered by JustForms". **PDFs** print the logo (PNG or SVG)
  above the title and the name in the footer line when the organisation is branded. **Excel
  exports** set the workbook creator and description to the name.
- **Settings.** `/settings` (account menu › "Organisation settings"); organisation admins and
  superadmins edit, members read. API: `GET/PUT /orgs/{id}/branding`,
  `PUT/DELETE /orgs/{id}/branding/images/{kind}` (raw body), `GET /branding/palette?color=`.

### 18.3 Form addresses, appearance and form themes

Screens and copy: [ux/FORM-THEME-SCREENS.md](ux/FORM-THEME-SCREENS.md).

- **Addresses.** `forms.slug` is unique across the install among forms not deleted (partial
  unique index; migration 0010 suffixed collisions and reserved words). `app/services/slugs.py`
  holds the reserved list (studio routes, API, static paths, document pages); nginx and the Vite
  dev server route `/{slug}` to the public form entry, `/f/{org}/{slug}` to a 301, and any other
  unknown path to the public not-found screen with a 404 (a well-formed but unknown address shows
  the same screen from the SPA). Forms carry `url`; webhooks send `form.url`; exports set it as the
  workbook identifier.
- **Addresses from titles.** `slugs.slugify`: a title with Thaana is romanised first by the
  official rules of 23 May 1977 (`app/text/thaana_latin.py`, ported from the MIT-licensed
  `dhivehi-rules` package; §1 to §6, without §6's proper-noun capitals or §8's English spellings),
  then apostrophes are dropped (§5 `kan'di` -> `kandi`, `ޢ`), accents folded (NFKD -> ASCII),
  lower-cased, every other run of characters becomes a hyphen, and the result is cut to 60
  characters at the last hyphen (a hard cut when that would lose more than two thirds). Latin
  parts of mixed titles pass through unchanged, so `Youth programme ޒުވާނުންގެ ޕްރޮގްރާމް 2026` is
  `youth-programme-zuvaanunge-prograam-2026`. Nothing left gives `form`. Reserved words and
  addresses in use (aliases included) get `-2`, `-3`... (`unique_slug`). The studio's live
  suggestion is the twin `titleSlug` in `frontend/src/thaana/latin.ts`; both run
  `spec/slugs/thaana-latin.json` (the rule booklet's 68 examples plus sentences) and
  `spec/slugs/slugs.json` (title -> address). It is used for new forms, duplicates
  (`<title> (copy)`), Jotform imports, the slug check's suggestion for invalid input (Thaana typed
  into the address field) and, before the first publish, for a form still at a generic address
  (`form`, `form-N`) whose title is written later in the builder or by the AI assistant
  (`slugs.follow_title`). Published forms never change address by themselves.
- **Earlier addresses.** When a published form's address changes, the old one is stored in
  `form_slug_aliases` (migration 0024; unique `slug`, `form_id` cascading). An alias is reserved
  like a live address (`slugs.taken`, so the slug check, create, rename and restore refuse it for
  other forms) for as long as its form exists, the trash included; erasing the form (owner or the
  nightly trash purge) frees it. The form itself can take an alias back, which removes it.
  Restoring a form at a new address because its old one was taken keeps no alias. Address changes
  before the first publish keep none either (there was no link). Requests to an alias of a form
  that is not in the trash: the page `/{alias}` (and `?embed=1`; the query is kept) gets a 301 to
  `/{slug}`: `GET /public/frame-ancestors` answers `401` with `X-JustForms-Moved: <slug>` and nginx
  turns it into the redirect (`@public_form_moved`). `GET /public/forms/{alias}` and
  `/public/forms/{alias}/og.png|og.jpg` answer 301 to the same path under the current slug; the
  theme stylesheet and the respondent's POSTs (OTP, uploads, submissions) resolve the alias in
  place, so a page opened before the change still submits. Redirects carry `Cache-Control:
  no-cache` because the owner may take the old address back. `FormOut.previousSlugs` lists the
  aliases (the Share page shows them). Existing forms are never renamed automatically; the Share
  page offers a Dhivehi form (Thaana in its title) still at a generic address a one-click
  "Use /<romanised>" (the API's free variant when it is taken).
- **Appearance.** `users.appearance` (migration 0011). `/appearance.js` (same origin, blocking,
  in `index.html`) applies the cached choice from `localStorage` before the first paint; the
  account value wins once `/auth/me` loads. Public form, approver and verify pages never read it:
  they are light unless the form's theme says dark or "match device"
  (`lib/color-scheme.ts`, remembered per form address to avoid a flash).
- **Form themes.** `app/schemas/theme.py` (`FormTheme`, every value optional = inherit) stored in
  `organizations.settings["formTheme"]` and `forms.settings["theme"]` (not the versioned schema:
  appearance applies on save). `app/theme/resolve.py` merges form over organisation over JustForms
  (the brand colour and the schema's legacy `settings.theme.accent` count as primaries).
  `app/theme/colors.py` checks text, muted text, primary and error at 4.5:1 on sheet and page
  background, input outlines at 3:1, the primary's label at 4.5:1, generates dark values from the
  same hues and reports every adjustment. Output: a stylesheet (`@import`s of the chosen fonts,
  `:root` and `.dark` variables) linked by public pages before load and through `brand.themeUrl`;
  `brand.theme` options become `data-df-*` attributes that `index.css` styles (button, input,
  heading scale, background image), so `components/ui` is untouched. The studio canvas, preview
  route and settings previews apply the same tokens inline (`lib/theme.ts`); `.light` forces light
  inside a dark studio.
- **Fonts.** Latin: Inter (bundled, the default), Atkinson Hyperlegible Next, IBM Plex Sans,
  Source Serif 4, Noto Sans, built by `frontend/theme-fonts.ts` from the OFL @fontsource packages into
  `/theme-fonts/{id}.css` + hashed woff2 (Latin and Latin Extended), loaded only when a theme uses
  one, so the public JavaScript budget is unchanged. Thaana: `JUSTFORMS_THAANA_FONTS`, each a
  css2-style URL on the configured font service (its origin is already in the CSP), Noto Sans
  Thaana always offered.
- **Images.** PNG/JPEG/WebP ≤ 2 MB and 4096 px, re-encoded to WebP by Pillow (metadata dropped),
  stored through `app.storage` at `theme/{org_id}/{sha16}.webp`, served same-origin with a sandbox
  CSP and a year's cache (`img-src 'self'` unchanged).
- **Emails and PDFs.** Emails about a form colour their button with its primary; signed PDFs use
  it for the title rule and page headings only (fonts stay the embedded OFL faces).
- **Logo per form** ([ux/INLINE-EDIT-AND-LOGO-SCREENS.md](ux/INLINE-EDIT-AND-LOGO-SCREENS.md) §2).
  The form theme gains `logoSize` (`s`/`m`/`l`: 24, 32, 56 px; PDF 7, 9, 13 mm), `logoPlacement`
  `end` (logical: start/end flip in dv forms and PDFs) and `logoLink` (absolute `http(s)` URL,
  ≤ 500 characters), inherited like every theme value. The file itself is per form only:
  `PUT/DELETE /forms/{id}/logo` (raw body, editors; same checks as branding logos: PNG decoded
  and re-encoded, SVG rebuilt from the allow-list, ≤ 512 KB, ≤ 4096 px) stores
  `forms.settings["logo"]` and the object at `form-logos/{form_id}/{sha16}.{png|svg}` through
  `app.storage`; it is served at `/api/v1/public/form-logos/{form_id}/{name}` with the branding
  image headers and a year's cache. `app/theme/logo.py` resolves it: the theme options carry the
  effective `logoUrl`/`logoDarkUrl` (the form's, else the organisation's) and `logoOwn`, so the
  public form, the approver and verify pages (`page_brand`), the builder canvas and the previews
  show it; form emails use a PNG form logo (an SVG falls back to the organisation's email
  header); signed PDFs print it at the chosen size and position (Hidden prints none). Duplicated
  forms don't copy it; a stored key that isn't under the form's own id is ignored.

### 18.4 Link previews (Open Graph)

Screens, layout and copy: [ux/SHARING-PREVIEW-SCREENS.md](ux/SHARING-PREVIEW-SCREENS.md).

- **Page tags.** Crawlers don't run scripts, so the public form page's HTML carries the title,
  description, canonical link, Open Graph (`og:type/site_name/title/description/url/locale/image`
  with type, size and alt) and `twitter:card=summary_large_image` tags. nginx already asks
  `GET /public/frame-ancestors` for every `/{slug}` page; the answer also carries the tags in
  `X-JustForms-Head` (`app/sharing/meta.py`: HTML-escaped, non-ASCII as character references,
  so one ASCII header line), and `sub_filter` puts them in place of the placeholder
  `<title>Form</title>`. No header: the placeholder stays; the API unreachable: the plain page
  (`error_page` fallback). Unknown, unpublished and archived addresses get the site's tags only
  (default organisation's name and card), nothing about the form. Studio pages are unchanged.
- **Image** (`app/sharing/image.py`). 1200 × 630 PNG drawn with fpdf2 + HarfBuzz like the signed
  PDFs and rasterised with pdfium (Pillow has no raqm/FriBiDi in slim images): logo and
  organisation name, the title at the largest size that fits three lines, up to two lines of
  description, the address, a band in the theme's primary colour; mirrored and shaped right to
  left for dv forms (Noto Sans Thaana; Latin always Inter). Colours are the
  form theme's light values.
- **Cache** (`app/sharing/service.py`). `version` hashes everything drawn; the file lives at
  `og/{form_id}/{version}.png` in `app.storage`, made on first request and the previous one
  deleted, so publishing, branding, theme and share-text changes give a new image at a new URL.
  `GET /public/forms/{slug}/og.png?v=` (and `og.jpg` for uploads) answers with a year's
  immutable cache for the current version, otherwise 5 minutes, an `ETag`/304,
  `Cross-Origin-Resource-Policy: cross-origin` and a sandbox CSP.
- **Overrides.** `forms.settings["sharing"]` (no migration): share title (≤ 120) and description
  (≤ 300), and an uploaded image (PNG/JPEG/WebP ≤ 5 MB, decoded, centre-cropped to 1.91:1, scaled
  to ≤ 1200 × 630, re-encoded as JPEG under ~300 KB, stored at
  `og/{form_id}/custom-{sha16}.jpg`). Viewers read, editors change, in form Settings › Sharing
  preview, with a live link-card preview. Not copied by Duplicate.

---

## 19. Deployment

### 19.1 Docker Compose (`deploy/compose`)

- **Services:** `web` (nginx + static builds), `api`, `worker`, `migrate` (one-shot, `alembic upgrade head`), `postgres:17`, `redis:7`. No object store is bundled: files go to the `storage-data` named volume mounted into `api` and `worker` (`local` backend), or to an external S3-compatible service when the `JUSTFORMS_S3_*` values are set. An optional `fonts/` directory is mounted read-only into `web` for operator-supplied fonts.
- **Profiles:** `mailpit` under the `dev` profile (catches sign-in codes, notifications and receipts), `clamav` later.
- **Web container:** nginx resolves `BACKEND_URL` at request time (`resolver` from `/etc/resolv.conf`, `valid=10s`), so a recreated backend container with a new address does not cause 502s; on Kubernetes the URL is the fully qualified service name. The CSP is built at start from `JUSTFORMS_THAANA_FONT_CSS_URL`, `JUSTFORMS_CAPTCHA_PROVIDER` and `JUSTFORMS_CSP_EXTRA_CONNECT_SRC`.
- **Setup:** a single `.env.example`. `just compose-up` or `docker compose up -d` brings it up, and the first admin is created with `docker compose run --rm api justforms create-admin --email you@example.org`.
- **Images:** `ghcr.io/alee-ibrahim/justforms-backend` (API, worker and migrations; the worker runs `arq app.worker.WorkerSettings`) and `ghcr.io/alee-ibrahim/justforms-frontend`, published by `.github/workflows/release.yml` for each `vX.Y.Z` tag. Both are multi-arch (amd64 and arm64), signed with cosign (keyless) and carry SLSA provenance and SPDX SBOM attestations; the Helm chart is published next to them as `oci://ghcr.io/alee-ibrahim/charts/justforms`. `docker-compose.release.yml` runs the stack from these images.

### 19.2 Helm (`deploy/helm/justforms`)

- **Workloads:** Deployments for `api`, `worker` and `web`; a Service plus Ingress (or Gateway API HTTPRoute, selectable); HPA for api, worker and web; PodDisruptionBudgets; and a migration Job as a `pre-install,pre-upgrade` hook.
- **Backing services:** Postgres and Redis are **external by default**, configured through values (`postgres.url`/`existingSecret`, `redis.url`). An optional `bundled.redis` exists for quick starts. No bundled Postgres ships in the chart, so operators bring their own.
- **File storage:** `storage.backend: local` (default) creates a PVC (`storage.local.persistence`: size, storageClass, accessModes, or `existingClaim`; kept on uninstall) mounted into `api` and `worker`, with `fsGroup` set so the non-root user can write. With ReadWriteOnce the worker is pinned to the backend's node and the backend uses the `Recreate` strategy; use ReadWriteMany or `s3` to scale across nodes. `storage.backend: s3` takes `storage.s3.endpointUrl/bucket/region/addressingStyle` plus `storage.s3.existingSecret` for the keys. No object store is bundled.
- **Secrets** are referenced through `existingSecret` names only: app secret key, OIDC client secret, SMTP, S3 keys (when used), AI key, PDF signing P12 and webhook encryption key. The chart never renders secret values.
- **Hardening:** securityContext runs as non-root with a read-only root filesystem (tmp via emptyDir) and drops all capabilities. NetworkPolicy templates are optional.
- **Observability:** a ServiceMonitor (optional) and liveness/readiness probes on `/healthz` and `/readyz`.

### 19.3 Example: GitOps deployment on Kubernetes (not product code)

A typical production setup, for orientation only:

- A GitOps controller deploys the chart, with the values file kept in a GitOps repository.
- Secrets live in a secrets manager and are synced into the `existingSecret` names above by an external secrets operator, never created by hand.
- OIDC points at the organisation's IdP, with group → org role mapping.
- `JUSTFORMS_TIMEZONE` is set for the installation's locale.
- Error tracking can use any Sentry-compatible service through `JUSTFORMS_SENTRY_DSN` (the SDK is optional and generic).
- An organisation moving from another forms tool recreates the forms it still needs; JustForms ships no importer other than Jotform (§13).

---

## 20. v1 milestones

### Phase 1: Foundations
Repo, CI (ruff, mypy, pytest, eslint, tsc, vitest), Compose stack, app config, DB models and Alembic baseline, orgs/users, OIDC login and local-OTP fallback, sessions and CSRF, permission resolver. Form schema Pydantic models, JSON Schema export and TS/zod generation. **Logic engine in Python and TS plus the conformance suite.**
**Acceptance:**
- `docker compose up` produces a working login via Keycloak (in dev compose) and via local OTP.
- `spec/form-schema.v1.json` is generated and checked in CI.
- At least 150 logic vectors pass identically in pytest and vitest.
- The cycle detector rejects all cyclic fixtures.

### Phase 2: Builder and renderer
Studio builder (dnd-kit, all v1 field types except signature, sections, repeaters, pages), inspector, logic editor, draft autosave with patches/revisions, server undo/redo, publish/versions. Public form app with wizard, logic, client validation, English and Dhivehi (RTL) forms, Thaana fonts and phonetic keyboard. Embed mode.
**Acceptance:**
- The §4.4 example (minus signatures) can be built entirely in the UI as a `dv` form, published, and rendered RTL with Thaana; an `en` form renders LTR.
- Hiding, requiring and skipping behave as the vectors specify.
- The public bundle is ≤ 120 KB gzip.
- The phonetic keyboard passes its mapping tests.
- No physical-direction Tailwind classes remain (lint passes).

### Phase 3: Submissions core
Public submit endpoint with server validation (logic plus stripping), presigned uploads with sniffing and attach, submissions table with filters and search, detail view, status workflow and comments, event hash chain, per-form roles UI, `.xlsx` export with repeater sheets, retention job.
**Acceptance:**
- A tampered client that sends hidden or invalid fields is rejected or stripped server-side, as shown by tests.
- Viewers cannot change status (API tests for every role × endpoint).
- An export of 10k submissions with repeaters opens in Excel, and Thaana renders RTL.
- Upload size and type limits are enforced at upload (presigned POST policy on `s3`, streamed byte count on `local`) and at attach (magic bytes), with tests for both backends.

### Phase 4: Respondent auth, notifications, webhooks, abuse controls, Helm
Email OTP access mode, owner and respondent emails, webhooks (signing, retries, delivery log, SSRF guard, rotation), rate limiting, CAPTCHA (ALTCHA and Turnstile), CSP headers, Helm chart, a reference staging deployment.
**Status (Phase 4 build):** respondent email codes and staff-only forms, owner and respondent emails (receipt with the signed PDF), webhooks with signing, rotation, retries, delivery log, SSRF guard and reference verifiers (Python, Node, PHP), Redis rate limits, optional CAPTCHA (built-in proof of work modelled on ALTCHA, Turnstile, hCaptcha), CSP and security headers, the Settings page (including retention days) and the Helm chart are done. One-time codes are kept in Redis (HMAC, TTL, attempt counter) rather than a `respondent_otps` table; notification rules, an email log, webhooks and deliveries are tables. Not done: the Jotform importer (blocked on real export fixtures, §22.2 question 7), the reference staging deployment through a GitOps controller, and the securityheaders.com grade (needs a public host).
**Acceptance:**
- An OTP form works end to end, and OTP brute-force is blocked by the limits.
- The reference verifiers (Python/Node) validate the webhook signature.
- A receiver that is down for 3 hours gets the event delivered after recovery.
- A private-IP webhook is refused unless allowlisted.
- The Helm chart installs on a staging Kubernetes namespace through a GitOps controller, with secrets supplied by an external secrets operator.
- securityheaders.com reports an A grade for the public form.

**Jotform import (all of §13) is also in Phase 4.** It covers the HTML-source form importer with the type mapping and import report, the Excel/CSV submission import with the column-mapping UI and idempotent re-import, and the optional API-key path (form list, structure plus conditions, submissions).
**Acceptance (Jotform):**
- At least 5 real Jotform forms (collected per open question 7 in §22.2), covering every mapped type, page breaks and a Thaana form, import from HTML source into valid drafts. Every question is reported as imported, changed or unsupported, and none is silently dropped.
- Their `.xlsx` and `.csv` exports import with auto-mapping covering at least 90% of columns. Re-uploading the same file creates 0 duplicates.
- The API-key path imports the same forms with their conditions translated where supported, and the key is absent from the DB and logs (verified by test).

### Phase 5: Signatures and signed PDFs
Signature field and pad, server re-render, signature records, content hash (JCS), PDF rendering (fpdf2 + HarfBuzz, RTL/Thaana; the audit page was later replaced by the clean respondent PDF, §9.5), pyHanko PAdES signing (self-signed default, P12 option, optional TSA), `verify` endpoint and CLI, PDF attached to the receipt email, `submission.pdf_ready` webhook.
**Status:** everything except the receipt email and the `pdf_ready` webhook (both need Phase 4) was built early, with Phase 3: signature capture with timing, server re-render, audit records, content hash and event chain, signed PDFs, `GET /submissions/{id}/verify`, "Check a PDF" (`POST /pdf-checks`) and `justforms verify-pdf`.
**Acceptance:**
- Acrobat shows a valid signature, which becomes invalid after any byte edit.
- `justforms verify-pdf` detects a modified database row.
- A dv submission renders correct Thaana shaping in the PDF.
- Strokes are re-rendered to an identical PNG deterministically.

### Phase 6: AI and v1.0 release
Provider interface and adapters (Gemini, Anthropic, OpenAI-compatible), tool layer with Pydantic arg models, orchestrator with limits, SSE chat, proposal diff preview with Apply/Undo, describe → form, chat edits, document import (PDF/photo) with `flag_uncertain`, AI hidden when unconfigured. Then docs (self-hosting, schema reference, API), an a11y pass (WCAG 2.1 AA on the public form), a load test, the v1.0.0 release.
**Status (AI build):** the AI part is built: provider interface with Gemini, Anthropic and OpenAI-compatible adapters plus a scripted test provider, the tool layer, the tool loop with limits, rate limits and token allowances, SSE chat with Stop, describe → form, chat edits, blank paper form import with `flag_uncertain` and `report_filled_in`, the suggestion preview on the canvas with Apply/Discard and one-step Undo, audit entries, and AI hidden when unconfigured (§12.5, PHASE-5-SCREENS). Not done: the evaluation set of 20 prompts and 10 scanned blank forms (needs a real provider key and real paper forms), and the rest of this phase (docs site, a11y pass, load test, release).
**Acceptance:**
- An evaluation set of 20 prompts and 10 scanned **blank** paper forms (including Dhivehi and English forms) produces schemas that pass validation 100% of the time, with an agreed manual quality score.
- No AI path can write to the draft without Apply.
- With AI unset, no AI UI is visible.
- The public submit endpoint sustains 50 rps on the reference deployment with p95 under 300 ms (excluding uploads).

---

## 21. Later / backlog

### Done since v1 planning

- **Clean respondent PDF and a public verify page** (§9.5, §9.5.2).
- **Approval workflow**: up to three ordered steps, emailed approver links with one-time codes, the approval record on the re-signed PDF and the outcome email (§15.3).

### Backlog

- **AATL cloud signing.** A pluggable remote-signer adapter for publicly trusted PDF signatures (for example CSC API-based services such as GlobalSign DSS or SSL.com eSigner), since AATL keys must live in certified hardware (§9.5.1).
- **Excel live sync via Microsoft Graph**: append rows to a workbook or table in OneDrive/SharePoint on submit, with field mapping and retry. Google Sheets follows the same pattern.
- **Approvals, later**: parallel or conditional steps, steps assigned to particular studio users or roles (steps decided by everyone with edit access are built), reminders and deadlines, delegation.
- **Payments**: Stripe and local gateways such as BML Connect.
- **AI response summarisation**: summaries and themes over submissions. Because filled-in data never goes to a cloud LLM (§22.1), this would only run against a self-hosted/local model, with an explicit per-form opt-in.
- ClamAV scanning, enforced per org.
- Save-and-resume drafts for respondents, and "edit my submission" links.
- Calculated fields and an arithmetic expression language (in the shared spec, with vectors).
- ZIP export of all files and PDFs, CSV export, and scheduled exports.
- Org API tokens and a public REST API for automation. Zapier/n8n nodes.
- Templates gallery, form analytics (views, drop-off per page), and a custom theme designer.
- Google Forms importer, following the §13 pattern. These are deterministic, not AI. Fetching Jotform-hosted files during submission import (needs authenticated download).
- SAML, and SCIM provisioning.
- Uploaded per-org PDF signing certificate (PKCS#12) in the admin UI.
- Additional form languages beyond en/dv (the `settings.language` enum grows; direction is looked up per language), and multilingual forms with per-language translations if there is demand. A translated studio UI is not planned.

---

## 22. Decisions and open questions

### 22.1 Resolved decisions

1. **File storage.** A local volume is the default (Compose named volume, Helm PVC), so self-hosters need no object store. An external S3-compatible service is optional. MinIO or any other object store is not bundled (§10, §19).
2. **AI document import.** Paper/PDF/photo → form is for **blank** forms only, which may be sent to the cloud LLM provider. Filled-in forms are never sent to a cloud LLM (§12.3). Submission data reaches a provider only through "Ask your submissions" (§12.6): counts by default; every textual answer (contact details and sensitive questions included, never files, signatures or IP addresses) only when the form's owner turns on "Allow AI to read answers", off by default for every form (decided).
3. **PDF signing.** Each install signs with its own self-signed key and certificate by default. An uploaded org certificate may be added later (§9.5).
4. **Thaana fonts.** The font stack is `Faruma, "MV Faseyha", "Noto Sans Thaana", sans-serif`. Noto Sans Thaana is bundled as the fallback; Faruma/MV files are never committed and are supplied by operators through the `/fonts/` directory (§16). The Faruma licence is still to be confirmed (open question 6 in §22.2).
5. **English-only UI, single-language forms.** The studio, builder and dashboard UI is English only; there is no UI internationalisation. Dhivehi exists only in form content: each form has one `settings.language` (`en` or `dv`), all form text is plain strings in that language, and direction derives from it. Thaana support (font stack, `lang`/`dir` on form content, the phonetic keyboard for `dv` forms) applies wherever form content is typed or shown (§4.2, §16).

6. **Clean respondent PDF.** The PDF prints only the title, answers, signatures, reference, date, the approval record and a verify footer with a QR code; audit data stays in the studio and the signed metadata. The verify page is status only (§9.5, §9.5.2).
7. **Approvals.** Settings live outside the schema and are copied onto each response; approvers confirm by email code and never see sensitive answers; the status is locked while an approval runs, and stopping it hands control back (§15.3).
8. **AI assistant scope (v1).** Describe → form, chat edits, and paper → form for blank forms only (confirmed per upload; filled forms are never sent and no answers are extracted). The model only calls validated schema tools; nothing reaches the draft before Apply. Providers are pluggable (Gemini, Anthropic, OpenAI-compatible for local models) and configured per install (§12.5).

### 22.2 Open questions

1. **Data retention defaults.** What default retention period, and which legal or records-management rules, should apply to submissions by default (especially signed ones)? Should hard deletion of signed submissions be blocked?
2. **Email delivery.** Which SMTP relay and sender domain should the reference deployment use? Respondent receipts to external addresses need SPF/DKIM alignment.
3. **Embedding.** Will forms mostly be embedded on other sites via iframe on specific origins, or only linked? This determines the `frame-ancestors` defaults.
4. **Internal webhook targets.** Which internal systems will receive webhooks? Their CIDRs need adding to `JUSTFORMS_WEBHOOK_ALLOWED_CIDRS`.
5. **Who may change status.** Editors can approve or reject in v1, and approval steps go to email addresses; editors and owners can also decide the current approval step in the studio (§15.3). Is a separate "reviewer" role needed (can change status and decide steps but cannot edit the form), or approval steps assigned to studio users?
6. **Faruma licence.** Can Faruma (and any MV-series fonts) be licensed for web embedding and PDF embedding? Until confirmed, installs rely on Noto Sans Thaana or locally installed fonts.
7. **Jotform HTML structure needs verifying.** The selectors in §13.1 (`li.form-line[data-type]`, `label#label_{qid}`, `form-required`, `name="q{qid}_..."`, `control_pagebreak`, inline `JotForm.setConditions`) are based on Jotform's known embed markup. They have **not** been checked against a current real export. Before building the parser, collect the "Source Code" HTML plus the matching `.xlsx`/`.csv` submission exports from several real forms, and commit them (with personal data scrubbed) as fixtures under `backend/tests/fixtures/jotform/`. Then confirm whether conditions appear in the HTML at all, and confirm the export's column headers and date and multi-choice formats.
8. **Timestamping.** Is an RFC 3161 TSA available, and is one required for signed PDFs (PAdES-B-T)?
