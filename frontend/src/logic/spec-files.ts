// Test helper: loads the shared spec fixtures from the repo's spec/ directory (node only).
import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

const specDir = path.resolve(import.meta.dirname, '../../../spec')

export function loadSpecDir<T>(sub: string): { file: string; data: T }[] {
  const dir = path.join(specDir, sub)
  return readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .sort()
    .map((file) => ({ file, data: JSON.parse(readFileSync(path.join(dir, file), 'utf8')) as T }))
}

export function loadSpecFile<T>(rel: string): T {
  return JSON.parse(readFileSync(path.join(specDir, rel), 'utf8')) as T
}
