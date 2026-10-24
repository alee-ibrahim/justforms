/**
 * Document pages reached from a link or QR code, outside the studio and the public form
 * bundle: the verify page (`/v/{token}`, tiny, status only) and the approver page
 * (`/a/{token}`, loaded lazily).
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '../index.css'

import { DocApp } from './app'


createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <DocApp />
  </StrictMode>,
)
