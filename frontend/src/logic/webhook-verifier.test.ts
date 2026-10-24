// The Node.js reference webhook verifier (docs/webhooks/verify.mjs) against the shared signature
// vectors that the backend's signer is also tested with (spec/webhooks/signature-v1.json).
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import { describe, expect, it } from 'vitest'

import { loadSpecFile } from './spec-files'

interface Vectors {
  secret: string
  previousSecret: string
  headers: Record<string, string>
  body: string
  now: number
}

type Verify = (secret: string, headers: Record<string, string>, body: string | Buffer, opts?: { now?: number }) => boolean

const vectors = loadSpecFile<Vectors>('webhooks/signature-v1.json')
const verifierUrl = pathToFileURL(path.resolve(import.meta.dirname, '../../../docs/webhooks/verify.mjs')).href

describe('webhook reference verifier (Node.js)', async () => {
  const { verify } = (await import(/* @vite-ignore */ verifierUrl)) as { verify: Verify }
  const now = vectors.now

  it('accepts the signed request with the current and the previous secret', () => {
    expect(verify(vectors.secret, vectors.headers, Buffer.from(vectors.body, 'utf8'), { now })).toBe(true)
    expect(verify(vectors.previousSecret, vectors.headers, vectors.body, { now })).toBe(true)
  })

  it('rejects a wrong secret, a changed body and an old timestamp', () => {
    expect(verify('whsec_wrong', vectors.headers, vectors.body, { now })).toBe(false)
    expect(verify(vectors.secret, vectors.headers, `${vectors.body} `, { now })).toBe(false)
    expect(verify(vectors.secret, vectors.headers, vectors.body, { now: now + 400 })).toBe(false)
  })
})
