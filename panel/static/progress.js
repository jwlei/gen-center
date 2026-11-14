// --- ComfyUI: an icon in Status, and all it knows a tap away ---
let lastComfy = null;
function comfyState(c) {
  return c.online ? 'running'
    : c.starting ? 'starting… (loading models)'
    : c.listening ? 'not answering'
    : c.can_start ? 'not running (Generate starts it)' : 'not running';
}
function renderComfy(c) {
  const rows = [['State', comfyState(c)]];
  if (c.online) {
    const step = c.active ? `${c.label || 'Working'}${c.max ? ` · ${c.value || 0}/${c.max}` : ''}${c.elapsed ? ` · ${fmt(c.elapsed)}` : ''}` : 'Idle';
    rows.push(['Now', step], ['In its queue', String(c.queue || 0)]);
  }
  const g = c.gpu;
  if (g) rows.push(['GPU', `${g.util}% · VRAM ${g.mem_used}/${g.mem_total}GB · ${g.power}W · ${g.temp}°C`]);
  if (c.ram) rows.push(['RAM', `${+(c.ram.total - c.ram.free).toFixed(1)}/${c.ram.total}GB used · ${c.ram.free}GB free`]);
  $('comfyFacts').innerHTML = rows.map(([name, value]) => `<dt>${name}</dt><dd>${esc(value)}</dd>`).join('');
  // What to do about it, when there's something to do.
  const low = c.ram && c.ram.free < c.ram.total * 0.1;
  const advice = c.listening && !c.online
    ? `It's running but doesn't answer${low ? ', and memory is nearly full: it is paging, so everything crawls' : ''}. It may come back; restarting ComfyUI frees it, and a stopped run continues from what it kept.`
    : low ? 'Memory is nearly full, so renders slow down as Windows pages. ComfyUI lets go of its models when a job ends.' : '';
  $('comfyAdvice').textContent = advice;
  $('comfyAdvice').hidden = !advice;
}
$('comfyStatus').addEventListener('click', e => {
  e.stopPropagation();  // The Status header around it opens the phone addresses
  if (lastComfy) renderComfy(lastComfy);
  $('comfyDialog').showModal();
});
$('comfyStatus').addEventListener('keydown', e => e.stopPropagation());
$('comfyDialogClose').addEventListener('click', () => $('comfyDialog').close());
$('comfyDialog').addEventListener('click', e => { if (e.target === $('comfyDialog')) $('comfyDialog').close(); });

// --- Header: the short status on Run, and a bar under it per job ---
// What's being made, in Status. A new one slides in, as it leaves the queue below.
// The run the title is about, and what it renders with, a tap away.
let workItem = null;
// Everything known about the run, not just its title: where it is, how long it has gone, and what ComfyUI is doing.
function runFactRows() {
  const facts = (workItem && workItem.facts) || {};
  const d = lastStatus || {}, p = d.progress || {}, c = d.comfyui || {};
  const rows = [['Workflow', facts.workflow], ['Resolution', facts.resolution], ...(facts.prompt ? [['Prompt', facts.prompt]] : [])];
  if (d.started_at) {
    rows.push(['Status', d.running ? 'Running' : d.stopped ? 'Stopped' : d.returncode ? `Failed, exit code ${d.returncode}` : 'Finished']);
    rows.push(['Started', `${d.started_at} · ${fmt(d.elapsed || 0)} ${d.running ? 'so far' : 'in all'}`]);
  }
  if (p.stage) rows.push(['Stage', `${p.stage[0]} of ${p.stage[1]}: ${p.stage[2]}${d.running ? ` · ${fmt(p.stage_elapsed || 0)}` : ''}`]);
  if (p.detail) rows.push(['Now', nowDetail(d)]);
  if (p.eta && d.running && p.eta.total_left != null) rows.push(['Estimate', `${fmtEta(p.eta.total_left)} left, done around ${clockIn(p.eta.total_left)}`]);
  if (c.connected) {
    const steps = c.max && c.value != null ? ` · Step ${c.value} of ${c.max}` : '';
    rows.push(['ComfyUI', `${c.active ? c.label || 'Working' : 'Idle'}${steps}${c.queue > 1 ? ` · ${c.queue - 1} more queued` : ''}`]);
  }
  if (d.command) rows.push(['Command', d.command]);
  return rows;
}
$('currentWork').addEventListener('click', () => {
  $('runFactsTitle').textContent = $('currentWork').textContent;
  $('runFactsList').innerHTML = runFactRows().map(([name, value]) => `<dt>${name}</dt><dd>${esc(value || 'Not known yet')}</dd>`).join('')
    + '<dt>Details</dt><dd><button type="button" id="runFactsWorkflow">Show the workflow</button></dd>';
  $('runFactsWorkflow').addEventListener('click', () => showWorkflow());
  $('runFacts').showModal();
});
$('runFactsClose').addEventListener('click', () => $('runFacts').close());
$('runFacts').addEventListener('click', e => { if (e.target === $('runFacts')) $('runFacts').close(); });
// Plays a class's animation again, from its start.
function replay(el, name) {
  if (!el || !el.classList) return;
  el.classList.remove(name);
  void el.offsetWidth;
  el.classList.add(name);
}
let lastStage = null;
// --- Status's parts come and go smoothly: each grows open and fades in as it shows, and closes and fades out as it
// hides (a copy of it does, the part itself hidden at once, so nothing that reads it is fooled), and nothing under it
// jumps. The page shows and hides them as it always has (hidden, or the hidden class); this watches for that. ---
const SMOOTH_PARTS = ['currentWork', 'currentWorkSize', 'runProgress', 'etaDetail', 'now', 'comfyNow', 'stepper', 'stageDetail',
  'uploadBox', 'uploadProgress', 'runActions', 'queuePending', 'warningRuns', 'runQueue', 'stoppedRuns', 'failedRuns', 'uploadQueue'];
