/**
 * "Download as PNG" for an Insights chart: the chart's SVG with its computed colours and
 * fonts written inline (CSS variables don't travel with a lone SVG), drawn on a canvas at 2x
 * with the card's background and the question as a title.
 */

const PROPS = ['fill', 'stroke', 'stroke-width', 'font-family', 'font-size', 'font-weight', 'opacity'] as const

function inline(source: Element, target: Element) {
  const style = getComputedStyle(source)
  const parts = PROPS.map((p) => `${p}:${style.getPropertyValue(p)}`)
  target.setAttribute('style', parts.join(';'))
  const a = source.children
  const b = target.children
  for (let i = 0; i < a.length && i < b.length; i++) inline(a[i], b[i])
}

export async function chartPng(container: HTMLElement, title: string): Promise<Blob | null> {
  const svg = container.querySelector('svg.recharts-surface')
  if (!(svg instanceof SVGSVGElement)) return null
  const { width, height } = svg.getBoundingClientRect()
  const clone = svg.cloneNode(true) as SVGSVGElement
  inline(svg, clone)
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))
  const data = new XMLSerializer().serializeToString(clone)
  const img = new Image()
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(data)}`
  await img.decode()

  const scale = 2
  const pad = 24
  const titleH = 36
  const canvas = document.createElement('canvas')
  canvas.width = (width + pad * 2) * scale
  canvas.height = (height + pad * 2 + titleH) * scale
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.scale(scale, scale)
  const card = getComputedStyle(container.closest('[data-slot=card]') ?? document.body)
  ctx.fillStyle = card.backgroundColor || '#fff'
  ctx.fillRect(0, 0, width + pad * 2, height + pad * 2 + titleH)
  ctx.fillStyle = getComputedStyle(document.body).color || '#000'
  ctx.font = `600 15px ${getComputedStyle(document.body).fontFamily}`
  ctx.direction = 'inherit'
  ctx.fillText(title.length > 90 ? `${title.slice(0, 89)}…` : title, pad, pad + 14, width)
  ctx.drawImage(img, pad, pad + titleH, width, height)
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
}

export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function fileName(label: string): string {
  const base = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 50)
  return `${base || 'chart'}.png`
}
