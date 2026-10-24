# Contributing to JustForms

Thanks for helping. Bug reports, fixes, docs and feature ideas are all welcome.

## Before you start

- **Bugs:** open an issue with steps to reproduce, what you expected and what happened.
  Screenshots help, especially for layout and right-to-left problems.
- **Features:** open an issue first so we can agree on the approach before you write code.
- **Security problems:** don't open a public issue. Use the private
  [Report a vulnerability](https://github.com/alee-ibrahim/justforms/security/advisories/new)
  button instead (see [docs/security.md](docs/security.md)).

## Getting set up

You need Python 3.13 with [uv](https://docs.astral.sh/uv/), Node with corepack (for pnpm),
[just](https://just.systems) and Docker.

```sh
just infra                    # PostgreSQL and Redis in Docker
just install                  # uv sync + pnpm install
just migrate
just create-admin you@example.org
just dev                      # API, worker and Vite together
```

[docs/development.md](docs/development.md) covers the project structure, every check and the
mobile layout audit.

## Making a change

1. Fork the repo and create a branch from `main`.
2. Keep the pull request focused on one thing.
3. Add or update tests for what you changed.
4. Run the checks:

   ```sh
   just lint
   just test
   just check-spec               # if you touched the form schema (run `just spec` first)
   cd frontend && pnpm build && pnpm check:bundle   # if you touched the public form
   ```

5. Update the docs in `docs/` when behaviour or settings change.
6. Open a pull request against `main` and fill in the template.

`main` is protected: changes land through reviewed pull requests.

## Project rules

These keep the codebase consistent. [CLAUDE.md](CLAUDE.md) has the full list.

- **UI components come from the official shadcn/ui CLI only** (`pnpm dlx shadcn@latest add …`).
  Don't hand-write components that imitate shadcn, and don't edit files in
  `frontend/src/components/ui/`. Compose new pieces from official components.
- **Use pnpm and uv**, not npm, yarn or pip.
- **Interface text is English.** The studio, public form buttons and messages, emails, the
  verify page and PDF labels are English. Dhivehi appears only in form content and answers;
  Dhivehi forms render right to left. Use logical Tailwind classes (`ms-`, `pe-`, `start-`…),
  never `left`/`right`.
- **The form schema is the source of truth.** Change `backend/app/schemas/form.py`, then run
  `just spec`. The logic engine and answer validation each have a Python and a TypeScript twin:
  change both together and add a shared test vector in `spec/`.
- **Keep the public form small.** It has a 120 KB gzip budget; lazy-load anything heavy.
- **No secrets** in code, fixtures or examples. Use placeholders such as `change-me` and
  `example.org`.
- **Keep it generic.** Don't reference a specific organisation's name, infrastructure or
  internal URLs anywhere in the repo.

## Commit messages

Write a short summary line in the imperative ("Add webhook retries", not "Added…"), then a
blank line and any detail that helps a reviewer.

## Licence

JustForms is licensed under [AGPL-3.0](LICENSE). By contributing, you agree that your
contributions are licensed under the same terms.
