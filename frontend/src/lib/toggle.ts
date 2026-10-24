/**
 * Visible "on" state for shadcn Toggle / ToggleGroup items. The generated components mark the
 * on state with bg-muted, which is 1.1:1 against the sheet (WCAG 1.4.11 needs 3:1), so the
 * selected option could not be seen. These call-site classes add a carbon edge (7.9:1) and a
 * carbon-tint fill, and the label goes semibold so the choice reads at a glance (not only by
 * colour); components/ui stays as generated. Written out in full so Tailwind sees them.
 */

/** For a single <Toggle>. */
export const toggleOn =
  'data-[state=on]:bg-secondary data-[state=on]:font-semibold data-[state=on]:text-foreground data-[state=on]:inset-ring data-[state=on]:inset-ring-primary'

/** For a <ToggleGroup>: styles its direct ToggleGroupItem children. */
export const toggleGroupOn =
  '*:data-[state=on]:border-primary! *:data-[state=on]:bg-secondary! *:data-[state=on]:font-semibold! *:data-[state=on]:text-foreground! *:data-[state=on]:inset-ring! *:data-[state=on]:inset-ring-primary!'
