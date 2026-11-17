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
// Feedback while a click's request is on its way (delete, move, rename, a queue's buttons, opening a prompt or a set's
// settings...): the button pressed pulses until the answer is back. Only for what a click asks for, so the polls,
// estimates and graphs that run by themselves don't.
let lastPressed = null;
const QUIET_REQUESTS = /\/api\/(status|estimate|temperatures|page-error)\b/;
// A click that asks for one thing after another (a set, then its workflow's options) pulses through them all: a
// request that ends keeps the button busy a moment longer, and the next one it starts in that time is still its own.
const BUSY_GRACE_MS = 200;
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
// Asked for ahead (prefetch): what a button is about to open, from the moment a finger is on it or the viewer shows
// its item, so the answer is on its way, or here, by the time it's asked for. Each is used once, for a while; anything
// sent that changes something drops them all, as one may no longer be so.
const prefetched = new Map(), PREFETCH_MS = 15000;
let plainFetch = null;
function prefetch(url) {
  if (!plainFetch) return;
  const kept = prefetched.get(url);
  if (kept && performance.now() - kept.at < PREFETCH_MS) return;
  const promise = plainFetch(url);
  promise.catch(() => { if (prefetched.get(url) && prefetched.get(url).promise === promise) prefetched.delete(url); });
  prefetched.set(url, { at: performance.now(), promise });
}
function takePrefetched(url, options) {
  const method = String(options.method || 'GET').toUpperCase();
  if (method !== 'GET') { prefetched.clear(); return null; }
  const kept = prefetched.get(String(url));
  if (!kept) return null;
  prefetched.delete(String(url));
  return performance.now() - kept.at < PREFETCH_MS ? kept.promise : null;
}
if (typeof window.fetch === 'function') {
  plainFetch = window.fetch.bind(window);
  const send = (url, options) => takePrefetched(url, options) || plainFetch(url, options);
  window.fetch = (url, options = {}) => {
    const pressed = lastPressed;
    const el = pressed && performance.now() - pressed.at < 1000 && !QUIET_REQUESTS.test(String(url)) ? pressed.el : null;
    if (!el) return send(url, options);
    markBusy(el, 1);
    return send(url, options).finally(() => {
      if (lastPressed === pressed) pressed.at = performance.now();
      setTimeout(() => markBusy(el, -1), BUSY_GRACE_MS);
    });
  };
}
// A finger on a button that opens a saved run (its prompts, or its settings back in Generate): its run asked for now.
const PREFETCH_BUTTONS = '[data-shots], [data-again-set], [data-again-film], [data-config]';
document.addEventListener('pointerdown', e => {
  const button = e.target.closest && e.target.closest(PREFETCH_BUTTONS);
  if (!button || button.disabled || typeof runUrl !== 'function') return;
  const d = button.dataset;
  const id = d.shots || d.againSet || d.againFilm || d.config;
  if (!id) return;
  if (d.config && d.pipeline === 'shorts') prefetch(`/shorts-runs/${encodeURIComponent(id)}/form`);
  else prefetch(d.againSet ? `/image-runs/${encodeURIComponent(id)}` : d.againFilm ? `/runs/${encodeURIComponent(id)}` : runUrl(id));
}, true);
// The saved workflows each side lists, kept from the last time: answered at once, and asked again behind, any change
// handed to onFresh (the side's loader, to draw it again). So opening a run's settings doesn't wait on the list.
const workflowLists = {};
async function workflowList(side, onFresh) {
  const kept = workflowLists[side];
  const asked = fetch('/api/workflows?pipeline=' + side).then(r => r.json()).then(data => {
    if (data && Array.isArray(data.workflows)) workflowLists[side] = data;
    return data;
  });
  if (!kept) return asked;
  asked.then(data => { if (onFresh && data && Array.isArray(data.workflows) && JSON.stringify(data) !== JSON.stringify(kept)) onFresh(data); }).catch(() => {});
  return kept;
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
// --- Steppers (− and +): held down, they keep stepping, faster and faster ---
// One step as it's pressed, as a tap does; held past HOLD_DELAY_MS, it steps again and again, each wait shorter than the
// last, down to HOLD_FASTEST_MS. Each step is the button's own click, so every stepper goes on doing what it does.
// The click the browser sends as it's let go is the one already counted, not one more.
const HOLD_DELAY_MS = 400, HOLD_FIRST_MS = 180, HOLD_FASTEST_MS = 25, HOLD_SPEEDUP = .82;
let heldStepper = null;
function stepperOf(target) {
  const button = target && target.closest && target.closest('.count-stepper button, button[data-lora-step]');
  return button && !button.disabled ? button : null;
}
function releaseStepper() {
  if (!heldStepper) return;
  clearTimeout(heldStepper.timer);
  heldStepper = null;
}
document.addEventListener('pointerdown', e => {
  const button = stepperOf(e.target);
  if (!button || (e.pointerType === 'mouse' && e.button !== 0)) return;
  releaseStepper();
  const held = heldStepper = { button, repeated: false, wait: HOLD_FIRST_MS, timer: 0 };
  const step = () => {
    if (heldStepper !== held || button.disabled) { releaseStepper(); return; }
    held.repeated = true;
    held.synthetic = true;
    button.click();
    held.synthetic = false;
    held.wait = Math.max(HOLD_FASTEST_MS, held.wait * HOLD_SPEEDUP);
    held.timer = setTimeout(step, held.wait);
  };
  held.timer = setTimeout(step, HOLD_DELAY_MS);
});
for (const name of ['pointerup', 'pointercancel', 'blur']) (name === 'blur' ? window : document).addEventListener(name, () => {
  // Let go after it repeated: its own click, coming next, isn't a step more.
  if (heldStepper && heldStepper.repeated) heldStepper.swallow = true, clearTimeout(heldStepper.timer);
  else releaseStepper();
});
document.addEventListener('pointerout', e => { if (heldStepper && e.target === heldStepper.button && !heldStepper.button.contains(e.relatedTarget)) releaseStepper(); });
document.addEventListener('click', e => {
  if (!heldStepper || !heldStepper.swallow || heldStepper.synthetic || stepperOf(e.target) !== heldStepper.button) return;
  e.stopImmediatePropagation();
  e.preventDefault();
  heldStepper = null;
}, true);
// A long press on a stepper is a hold, not a phone's text selection or menu.
document.addEventListener('contextmenu', e => { if (stepperOf(e.target)) e.preventDefault(); });