const smoothShown = el => !el.hidden && !(el.classList && el.classList.contains('hidden'));
const SMOOTH_MS = 320, SMOOTH_EASE = 'cubic-bezier(.2, .8, .2, 1)';
function smoothIn(el) {
  if (el._leaving) { el._leaving.remove(); el._leaving = null; }
  const h = el.offsetHeight;
  if (!h || !el.animate) return;
  const style = window.getComputedStyle ? window.getComputedStyle(el) : {};
  el.animate([{ height: '0px', opacity: 0, marginTop: '0px', marginBottom: '0px', paddingTop: '0px', paddingBottom: '0px', overflow: 'hidden' },
    { height: `${h}px`, opacity: 1, marginTop: style.marginTop, marginBottom: style.marginBottom, paddingTop: style.paddingTop, paddingBottom: style.paddingBottom, overflow: 'hidden' }],
    { duration: SMOOTH_MS, easing: SMOOTH_EASE });
}
function smoothOut(el, copy) {
  if (!copy || !el.parentNode || !copy.animate) return;
  if (el._leaving) el._leaving.remove();
  // The copy as it was, where it was, closing; no ids, so nothing finds it.
  copy.removeAttribute('id');
  for (const inner of copy.querySelectorAll('[id]')) inner.removeAttribute('id');
  copy.setAttribute('aria-hidden', 'true');
  copy.style.pointerEvents = 'none';
  el.parentNode.insertBefore(copy, el);
  el._leaving = copy;
  const h = copy.offsetHeight;
  const leave = copy.animate([{ height: `${h}px`, opacity: 1, overflow: 'hidden' },
    { height: '0px', opacity: 0, marginTop: '0px', marginBottom: '0px', paddingTop: '0px', paddingBottom: '0px', overflow: 'hidden' }],
    { duration: SMOOTH_MS, easing: SMOOTH_EASE, fill: 'forwards' });
  leave.onfinish = () => { copy.remove(); if (el._leaving === copy) el._leaving = null; };
}
if (window.MutationObserver) {
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const watcher = new MutationObserver(records => {
    for (const el of new Set(records.map(r => r.target))) {
      const shown = smoothShown(el);
      if (shown === el._smoothShown) continue;
      el._smoothShown = shown;
      if (reduced() || document.body.classList.contains('page-loading')) continue;
      if (shown) { smoothIn(el); continue; }
      // Hidden: a copy of it, shown, closes in its place.
      const copy = el.cloneNode(true);
      copy.hidden = false;
      copy.classList.remove('hidden');
      smoothOut(el, copy);
    }
  });
  for (const id of SMOOTH_PARTS) {
    const el = $(id);
    if (!el || !el.cloneNode) continue;
    el._smoothShown = smoothShown(el);
    watcher.observe(el, { attributes: true, attributeFilter: ['hidden', 'class'] });
  }
}
// Idle: one of Gemini's nudges (panel/nudges.json), picked at random each time Status goes idle, kept while it stays so.
const NUDGES = PANEL_CONFIG.nudges;
let nudgeShown = null;
function syncNudge(idle) {
  const box = $('nudge');
  if (!idle || !NUDGES.length) { box.hidden = true; nudgeShown = null; return; }
  if (nudgeShown === null) box.textContent = nudgeShown = NUDGES[Math.floor(Math.random() * NUDGES.length)];
  box.hidden = false;
}
// Tapped: Image's Generate, with its starred preset (if one is starred), and the nudge as the prompt.
async function makeFromNudge() {
  const text = nudgeShown;
  if (!text) return;
  reopening('image');
  if (pipeline !== 'image') setPipeline('image');
  const preset = (presets.image || []).find(p => p.default);
  if (preset) applyPreset('image', preset.name);
  const prompt = $('imagePrompt');
  prompt.value = text;
  prompt.dispatchEvent(new Event('input', { bubbles: true }));
  syncImageForm();
  saveImageForm();
  if (!preset) reopened('image');
  backToGenerate('image');
}
$('nudge').addEventListener('click', makeFromNudge);
$('nudge').addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); makeFromNudge(); } });
function showWork(text) {
  const el = $('currentWork');
  el.hidden = !text;
  if (!text || el.textContent === text) return;
  el.textContent = text;
  el.classList.remove('arrive');
  void el.offsetWidth;  // So it plays again
  el.classList.add('arrive');
}
// Out of Private mode an NSFW job's own title (its prompt, mostly) isn't shown in the queues or Status: a plain one is.
const PLAIN_TITLE = 'Untitled';
function hideTitle(item) { return !privateMode && !!(item && item.nsfw); }
function workHeading(item, side) {
  const name = SIDE_NAMES[side] || 'Shorts';
  const label = (item && item.label) || 'Starting';
  const generic = /^(\d+) (?:videos?|images?)(?::\s*(.*))?$/i.exec(label);
  const count = (item && item.facts && item.facts.count) || (generic && Number(generic[1]));
  const text = hideTitle(item) ? PLAIN_TITLE : generic ? generic[2] || '' : label;
  return `${name}${count > 1 ? `(${count})` : ''}:${text ? ` ${text}` : ''}`;
}
// share is how much is done, 0 to 1, or null when that can't be told.
function inView(id) {
  const box = $(id).getBoundingClientRect();
  return box.top < window.innerHeight - $('stick').offsetHeight && box.bottom > 0;
}
// Status shows them in full, so the bars in the footer are for everywhere else.
const stripActive = { run: false, upload: false };
function syncStrips() {
  // Each only while its own bar on Status is out of sight: elsewhere, or on Status scrolled past it.
  for (const job of Object.keys(stripActive)) $(`${job}Strip`).hidden = !stripActive[job] || inView(`${job}Progress`);
  // Nothing to show: no box at all, pinned or not.
  const empty = Object.keys(stripActive).every(job => $(`${job}Strip`).hidden);
  $('headStrips').classList.toggle('empty', empty);
  $('topMain').hidden = empty;
  document.documentElement.style.setProperty('--head', `${$('stick').offsetHeight}px`);
}
// Pinned (Settings): scrolled away from the top, the bars leave their place in the header and stretch along the top of
// the screen; back at the top, they go back. Either way they ease from where they were to where they go.
let pinnedOut = false;
function syncPin() {
  const out = !!SETTINGS.pin_progress && window.scrollY > 8;
  if (out === pinnedOut) return;
  pinnedOut = out;
  const box = $('headStrips'), measure = el => (el.getBoundingClientRect ? el.getBoundingClientRect() : null);
  const style = el => (window.getComputedStyle ? window.getComputedStyle(el) : {});
  const from = measure(box), padFrom = style(box).padding;
  // Its own transitions off while it changes place: measured mid-transition, where it goes would read as where it was,
  // and the two would step against each other. One animation moves it, its padding with it.
  box.classList.add('pinning');
  document.body.classList.toggle('strips-out', out);
  syncOpened();
  const to = measure(box), padTo = style(box).padding;
  const done = () => box.classList.remove('pinning');
  if (!from || !to || !box.animate || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { done(); return; }
  // In the coordinates of what holds it now: the screen once out, the header's spot once back.
  const base = out ? { top: 0, left: 0 } : measure($('topMain'));
  const at = (r, padding) => ({ top: `${r.top - base.top}px`, left: `${r.left - base.left}px`, width: `${r.width}px`, ...(padding ? { padding } : {}) });
  const move = box.animate([at(from, padFrom), at(to, padTo)], { duration: 340, easing: 'cubic-bezier(.2, .8, .2, 1)' });
  move.onfinish = move.oncancel = done;
}
window.addEventListener('scroll', syncPin, { passive: true });
// A status in two lines: "Rendering clip - The Descent to Knees, 5s", then "Clip 6 of 8" left and "0:19" right.
// The count is split off a detail such as "Clip 6 of 8: The Descent, 5s" or Shorts' "Clip 2 of 5 - scene 3, 6s".
// What the run is making now ("Image 2 of 4: its title"): only the count when its title is hidden (hideTitle).
function nowDetail(data) {
  const detail = (data.progress || {}).detail || '';
  const [count, what] = splitCount(detail);
  return count && what && hideTitle(data.queue && data.queue.current) ? count : detail;
}
function splitCount(detail) {
  const m = /^((?:Clip|Image|Scene|Video) \d+ of \d+)(?::\s*|\s+-\s+)?(.*)$/.exec(detail || '');
  return m ? [m[1], m[2]] : ['', detail || ''];
}
// With no count there is no second line: the time goes at the right of the first.
function statusHtml(first, count = '', time = '', timeTitle = '') {
  const clock = time ? `<span class="time"${timeTitle ? ` title="${esc(timeTitle)}"` : ''}>${esc(time)}</span>` : '';
  if (!count) return first || time ? `<div class="status-foot"><span class="status-first">${esc(first)}</span>${clock}</div>` : '';
  return (first ? `<div class="status-first">${esc(first)}</div>` : '')
    + `<div class="status-foot"><span class="status-count">${esc(count)}</span>${clock}</div>`;
}
// The footer bar says it all in one line; Status already has the stage and the time so
// far, so its bar only adds how far along and when it ends.
function setStrip(job, show, strip, status, share) {
  stripActive[job] = show;
  $(`${job}Progress`).hidden = !show;
  if (!show) return;
  const pct = share === null ? '' : `${Math.round(share * 100)}%`;
  for (const [where, say] of [['Strip', strip], ['Progress', status]]) {
    const left = job === 'run' && where === 'Progress';
    $(`${job}${where}Text`).textContent = left ? [pct, say.text].filter(Boolean).join(' · ') : say.text;
    $(`${job}${where}Right`).textContent = left ? say.right : [pct, say.right].filter(Boolean).join(' · ');
    const bar = $(`${job}${where}Bar`);
    bar.parentElement.classList.toggle('busy', share === null);
    bar.style.width = `${share === null ? 30 : Math.round(share * 100)}%`;
  }
  // Folded, the bar says only how far along; opened, two lines: what it is and which of how many, then what it is doing
  // and when it ends.
  $(`${job}StripPct`).textContent = pct;
  $(`${job}StripCount`).textContent = strip.count || '';
  $(`${job}StripHint`).textContent = strip.line || '';
  $(`${job}StripTotal`).textContent = strip.total || '';
  if (job === 'upload') $('uploadProgressHint').innerHTML = status.hint;
}
const STRIP_OPEN_MS = 5000;
const stripTimers = {};
function foldStrip(job) {
  clearTimeout(stripTimers[job]);
  $(`${job}Strip`).classList.remove('open');
  $(`${job}Strip`).setAttribute('aria-expanded', 'false');
  syncOpened();
}
// Opened, the box they sit in has the page's background behind them, so what they say reads over the page.
// It opens to the screen's full width, edge to edge over the icons beside it (pinned, it is full width already), and
// back to its place when folded.
function syncOpened() {
  const box = $('headStrips'), opened = ['run', 'upload'].some(job => $(`${job}Strip`).classList.contains('open'));
  box.classList.toggle('opened', opened);
  const main = $('topMain'), wide = opened && !document.body.classList.contains('strips-out') && main.getBoundingClientRect;
  const at = wide ? main.getBoundingClientRect() : null, screen = document.documentElement.clientWidth || window.innerWidth;
  box.style.left = at ? `${-at.left}px` : '';
  box.style.right = at ? `${at.right - screen}px` : '';
}
// Opened, a tap anywhere else, or a scroll, folds it again.
function foldStrips() { for (const job of ['run', 'upload']) if ($(`${job}Strip`).classList.contains('open')) foldStrip(job); }
document.addEventListener('click', e => { if (!(e.target.closest && e.target.closest('#headStrips'))) foldStrips(); });
window.addEventListener('scroll', foldStrips, { passive: true });
function tapStrip(job) {
  if ($(`${job}Strip`).classList.contains('open')) {
    foldStrip(job);
    if (WIDE.matches) $('runCard').scrollIntoView({ behavior: 'smooth' }); else showPage('status');
    return;
  }
  $(`${job}Strip`).classList.add('open');
  $(`${job}Strip`).setAttribute('aria-expanded', 'true');
  syncOpened();
  clearTimeout(stripTimers[job]);
  stripTimers[job] = setTimeout(() => foldStrip(job), STRIP_OPEN_MS);
}
for (const job of ['run', 'upload']) {
  $(`${job}Strip`).addEventListener('click', () => tapStrip(job));
  $(`${job}Strip`).addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tapStrip(job); }
  });
}
function renderStrips(data) {
  const p = data.progress || {}, stage = p.stage || [], eta = p.eta;
  const video = p.run && p.run[1] > 1 ? `Video ${p.run[0]} of ${p.run[1]}` : '';
  const left = eta ? `${fmtEta(eta.total_left)} left` : fmt(data.elapsed);
  // Everything queued after it too, when there is more.
  const all = eta && queueAhead > eta.total_left + 30 ? ` · the whole queue around ${clockIn(queueAhead)}` : '';
  const total = eta ? `Done around ${clockIn(eta.total_left)}${all}` : `${fmt(data.elapsed)} so far`;
  const [count, what] = splitCount(nowDetail(data));
  const current = data.queue && data.queue.current;
  const doing = [stage[2] || 'Starting', [p.action, what].filter(Boolean).join(' - ') || (count ? '' : STAGE_HINTS[stage[2]] || '')].filter(Boolean).join(' · ');
  setStrip('run', data.running,
    { text: current ? workHeading(current, data.pipeline) : stage[2] || 'Starting', count: [video, count].filter(Boolean).join(' · '), line: doing,
      right: left + (runsQueued ? ` · +${runsQueued} queued` : ''), total },
    { text: p.run && p.run[1] > 1 ? `Video ${p.run[0]} of ${p.run[1]}` : '', right: eta ? `${left}, done around ${clockIn(eta.total_left)}${etaShift(eta) ? ` (${etaShift(eta)})` : ''}` : '' },
    eta && eta.adjusted_total ? 1 - eta.total_left / eta.adjusted_total : null);
  const up = data.upload, at = (up.progress || {}).upload;
  const sending = statusHtml(at ? `Uploading - ${at[2]}` : 'Writing the title and description', at ? `Video ${at[0]} of ${at[1]}` : '',
    fmt(up.elapsed || 0));
  setStrip('upload', up.running,
    { text: at ? `Uploading ${at[2]}` : 'Writing the title and description', count: at ? `Video ${at[0]} of ${at[1]}` : '', line: at ? 'Sending to YouTube' : 'Preparing', right: fmt(up.elapsed),
      total: `${fmt(up.elapsed || 0)} so far` },
    { text: at ? 'Uploading' : 'Getting ready', right: '', hint: sending },
    at && at[1] > 1 ? (at[0] - 1) / at[1] : null);
  syncStrips();
}
