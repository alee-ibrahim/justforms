/**
 * The JustForms mark: the radio o from the wordmark on its own (docs/brand), in the text colour.
 * Tiny on purpose: it ships in the public form bundle. Decorative.
 */
export function JustFormsMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false" className={className}>
      <circle cx="32" cy="32" r="25.15" fill="none" stroke="currentColor" strokeWidth="13.7" />
      <circle cx="32" cy="32" r="11.75" fill="currentColor" />
    </svg>
  )
}
