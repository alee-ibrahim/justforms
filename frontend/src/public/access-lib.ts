/**
 * Strings and helpers for the access chunk (email codes, staff sign-in, CAPTCHA). The strings are
 * system text, so English for every form (docs/DESIGN.md, "Languages").
 */
import { formPath, type CaptchaChallenge } from './api'

export const ACCESS = {
  otpTitle: 'Confirm your email to continue',
  otpIntro: "We'll send a 6-digit code to your inbox.",
  email: 'Email',
  sendCode: 'Send code',
  codeTitle: 'Enter the code',
  codeSent: 'We sent it to {email}. It works for 10 minutes.',
  codeLabel: '6-digit code',
  continue: 'Continue',
  resend: 'Send a new code',
  resendIn: 'Send a new code (in {time})',
  differentEmail: 'Use a different email',
  emailInvalid: 'Enter an email address like name@example.com',
  domain: 'Use an email address from {domains}.',
  wrong: "That code isn't right. Check the email and try again.",
  expired: 'This code has expired. Send a new code.',
  tooMany: 'Too many tries. Wait a few minutes and try again.',
  failed: "Couldn't send the code. Check your connection and try again.",
  announceSent: 'Code sent',
  respondingAs: 'Responding as {email}',
  alreadyTitle: "You've already responded",
  alreadyBody: 'This form accepts one response per email address.',
  signInTitle: 'Sign in to fill in this form',
  signInBody: 'This form is for staff. Taking you to the sign-in page.',
  captchaLabel: "Check that you're a person",
  captchaRequired: 'Complete the check above the submit button',
  checking: 'Checking your browser…',
  captchaFailed: "Couldn't finish the check. Try again.",
  retry: 'Try again',
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

/** Solve a proof-of-work challenge (altcha); yields to the page every 500 hashes. */
export async function solveAltcha(c: CaptchaChallenge, signal?: AbortSignal): Promise<string> {
  for (let n = 0; n <= c.maxnumber; n++) {
    if (signal?.aborted) throw new Error('aborted')
    if ((await sha256Hex(`${c.salt}${n}`)) === c.challenge) {
      const payload = { algorithm: c.algorithm, challenge: c.challenge, number: n, salt: c.salt, signature: c.signature }
      return btoa(JSON.stringify(payload))
    }
    if (n % 500 === 499) await new Promise((r) => setTimeout(r, 0))
  }
  throw new Error('unsolved')
}

export async function freshChallenge(slug: string): Promise<CaptchaChallenge | null> {
  try {
    const res = await fetch(`${formPath(slug)}/captcha`, { credentials: 'omit' })
    return res.ok ? ((await res.json()) as CaptchaChallenge) : null
  } catch {
    return null
  }
}
