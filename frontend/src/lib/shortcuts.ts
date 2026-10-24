/** "Ctrl" or "⌘" for the shortcut hints. */
export const MOD_KEY =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'

export const BUILDER_SHORTCUTS: { keys: string[]; action: string }[] = [
  { keys: ['/'], action: 'Add a question' },
  { keys: ['↑', '↓'], action: 'Select previous or next question' },
  { keys: ['Enter'], action: 'Edit the label, or the focused text' },
  { keys: ['Tab'], action: 'Next text you can edit' },
  { keys: ['Shift', 'Enter'], action: 'New line while editing' },
  { keys: ['Esc'], action: 'Cancel editing, then clear the selection' },
  { keys: ['Alt', '↑'], action: 'Move up' },
  { keys: ['Alt', '↓'], action: 'Move down' },
  { keys: [MOD_KEY, 'D'], action: 'Duplicate' },
  { keys: ['Delete'], action: 'Delete' },
  { keys: [MOD_KEY, 'Z'], action: 'Undo' },
  { keys: [MOD_KEY, 'Shift', 'Z'], action: 'Redo' },
  { keys: [MOD_KEY, 'Enter'], action: 'Publish' },
  { keys: ['?'], action: 'Show shortcuts' },
]
