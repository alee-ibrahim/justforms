/** Respondent file upload (DESIGN 10). Its own chunk: loaded on the first upload only. */
import type { FileRef } from '@/renderer/validation'

import { authInit, formPath, type Access } from './api'

interface UploadTarget {
  fileId: string
  method: 'PUT' | 'POST'
  url: string
  fields: Record<string, string>
  headers: Record<string, string>
}

/**
 * Upload one file (DESIGN 10): start it with the API, then send the bytes either to the API
 * (`PUT`, local storage) or straight to the bucket (`POST` presigned form, s3). XHR because
 * fetch has no upload progress.
 */
export async function uploadFile(
  slug: string,
  access: Access,
  nonce: string,
  file: File,
  fieldId: string,
  onProgress: (fraction: number) => void,
  signal: AbortSignal,
): Promise<FileRef> {
  const init = authInit(access, true)
  const res = await fetch(`${formPath(slug)}/uploads`, {
    ...init,
    method: 'POST',
    headers: { ...(init.headers as Record<string, string>), 'Content-Type': 'application/json' },
    body: JSON.stringify({ fieldId, name: file.name, size: file.size, mime: file.type, uploadNonce: nonce }),
    signal,
  })
  // The API's refusal code (file_type, file_too_large, file_empty...) becomes the error message,
  // so the question can say why; 429 is a rate limit.
  if (!res.ok)
    throw new Error(
      res.status === 429 ? 'rate_limited' : await res.json().then((b: { detail?: unknown }) => String(b.detail), () => 'upload_refused'),
    )
  const target = (await res.json()) as UploadTarget
  const body = await new Promise<string>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(target.method, target.url)
    for (const [k, v] of Object.entries(target.headers)) xhr.setRequestHeader(k, v)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () =>
      xhr.status < 300
        ? resolve(xhr.responseText)
        : reject(new Error(xhr.status === 413 ? 'file_too_large' : xhr.status === 429 ? 'rate_limited' : String(xhr.status)))
    xhr.onerror = xhr.onabort = () => reject(new Error('upload_failed'))
    signal.addEventListener('abort', () => xhr.abort())
    let payload: Blob | FormData = file
    if (target.method === 'POST') {
      payload = new FormData()
      for (const [k, v] of Object.entries(target.fields)) payload.append(k, v)
      payload.append('file', file)
    }
    xhr.send(payload)
  })
  onProgress(1)
  return target.method === 'PUT'
    ? (JSON.parse(body) as FileRef)
    : { fileId: target.fileId, name: file.name, size: file.size, mime: file.type }
}
