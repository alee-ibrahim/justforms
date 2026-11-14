/**
 * Embedded (`?embed=1`, a lazy chunk): the host page sizes the frame to the form
 * (public/embed.js), so the frame never scrolls on its own. Messages carry only a height, nothing
 * about the respondent, so they go to any parent ('*'); the host checks where they came from.
 */
let sent = 0
let pending = 0

/** The form's own height: its content, not the document, which is at least as tall as the
 *  frame and so could never shrink (or would feed the frame's height back to itself). */
export const contentHeight = (root = document.getElementById('root')) =>
  root ? Math.ceil(root.getBoundingClientRect().height) : 0

/** Tells the host page the form's height: at most once a frame, and only when it changed. */
export function postHeight() {
  pending ||= requestAnimationFrame(() => {
    pending = 0
    const height = contentHeight()
    if (height && height !== sent) parent.postMessage({ type: 'justforms:resize', height: (sent = height) }, '*')
  })
}

/** Reports the form's height whenever its content changes size (pages, problems, repeaters). */
export function startEmbed(): void {
  document.documentElement.style.background = 'transparent'
  const root = document.getElementById('root')
  if (root) new ResizeObserver(postHeight).observe(root)
}
