/**
 * The code a website pastes to show the form. Inline: an iframe that works on its own (fixed
 * height, scrolls inside), plus /embed.js, which sizes it to the form so only the page scrolls.
 * Full page: the normal form page (background, footer) filling the window.
 */
export function embedCode(mode: 'inline' | 'full', url: string, title: string): string {
  const t = title.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
  if (mode === 'full')
    return `<iframe src="${url}" title="${t}" style="position:fixed;inset:0;width:100%;height:100%;border:0"></iframe>`
  const origin = new URL(url, window.location.href).origin
  return (
    `<iframe src="${url}?embed=1" title="${t}" style="display:block;width:100%;height:800px;border:0" loading="lazy"></iframe>\n` +
    `<script src="${origin}/embed.js" async></script>`
  )
}
