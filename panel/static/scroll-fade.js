// --- Any box that scrolls up and down: what goes past its top or bottom fades out there ---
// As Generate's sections and the chat do (they keep their own, accordions.js and chat.js). A box is found by its own
// style (overflow-y auto or scroll), looked for as the page loads, a box opens, a fold opens or the window changes
// size; then each one's fades follow its scrolling and its size. The page itself and what's typed in are left as they are.
const FADE_OWN = '.section-body, .chat-log, textarea, select, input';
const fadeWatched = new WeakSet();
const fadeResize = typeof ResizeObserver === 'function' ? new ResizeObserver(entries => {
  for (const entry of entries) updateScrollFade(entry.target.closest('.scroll-fade') || entry.target);
}) : null;
function updateScrollFade(box) {
  if (!box || !box.classList || !box.classList.contains('scroll-fade')) return;
  box.classList.toggle('fade-above', box.scrollTop > 1);
  box.classList.toggle('fade-below', box.scrollHeight - box.clientHeight - box.scrollTop > 1);
}
function scrollsUpAndDown(el) {
  if (el === document.documentElement || el === document.body || (el.matches && el.matches(FADE_OWN))) return false;
  const overflow = window.getComputedStyle(el).overflowY;
  return overflow === 'auto' || overflow === 'scroll';
}
function findScrollFades(root = document.body) {
  if (typeof window.getComputedStyle !== 'function' || !root || !root.querySelectorAll) return;
  for (const el of [root, ...root.querySelectorAll('*')]) {
    if (fadeWatched.has(el) || !scrollsUpAndDown(el)) continue;
    fadeWatched.add(el);
    el.classList.add('scroll-fade');
    if (fadeResize) {
      fadeResize.observe(el);
      for (const child of el.children) fadeResize.observe(child);
    }
    updateScrollFade(el);
  }
}
// Scrolling doesn't bubble, but it passes the document on its way down.
document.addEventListener('scroll', e => updateScrollFade(e.target), true);
document.addEventListener('toggle', e => findScrollFades(e.target), true);
window.addEventListener('resize', () => findScrollFades());
window.addEventListener('load', () => findScrollFades());
// A box opening (showModal sets its open attribute): it and what's in it.
if (typeof MutationObserver === 'function') {
  new MutationObserver(changes => {
    for (const change of changes) if (change.target.open) findScrollFades(change.target);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['open'], subtree: true });
}
