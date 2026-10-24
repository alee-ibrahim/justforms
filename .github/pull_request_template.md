## What does this change?

<!-- One or two sentences. Link the issue it fixes, e.g. "Fixes #12". -->

## How was it tested?

<!-- Commands you ran, screenshots for UI changes (light/dark, phone/desktop, English/Dhivehi form if relevant). -->

## Checklist

- [ ] `just lint` and `just test` pass
- [ ] Tests added or updated
- [ ] UI uses official shadcn/ui components only (nothing hand-rolled, `components/ui/` untouched)
- [ ] Interface text is English; logical direction classes only
- [ ] Schema change: `just spec` run, both logic/validation twins updated with shared vectors
- [ ] Public form change: `pnpm check:bundle` passes
- [ ] Docs in `docs/` updated if behaviour or settings changed
- [ ] No secrets or organisation-specific details
