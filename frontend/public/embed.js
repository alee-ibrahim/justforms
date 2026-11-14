// JustForms embed helper (docs/features.md, "Embedding a form"). Load it on the page that
// shows a form in an iframe:
//
//   <iframe src="https://forms.example.org/my-form?embed=1" title="My form"
//           style="width:100%;height:800px;border:0" loading="lazy"></iframe>
//   <script src="https://forms.example.org/embed.js" async></script>
//
// Every iframe of this JustForms site on the page is then sized to its form, so it never
// scrolls on its own, and the page scrolls back to the form's top when the respondent moves to
// another page of the form or submits it. Without this script the iframe still works: it keeps
// its own height and scrolls inside.
//
// Only messages from this script's own origin, sent by one of those iframes, are acted on; they
// can set that iframe's height and scroll the page to it, nothing else.
;(function () {
  var script = document.currentScript
  if (!script || !script.src || window.__justformsEmbed) return
  var origin = new URL(script.src, location.href).origin
  window.__justformsEmbed = true

  function frameOf(source) {
    var frames = document.getElementsByTagName('iframe')
    for (var i = 0; i < frames.length; i++) if (frames[i].contentWindow === source) return frames[i]
    return null
  }

  window.addEventListener('message', function (e) {
    if (e.origin !== origin || !e.data || typeof e.data !== 'object') return
    var frame = frameOf(e.source)
    if (!frame) return
    if (e.data.type === 'justforms:resize') {
      var height = Number(e.data.height)
      if (!isFinite(height) || height <= 0 || height > 100000) return
      // Sized to the form from now on: no scrollbar of its own.
      frame.setAttribute('scrolling', 'no')
      frame.style.overflow = 'hidden'
      frame.style.height = Math.ceil(height) + 'px'
    } else if (e.data.type === 'justforms:top') {
      // Only when the form's top is out of view; the host page's scroll-margin-top is kept (for
      // a fixed header).
      var top = frame.getBoundingClientRect().top
      if (top < 0 || top > window.innerHeight) frame.scrollIntoView({ block: 'start' })
    }
  })
})()
