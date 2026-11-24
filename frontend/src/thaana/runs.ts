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

/** A piece of form text; `dir` set on a run of the minority script, to be isolated in it. */
export type IsolatedRun = { text: string; dir: 'ltr' | 'rtl' | null }

/**
 * `text` split for display in a block whose direction is `dir`: runs of the other script (Latin
 * inside right-to-left text, Thaana inside left-to-right text) carry the direction to isolate
 * them in (`<bdi>` / `dir` on a span, LRI/RLI…PDI in the PDF), so the brackets and punctuation
 * around them stay on the right side ("(PPY)" inside Dhivehi). Everything else is one run.
 * Twin of `isolate_runs` (backend/app/schemas/direction.py); vectors `isolate`.
 */
export function isolateRuns(text: string, dir: 'ltr' | 'rtl'): IsolatedRun[] {
  const minority = dir === 'rtl' ? 'latin' : 'thaana'
  const out: IsolatedRun[] = []
  for (const run of scriptRuns(text)) {
    if (run.script === minority) out.push({ text: run.text, dir: minority === 'thaana' ? 'rtl' : 'ltr' })
    else if (out.length && out[out.length - 1].dir === null) out[out.length - 1].text += run.text
    else out.push({ text: run.text, dir: null })
  }
  return out
}
