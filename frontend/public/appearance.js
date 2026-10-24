// Studio appearance before the first paint (docs/ux/FORM-THEME-SCREENS.md section 2): light
// unless this person chose dark or "match device". A classic blocking script from this origin,
// so the CSP stays script-src 'self'. The studio re-applies it from the account once loaded.
;(function () {
  var pref = 'light'
  try {
    pref = window.localStorage.getItem('justforms:appearance') || 'light'
  } catch {
    // storage blocked: light
  }
  var dark = pref === 'dark' || (pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) document.documentElement.classList.add('dark')
})()
