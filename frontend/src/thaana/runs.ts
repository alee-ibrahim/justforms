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

const OPENERS = '([{'
const CLOSERS = ')]}'

/** Openers in `text` still waiting for their closer, innermost last. */
function unclosed(text: string): string[] {
  const stack: string[] = []
  for (const ch of text) {
    const o = OPENERS.indexOf(ch)
    if (o >= 0) stack.push(CLOSERS[o])
    else if (stack[stack.length - 1] === ch) stack.pop()
  }
  return stack
}

/**
 * Bracket pairs stay with the run they enclose: closers right after a run that it opened
 * ("(PPY" + "))") move into it, and an opener just before it whose closer follows it right after
 * wraps it ("(" + "Practice Parliament (PPY)" + ")"). Runs are modified in place; emptied
 * neutrals are dropped.
 */
function pairBrackets(runs: Run[], i: number): void {
  const run = runs[i]
  const next = runs[i + 1]?.script === 'neutral' ? runs[i + 1] : null
  const prev = runs[i - 1]?.script === 'neutral' ? runs[i - 1] : null
  if (next) {
    const stack = unclosed(run.text)
    let k = 0
    while (stack.length && next.text[k] === stack[stack.length - 1]) {
      stack.pop()
      k++
    }
    run.text += next.text.slice(0, k)
    next.text = next.text.slice(k)
  }
  while (prev && next && prev.text) {
    const o = OPENERS.indexOf(prev.text[prev.text.length - 1])
    if (o < 0 || next.text[0] !== CLOSERS[o]) break
    run.text = prev.text[prev.text.length - 1] + run.text + next.text[0]
    prev.text = prev.text.slice(0, -1)
    next.text = next.text.slice(1)
  }
}

/**
 * `text` split for display in a block whose direction is `dir`: runs of the other script (Latin
 * inside right-to-left text, Thaana inside left-to-right text) carry the direction to isolate
 * them in (`<bdi>` / `dir` on a span, LRI/RLI…PDI in the PDF), so the brackets and punctuation
 * around them stay on the right side ("(PPY)" inside Dhivehi). A bracket pair belongs to the run
 * it encloses, so "(Practice Parliament for Youth (PPY))" after Dhivehi is one isolated run with
 * both its closers. Everything else is one run.
 * Twin of `isolate_runs` (backend/app/schemas/direction.py); vectors `isolate`.
 */
export function isolateRuns(text: string, dir: 'ltr' | 'rtl'): IsolatedRun[] {
  const minority = dir === 'rtl' ? 'latin' : 'thaana'
  const runs = scriptRuns(text)
  runs.forEach((run, i) => {
    if (run.script === minority) pairBrackets(runs, i)
  })
  const out: IsolatedRun[] = []
  for (const run of runs) {
    if (!run.text) continue
    if (run.script === minority) out.push({ text: run.text, dir: minority === 'thaana' ? 'rtl' : 'ltr' })
    else if (out.length && out[out.length - 1].dir === null) out[out.length - 1].text += run.text
    else out.push({ text: run.text, dir: null })
  }
  return out
}

/**
 * The two halves of a bilingual one-line text ("Full name: ފުރިހަމަ ނަން"): its English part and
 * its Dhivehi part, each with the punctuation that ends it and the brackets that enclose it, the
 * divider between them ("/", "|", a dash, spaces) dropped. `first` is the script the text starts
 * with. Rendered as one row, English at the left and Dhivehi at the right.
 */
export interface BilingualParts {
  ltr: string
  rtl: string
  first: 'ltr' | 'rtl'
}

// Always a divider between two parts, however short they are.
const STRONG = /[/|]/
// Where the gap between the parts is cut: at a divider ("/", "|", a spaced dash or bullet), else
// at its last spaces; the divider and spaces are dropped.
const CUT = /\s*[/|]\s*|\s+[‐-―•·-]+\s+/
const LAST_SPACES = /\s+(?=\S*$)/
// Without spaces: the closers and punctuation that end the first part (Dhivehi "؟", "،", "؛").
const ENDING = /^[)\]}:;,.!?؟،؛…]*/

/** Words of one script run: runs of letters (marks included). */
function words(text: string): number {
  return text.split(/[^\p{L}\p{M}]+/u).filter(Boolean).length
}

/**
 * Splits a one-line text that is **one English block and one Dhivehi block** (either order) into
 * its two parts, or `null`: multi-line text, text in one script, text with more than two script
 * blocks (an acronym inside a Dhivehi sentence: "ބައިވެރިވުމަށް (PPY) ފޯމު ފުރުއްވާ."), two
 * blocks with only spaces between them ("PPY ގެ ބައިވެރިން"), and, unless "/" or "|" divides
 * them, a lone capitalised acronym ("ބައިވެރިވުމަށް (PPY)") or a short run tacked onto a long
 * sentence ("Is PPY ready? ތައްޔާރު": the shorter part needs two words or half the longer's).
 * Twin of `bilingual_parts` (backend/app/schemas/direction.py); vectors `bilingual`.
 */
export function bilingualParts(text: string | null | undefined): BilingualParts | null {
  if (!text || /[\r\n]/.test(text)) return null
  const runs = scriptRuns(text)
  const letters = runs.filter((r) => r.script !== 'neutral')
  if (letters.length !== 2 || letters[0].script === letters[1].script) return null
  const a = runs.indexOf(letters[0])
  const b = runs.indexOf(letters[1])
  const gap = b > a + 1 ? runs[a + 1].text : ''
  // Something other than spaces (and figures) must mark the break between the two parts.
  if (!/[^\s\d]/.test(gap)) return null
  const latinFirst = letters[0].script === 'latin'
  const latin = letters[latinFirst ? 0 : 1].text
  const latinWords = words(latin)
  const thaanaWords = words(letters[latinFirst ? 1 : 0].text)
  const short = Math.min(latinWords, thaanaWords)
  if (!STRONG.test(gap) && ((latinWords === 1 && !/\p{Ll}/u.test(latin)) || (short < 2 && short * 2 < latinWords + thaanaWords - short)))
    return null
  // The first part keeps what ends it (":", "?", its closing brackets), the second what opens it.
  const cut = CUT.exec(gap) ?? LAST_SPACES.exec(gap)
  const at = cut ? cut.index : ENDING.exec(gap)![0].length
  const first = (runs.slice(0, a + 1).map((r) => r.text).join('') + gap.slice(0, at)).trim()
  const second = (gap.slice(cut ? at + cut[0].length : at) + runs.slice(b).map((r) => r.text).join('')).trim()
  return latinFirst ? { ltr: first, rtl: second, first: 'ltr' } : { ltr: second, rtl: first, first: 'rtl' }
}
