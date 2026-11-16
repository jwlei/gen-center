const $ = id => document.getElementById(id);
function scrollReorderEdge(scroller, y, drag, now) {
  const reset = () => { drag.lastFrame = drag.edgeSince = null; drag.carry = 0; drag.edgeDirection = 0; };
  if (!scroller || scroller.scrollHeight <= scroller.clientHeight + 1) { reset(); return false; }
  const footer = $('stick').getBoundingClientRect();
  const screenBottom = footer.height && footer.top < window.innerHeight ? footer.top : window.innerHeight;
  const box = scroller.getBoundingClientRect();
  const top = Math.max(0, box.top), bottom = Math.min(screenBottom, box.bottom);
  if (bottom <= top) { reset(); return false; }
  const edge = Math.max(24, Math.min(80, (bottom - top) / 3));
  const strength = y < top + edge ? -Math.min(1, (top + edge - y) / edge)
    : y > bottom - edge ? Math.min(1, (y - bottom + edge) / edge) : 0;
  if (!strength) { reset(); return false; }
  if (drag.edgeDirection !== Math.sign(strength)) reset();
  drag.edgeDirection = Math.sign(strength);
  const elapsed = drag.lastFrame == null ? 16 : Math.min(50, now - drag.lastFrame);
  drag.lastFrame = now;
  if (drag.edgeSince == null) drag.edgeSince = now;
  const speed = (180 + 1100 * strength * strength) * Math.min(4, 1 + (now - drag.edgeSince) / 1000 * 1.2);
  drag.carry += Math.sign(strength) * speed * elapsed / 1000;
  const step = Math.trunc(drag.carry);
  drag.carry -= step;
  if (step) {
    const before = scroller.scrollTop;
    scroller.scrollTop += step;
    if (scroller.scrollTop === before) { reset(); return false; }
  }
  return true;
}
document.addEventListener('error', event => {
  const image = event.target;
  if (image.tagName !== 'IMG') return;
  if (image.dataset.fallbackSrc) {
    const fallback = image.dataset.fallbackSrc;
    delete image.dataset.fallbackSrc;
    image.src = fallback;
  } else if (image.hasAttribute('data-remove-on-error')) image.remove();
}, true);
// Feedback while a click's request is on its way (delete, move, rename, a queue's buttons...): the button pressed
// pulses until the answer is back. Only for what a click sends, so the polls and estimates that run by themselves don't.
let lastPressed = null;
const QUIET_REQUESTS = /\/api\/(status|estimate)/;
document.addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('button, a[role="button"], .icon-btn');
  // Steppers (and anything marked data-no-busy) take press after press: each sends its own, none waits on the last.
  if (button && (button.closest('.count-stepper') || button.closest('[data-no-busy]'))) { lastPressed = null; return; }
  if (button) lastPressed = { el: button, at: performance.now() };
}, true);
function markBusy(el, by) {
  el._busy = Math.max(0, (el._busy || 0) + by);
  el.classList.toggle('is-busy', el._busy > 0);
  el.setAttribute('aria-busy', String(el._busy > 0));
}
if (typeof window.fetch === 'function') {
  const plainFetch = window.fetch.bind(window);
  window.fetch = (url, options = {}) => {
    const method = String(options.method || 'GET').toUpperCase();
    const el = lastPressed && performance.now() - lastPressed.at < 1000 && method !== 'GET' && !QUIET_REQUESTS.test(String(url)) ? lastPressed.el : null;
    if (!el) return plainFetch(url, options);
    markBusy(el, 1);
    return plainFetch(url, options).finally(() => markBusy(el, -1));
  };
}
const SETTINGS = PANEL_CONFIG.settings;
let LOCAL_MODELS = PANEL_CONFIG.local_models;
let keepSectionsOpen = false;
let privateMode = !!SETTINGS.private_mode, privateChanging = false, workspaceEpoch = 0;
const privateDraftStorage = new Map();
function draftRead(key) { return privateMode ? privateDraftStorage.get(key) || null : localStorage.getItem(key); }
function draftWrite(key, value) {
  if (privateMode) privateDraftStorage.set(key, value);
  else localStorage.setItem(key, value);
}
// The workflow a side opens on: its default if one is set (built-in is '@builtin'), else null for the one last used.
function defaultWorkflow(side) {
  const chosen = (SETTINGS.default_workflow || {})[side];
  return chosen ? (chosen === '@builtin' ? '' : chosen) : null;
}
function startingWorkflow(side, remembered) {
  const chosen = defaultWorkflow(side);
  return chosen === null ? remembered() : chosen;
}
const STORE_KEY = 'autoshorts.form.v3';  // v3: privacy became public by default; older saves kept the old default
let autoScroll = true;
let folder = 'output';
let lastVideos = { output: [], uploaded: [], video: [] };
let pipeline = 'shorts';
const PIPELINE_KEY = 'comfyui-auto-gen.pipeline';

