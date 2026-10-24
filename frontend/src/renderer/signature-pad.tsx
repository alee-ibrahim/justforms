/**
 * Signature pad (PHASE-2-SCREENS 4.9): Card + Buttons around a bare <canvas>. Lazy chunk.
 * Strokes are kept as point lists `[x, y, t, pressure]` (x/y 0-1 across the pad, t in ms since
 * the pad was first touched) so the server can re-render them for the audit trail (DESIGN 9.1);
 * the drawing is never mirrored in RTL.
 */
import { EraserIcon, UndoIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import type { SignatureField } from '@/schema'

import { useRenderer } from './context'
import type { ControlProps } from './fields'
import { MSG } from './messages'
import { En } from './msg'

type Point = [x: number, y: number, t: number, pressure: number]
interface SignatureValue {
  strokes: Point[][]
  width: number
  height: number
  dpr: number
  signedAt: string
}

const round = (n: number) => Math.round(n * 10000) / 10000

export default function SignaturePad({
  field,
  path,
  invalid,
  describedBy,
}: ControlProps & { field: SignatureField }) {
  const ctx = useRenderer()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const initial = ctx.getValue(path) as SignatureValue | undefined
  const [strokes, setStrokes] = useState<Point[][]>(initial?.strokes ?? [])
  const drawing = useRef<Point[] | null>(null)
  const started = useRef<number | null>(null)

  const redraw = useCallback((list: Point[][]) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    const { width, height } = canvas.getBoundingClientRect()
    canvas.width = width * dpr
    canvas.height = height * dpr
    const g = canvas.getContext('2d')
    if (!g) return
    g.scale(dpr, dpr)
    g.clearRect(0, 0, width, height)
    g.strokeStyle = getComputedStyle(canvas).color
    g.lineCap = 'round'
    g.lineJoin = 'round'
    for (const stroke of list) {
      for (let i = 1; i < stroke.length; i++) {
        const [x0, y0] = stroke[i - 1]
        const [x1, y1, , p] = stroke[i]
        g.lineWidth = 1.2 + 2.2 * (p || 0.5)
        g.beginPath()
        g.moveTo(x0 * width, y0 * height)
        g.lineTo(x1 * width, y1 * height)
        g.stroke()
      }
    }
  }, [])

  useEffect(() => {
    redraw(strokes)
    const onResize = () => redraw(strokes)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [strokes, redraw])

  const commit = (list: Point[][]) => {
    setStrokes(list)
    const canvas = canvasRef.current!
    const { width, height } = canvas.getBoundingClientRect()
    const value: SignatureValue = {
      strokes: list,
      width: Math.round(width),
      height: Math.round(height),
      dpr: window.devicePixelRatio || 1,
      signedAt: new Date().toISOString(),
    }
    ctx.setValue(path, list.length ? value : undefined)
  }

  const point = (e: React.PointerEvent<HTMLCanvasElement>): Point => {
    const r = e.currentTarget.getBoundingClientRect()
    started.current ??= e.timeStamp
    const clamp = (n: number) => round(Math.min(1, Math.max(0, n)))
    return [
      clamp((e.clientX - r.left) / r.width),
      clamp((e.clientY - r.top) / r.height),
      Math.round(e.timeStamp - started.current),
      round(e.pressure),
    ]
  }

  const signed = strokes.length > 0
  return (
    <div className="flex flex-col gap-3">
      {/* The signing statement is content, never part of an error: it keeps the ink colour. */}
      {field.attestation && <p className="text-base text-foreground">{field.attestation}</p>}
      <Card className="relative gap-0 overflow-hidden py-0" dir="ltr">
        <CardContent className="p-0">
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={signed ? MSG.signatureSigned : MSG.signatureEmpty}
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            className="block h-44 w-full touch-none text-foreground sm:h-56"
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId)
              drawing.current = [point(e)]
            }}
            onPointerMove={(e) => {
              if (!drawing.current) return
              drawing.current.push(point(e))
              redraw([...strokes, drawing.current])
            }}
            onPointerUp={() => {
              const stroke = drawing.current
              drawing.current = null
              // A new stroke updates the answer, which clears "Sign in the box" by itself;
              // blurring now would check the answer from before the stroke and show it again.
              if (stroke && stroke.length > 1) commit([...strokes, stroke])
              else ctx.blur(path)
            }}
          />
          <div className="pointer-events-none absolute inset-x-6 top-[70%] border-t" />
          {!signed && (
            <p
              className="pointer-events-none absolute inset-x-6 top-[74%] text-sm text-muted-foreground"
              lang="en"
            >
              {MSG.signHere}
            </p>
          )}
        </CardContent>
      </Card>
      {/* Public density: 44px targets (DESIGN-SYSTEM 6). */}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-11 px-3 text-base"
          disabled={!signed}
          onClick={() => commit(strokes.slice(0, -1))}
        >
          <UndoIcon className="rtl:-scale-x-100" />
          <En>{MSG.undoStroke}</En>
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-11 px-3 text-base"
          disabled={!signed}
          onClick={() => commit([])}
        >
          <EraserIcon />
          <En>{MSG.clear}</En>
        </Button>
      </div>
      <p className="text-sm text-muted-foreground min-[360px]:hidden">
        <En>{MSG.turnPhone}</En>
      </p>
      <p className="sr-only" lang="en">
        {MSG.signatureAlt}
      </p>
    </div>
  )
}
