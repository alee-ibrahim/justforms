/**
 * Thaana -> Latin by the official romanisation rules of 23 May 1977, and form addresses made
 * from titles.
 *
 * Ported from `dhivehi_rules/thaana_latin.py` in https://github.com/alee-ibrahim/dhivehi-rules
 * (MIT License, Copyright (c) 2026 Alee Ibrahim). Twin of `backend/app/text/thaana_latin.py` and
 * `slugify` in `backend/app/services/slugs.py`; both run the vectors in `spec/slugs/`, so change
 * them together.
 *
 *   §1 consonants  ހ h  ށ sh  ނ n  ރ r  ބ b  ޅ lh  ކ k  ވ v  މ m  ފ f  ދ dh  ތ th
 *                  ލ l  ގ g  ޏ gn  ސ s  ޑ d  ޒ z  ޓ t  ޔ y  ޕ p  ޖ j  ޗ ch
 *   §2 Arabic      ޞ s'  ޟ l'  ޠ t'  ޡ z'  ޥ w  ޘ th'  ޙ h'  ޚ kh  ޛ dh'  ޣ gh  ޤ q ;
 *                  ޝ sh ; ޢ = the vowel with an apostrophe (a'mal)
 *   §3 vowels      ަ a  ާ aa  ި i  ީ ee  ު u  ޫ oo  ެ e  ޭ ey  ޮ o  ޯ oa ; އ + vowel = the vowel
 *   §4 sukun       final އް h, ން n, ށް iy, ސް s; before a consonant: that consonant
 *                  (doubled after އް: bappa), ން before މ -> m (mamma)
 *   §5             a bare ނ before a consonant -> n' (kan'di)
 *   §6             a sentence begins with a capital
 */

const CONS: Record<string, string> = {
  'ހ': 'h', 'ށ': 'sh', 'ނ': 'n', 'ރ': 'r', 'ބ': 'b', 'ޅ': 'lh', 'ކ': 'k', 'އ': '',
  'ވ': 'v', 'މ': 'm', 'ފ': 'f', 'ދ': 'dh', 'ތ': 'th', 'ލ': 'l', 'ގ': 'g', 'ޏ': 'gn',
  'ސ': 's', 'ޑ': 'd', 'ޒ': 'z', 'ޓ': 't', 'ޔ': 'y', 'ޕ': 'p', 'ޖ': 'j', 'ޗ': 'ch',
  'ޞ': "s'", 'ޟ': "l'", 'ޠ': "t'", 'ޡ': "z'", 'ޥ': 'w', 'ޘ': "th'", 'ޙ': "h'",
  'ޚ': 'kh', 'ޛ': "dh'", 'ޝ': 'sh', 'ޣ': 'gh', 'ޤ': 'q', 'ޜ': 'zh', 'ޢ': '',
}
const VOWEL: Record<string, string> = {
  'ަ': 'a', 'ާ': 'aa', 'ި': 'i', 'ީ': 'ee', 'ު': 'u', 'ޫ': 'oo',
  'ެ': 'e', 'ޭ': 'ey', 'ޮ': 'o', 'ޯ': 'oa',
}
const SUKUN = 'ް'
const LONG = new Set(['aa', 'ee', 'oo', 'ey', 'oa'])
const PUNCT: Record<string, string> = { '،': ',', '؟': '?', '؛': ';' }
const THAANA = /[ހ-޿]/

const has = (map: Record<string, string>, c: string) => Object.prototype.hasOwnProperty.call(map, c)

export function hasThaana(text: string): boolean {
  return THAANA.test(text)
}

/** One word, without §6's capital (the booklet's examples are given this way). */
export function romaniseWord(w: string): string {
  const out: string[] = []
  const n = w.length
  let i = 0
  while (i < n) {
    const c = w[i]
    const nxt = i + 1 < n ? w[i + 1] : ''
    if (has(VOWEL, c) || c === SUKUN) {
      i += 1 // stray mark: nothing to attach it to
      continue
    }
    if (!has(CONS, c)) {
      out.push(PUNCT[c] ?? c)
      i += 1
      continue
    }
    if (nxt && has(VOWEL, nxt)) {
      const v = VOWEL[nxt]
      // §2: a'mal, i'shq, Maso'odh, a'ailaa
      if (c === 'ޢ') out.push(LONG.has(v) ? `${v[0]}'${v.slice(1)}` : `${v}'`)
      else out.push(CONS[c] + v)
      i += 2
      continue
    }
    if (nxt === SUKUN) {
      const after = i + 2 < n ? w[i + 2] : ''
      const final = after === '' || !has(CONS, after)
      if (c === 'އ') {
        if (final) out.push('h') // §4: meeheh
        else if (CONS[after]) out.push(CONS[after]) // §4: bappa, bayyeh
      } else if (c === 'ށ' && final) out.push('iy') // §4: foiy, baiy
      else if (c === 'ނ' && after === 'މ') out.push('m') // §4: mamma
      else out.push(CONS[c]) // fen, gas, ramzu, milku
      i += 2
      continue
    }
    if (c === 'ނ' && nxt && has(CONS, nxt)) {
      out.push("n'") // §5: prenasalised stop
      i += 1
      continue
    }
    out.push(CONS[c]) // bare letter: an abbreviation
    i += 1
  }
  return out.join('')
}

/** Official 1977 romanisation of a Thaana text; sentences start with a capital. Latin letters,
 * digits and other characters pass through unchanged. */
export function romanise(text: string): string {
  const out = text
    .split(/(\s+)/)
    .map((p) => (p.trim() ? romaniseWord(p) : p))
    .join('')
  // §6: a capital at the start of each sentence.
  return out.replace(/(^|[.!?]\s+)([a-z])/g, (_m, pre: string, ch: string) => pre + ch.toUpperCase())
}

/** Addresses made from a title are cut to about this many characters, at a word boundary. */
export const TITLE_SLUG_LENGTH = 60

function cut(slug: string, limit = TITLE_SLUG_LENGTH): string {
  if (slug.length <= limit) return slug
  const head = slug.slice(0, limit + 1)
  const at = head.lastIndexOf('-')
  return at >= Math.floor(limit / 3) ? head.slice(0, at) : slug.slice(0, limit).replace(/-+$/, '')
}

/** Romanised when it has Thaana, apostrophes dropped (kan'di -> kandi), accents folded. */
export function toSlugText(text: string): string {
  const latin = hasThaana(text) ? romanise(text) : text
  return latin
    .replace(/['’ʼ]/g, '')
    .normalize('NFKD')
    .replace(/[\u0080-\uffff]/g, '')
    .toLowerCase()
}

/** The address the server derives from a title (`slugify` in `app/services/slugs.py`). */
export function titleSlug(title: string, fallback = 'form'): string {
  const slug = toSlugText(title).replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return cut(slug).replace(/^-+|-+$/g, '') || fallback
}

/** What a title without Latin letters used to give (`form`, `form-2`). */
export function isGenericSlug(slug: string): boolean {
  return /^form(-[0-9]+)?$/.test(slug)
}
