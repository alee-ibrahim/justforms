/** Script runs of form text that may mix Thaana and Latin (see form-text.tsx). */
const THAANA = /[ހ-޿]/
const LETTER = /\p{L}/u

/** A script run: `thaana`, `latin` (any other letters) or `neutral` (spaces, digits, marks). */
export type Run = { text: string; script: 'thaana' | 'latin' | 'neutral' }

function scriptOf(ch: string): Run['script'] {
  if (THAANA.test(ch)) return 'thaana'
  return LETTER.test(ch) ? 'latin' : 'neutral'
}

/** Splits `text` into script runs. Neutrals between two runs of one script join that run. */
export function scriptRuns(text: string): Run[] {
  const runs: Run[] = []
  let current: Run | null = null
  let pending = ''
  for (const ch of text) {
    const script = scriptOf(ch)
    if (script === 'neutral') {
      pending += ch
    } else if (current && current.script === script) {
      current.text += pending + ch
      pending = ''
    } else {
      if (pending) runs.push({ text: pending, script: 'neutral' })
      pending = ''
      current = { text: ch, script }
      runs.push(current)
    }
  }
  if (pending) runs.push({ text: pending, script: 'neutral' })
  return runs
}

/** True when `text` holds letters of both scripts. */
export function isMixed(text: string): boolean {
  const scripts = new Set(scriptRuns(text).map((r) => r.script))
  return scripts.has('thaana') && scripts.has('latin')
}