const DEFAULTS = {
  avatar_clips: PANEL_CONFIG.avatar_clips,
  avatar_clips_min: PANEL_CONFIG.avatar_clips_min,
  avatar_clips_max: PANEL_CONFIG.avatar_clips_max,
  avatar_seconds_min: PANEL_CONFIG.avatar_seconds_min,
  avatar_seconds_max: PANEL_CONFIG.avatar_seconds_max,
};

// --- Remember the last options (per browser) ---
function saveForm() {
  const data = {};
  for (const el of $('formShorts').elements) {
    if (!el.name || el.name === 'topic' || el.name === 'output' || el.name === 'seed') continue;
    data[el.name] = el.type === 'checkbox' ? el.checked : el.value;
  }
  try { draftWrite(STORE_KEY, JSON.stringify(data)); } catch (e) {}
}
function loadForm() {
  let data = {};
  try {
    data = JSON.parse(draftRead(STORE_KEY));
    if (!data) {
      data = JSON.parse(draftRead('autoshorts.form.v2'));
      if (data) delete data.privacy;
    }
  } catch (e) {}
  data = { ...DEFAULTS, ...data };
  for (const el of $('formShorts').elements) {
    if (!el.name || !(el.name in data)) continue;
    if (el.type === 'checkbox') el.checked = !!data[el.name];
    else if ([...(el.options || [])].some(o => o.value === String(data[el.name]) && !o.disabled) || !el.options) el.value = data[el.name];
  }
}
// The footer stays on the screen whatever is focused: long text is typed in the prompt editor, over it.

// Words per prompt (core.prompt_words), on the image and video forms' sliders: the range the LLM is asked for around the
// number, and what it comes to in tokens, each prompt and, for a set, all of them. The video slider's first step
// (data-auto) is Auto: each video model's own length.
function syncWords(side, count = 1) {
  const input = $(`${side}Words`), box = $(`${side}WordsBox`), out = $(`${side}WordsTokens`);
  const words = Math.round(+input.value);
  if (input.dataset.auto && words <= +input.dataset.auto) {
    $(`${side}WordsValue`).textContent = 'Auto';
    box.classList.remove('off-band');
    out.textContent = "the video model's own length";
    return;
  }
  const [lo, hi] = (input.dataset.suggested || '').split('-').map(Number);
  box.classList.toggle('off-band', words < lo || words > hi);
  const spread = +input.dataset.spread || .2, round5 = n => 5 * Math.round(n / 5);
  const each = Math.round(words * +input.dataset.perWord + +input.dataset.perVersion);
  $(`${side}WordsValue`).textContent = `${words} words`;
  out.textContent = `${round5(words * (1 - spread))}–${round5(words * (1 + spread))} words, ~${each} tokens each`
    + (count > 1 ? `, ~${(each * count).toLocaleString('en-US')} total` : '');
}
