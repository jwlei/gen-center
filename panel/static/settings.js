// --- Settings (the gear in the header) ---
const SETTINGS_BUILTIN = { shorts: 'LTX23_I2V_T2V_shorts', video: 'LTX23_I2V_T2V', image: 'Automatic' };
const settingsDialog = $('settingsDialog');
function settingsNote(text, bad) {
  $('settingsNote').hidden = !text;
  $('settingsNote').textContent = text || '';
  $('settingsNote').style.color = bad ? 'var(--err)' : '';
}
async function saveSettings(changes, note = settingsNote) {
  try {
    const body = await (await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes) })).json();
    if (!body.ok) { note(body.error || 'Could not save it.', true); return false; }
    Object.assign(SETTINGS, body.settings);
    note('');
    return true;
  } catch (e) { note('Could not save it.', true); return false; }
}
const themeDialog = $('themeDialog');
function themeNote(text, bad) {
  $('themeNote').hidden = !text;
  $('themeNote').textContent = text || '';
  $('themeNote').style.color = bad ? 'var(--err)' : '';
}
function syncTheme() {
  document.documentElement.dataset.theme = SETTINGS.theme;
  for (const choice of themeDialog.querySelectorAll('.theme-choice')) {
    const selected = choice.dataset.theme === SETTINGS.theme;
    choice.setAttribute('aria-pressed', String(selected));
    if (selected) $('themePicker').textContent = choice.querySelector('.theme-name').textContent;
  }
}
syncTheme();
$('themePicker').addEventListener('click', () => { themeNote(''); themeDialog.showModal(); });
$('themeClose').addEventListener('click', () => themeDialog.close());
themeDialog.addEventListener('click', async e => {
  if (e.target === themeDialog) { themeDialog.close(); return; }
  const choice = e.target.closest ? e.target.closest('.theme-choice') : null;
  if (!choice || choice.dataset.theme === SETTINGS.theme) return;
  const choices = themeDialog.querySelectorAll('.theme-choice');
  for (const button of choices) button.disabled = true;
  if (await saveSettings({ theme: choice.dataset.theme }, themeNote)) {
    syncTheme();
    themeDialog.close();
  }
  for (const button of choices) button.disabled = false;
});
function formatBytes(n) {
  const gb = n / 2 ** 30;
  return gb >= 100 ? `${Math.round(gb)} GB` : gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(n / 2 ** 20)} MB`;
}
function compactLocalModel(model) {
  let name = model.label.replace(/\s*\(vision\)/i, '').replace(/(?:[-_ ]uncensored|[-_ ]heretic)/gi, '')
    .replace(/^gemma[-_]?4[-_]?12b[-_]?it/i, 'Gemma 4')
    .replace(/^gemma[-_]?4[-_]?12b/i, 'Gemma 4')
    .replace(/^qwen3[-_]?14b/i, 'Qwen3 14B');
  const quant = name.match(/[-_.](I?Q\d(?:_[A-Za-z0-9]+)+|BF16)$/i);
  if (quant) name = name.slice(0, -quant[0].length);
  name = name.replace(/[-_]+/g, ' ').trim();
  const suffix = (quant ? ` ${quant[1]}` : '') + (model.vision ? '-v' : '');
  const limit = 22 - suffix.length;
  if (name.length > limit) name = name.slice(0, Math.max(1, limit - 1)).trimEnd() + '…';
  return name + suffix;
}
function localModelLabel(model) {
  const speed = Number.isFinite(model.tokens_per_second) ? model.tokens_per_second.toFixed(1) : '—';
  return `${compactLocalModel(model)} · ${speed} tok/s`;
}
function renderLocalModels() {
  for (const [id, fallback] of [['h3Model', SETTINGS.h3_model], ['localLlmModel', SETTINGS.local_llm_model || SETTINGS.h3_model],
                                 ['videoLocalModel', SETTINGS.local_llm_model || SETTINGS.h3_model],
                                 ['imageLocalModel', SETTINGS.local_llm_model || SETTINGS.h3_model]]) {
    const select = $(id), selected = select.value || fallback;
    select.innerHTML = LOCAL_MODELS.map(model => `<option value="${esc(model.id)}" title="${esc(model.label)}">${esc(localModelLabel(model))}</option>`).join('');
    select.value = selected;
    if (select.value !== selected) select.add(new Option(`${selected} (missing)`, selected, false, true));
  }
}
async function refreshLocalModels() {
  const response = await fetch('/api/local-models');
  if (!response.ok) throw new Error('Could not load local models.');
  const data = await response.json();
  if (!data.ok || !Array.isArray(data.models)) throw new Error(data.error || 'Could not load local models.');
  LOCAL_MODELS = data.models;
  renderLocalModels();
}
async function fillSettings() {
  $('lowPriority').checked = !!SETTINGS.low_priority;
  $('titleSource').value = SETTINGS.title_source || 'off';
  $('pinProgress').checked = !!SETTINGS.pin_progress;
  $('h3Model').value = SETTINGS.h3_model;
  $('localLlmModel').value = SETTINGS.local_llm_model || SETTINGS.h3_model;
  try { await refreshLocalModels(); } catch (e) { settingsNote(e.message || 'Could not load local models.', true); }
  reserveGb = reserveSaved();
  showReserve();
  const edit = SETTINGS.edit_preset || '';
  $('editPreset').innerHTML = '<option value="">Qwen-Image 2.1 edit workflow</option>'
    + (presets.image || []).map(p => `<option value="${esc(p.name)}">Preset: ${esc(p.name)}</option>`).join('');
  $('editPreset').value = edit;
  if ($('editPreset').value !== edit) $('editPreset').add(new Option(`Preset: ${edit} (gone)`, edit, false, true));
  const toVideo = SETTINGS.edit_video_preset || '';
  $('editVideoPreset').innerHTML = '<option value="">Video\'s own workflow</option>'
    + (presets.video || []).map(p => `<option value="${esc(p.name)}">Preset: ${esc(p.name)}</option>`).join('');
  $('editVideoPreset').value = toVideo;
  if ($('editVideoPreset').value !== toVideo) $('editVideoPreset').add(new Option(`Preset: ${toVideo} (gone)`, toVideo, false, true));
  for (const side of ['shorts', 'video', 'image']) {
    const select = document.getElementById('default' + side[0].toUpperCase() + side.slice(1));
    const chosen = (SETTINGS.default_workflow || {})[side] || '';
    select.innerHTML = `<option value="">Last one used</option><option value="@builtin">${SETTINGS_BUILTIN[side]}</option>`;
    select.value = chosen;
    fetch('/api/workflows?pipeline=' + side).then(r => r.json()).then(data => {
      const usable = data.workflows.filter(w => !w.problem);
      select.innerHTML += usable.map(w => `<option value="${esc(w.name)}">${esc(w.label)}</option>`).join('');
      select.value = chosen;
      if (select.value !== chosen) select.add(new Option(chosen, chosen, false, true));
    }).catch(() => {});
  }
  try {
    const { disk } = await (await fetch('/api/settings')).json();
    $('diskBox').innerHTML = !disk ? '<div class="hint">The disk could not be read.</div>' : `
      <div class="bar"><div style="width:${Math.round((1 - disk.free / disk.total) * 100)}%"></div></div>
      <div class="disk-line"><span><b>${formatBytes(disk.free)}</b> free of ${formatBytes(disk.total)} (${esc(disk.drive)})</span><span>Outputs take ${formatBytes(disk.outputs)}</span></div>`;
  } catch (e) { $('diskBox').innerHTML = '<div class="hint">The disk could not be read.</div>'; }
}
$('settingsBtn').addEventListener('click', e => {
  e.preventDefault();
  settingsNote('');
  fillSettings();
  settingsDialog.showModal();
});
$('settingsClose').addEventListener('click', () => settingsDialog.close());
settingsDialog.addEventListener('click', e => { if (e.target === settingsDialog) settingsDialog.close(); });
$('lowPriority').addEventListener('change', () => saveSettings({ low_priority: $('lowPriority').checked }));
$('titleSource').addEventListener('change', () => saveSettings({ title_source: $('titleSource').value }));
$('pinProgress').addEventListener('change', async () => { await saveSettings({ pin_progress: $('pinProgress').checked }); syncPin(); });
$('h3Model').addEventListener('change', () => saveSettings({ h3_model: $('h3Model').value }));
$('localLlmModel').addEventListener('change', () => saveSettings({ local_llm_model: $('localLlmModel').value }));
$('editPreset').addEventListener('change', () => saveSettings({ edit_preset: $('editPreset').value }));
$('editVideoPreset').addEventListener('change', () => saveSettings({ edit_video_preset: $('editVideoPreset').value }));
// Free RAM ComfyUI keeps, in whole GB, 3 unless set. Saved with Set, used from ComfyUI's next start.
const RESERVE_LEAST = 1, RESERVE_MOST = 24, RESERVE_DEFAULT = 3;
let reserveGb = RESERVE_DEFAULT;
const reserveSaved = () => Math.round(SETTINGS.reserve_ram_gb || RESERVE_DEFAULT);
function showReserve() {
  $('reserveRamValue').textContent = `${reserveGb} GB`;
  $('reserveDown').disabled = reserveGb <= RESERVE_LEAST;
  $('reserveUp').disabled = reserveGb >= RESERVE_MOST;
  $('reserveSet').hidden = reserveGb === reserveSaved();
}
// Shut down when the queue is empty: kept by the server for this session only.
function renderPoweroff(p) {
  if (!p) return;
  $('poweroff').checked = p.armed;
  $('poweroffNote').textContent = p.seconds_left != null
    ? `Shutting down in ${p.seconds_left} s. Untick to cancel.`
    : 'This session only: it isn\'t saved. You get a minute to cancel it.';
}
$('poweroff').addEventListener('change', async () => {
  try {
    renderPoweroff(await (await fetch('/api/poweroff', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ armed: $('poweroff').checked }) })).json());
  } catch (e) { settingsNote('Could not reach the panel.', true); }
});
$('reserveDown').addEventListener('click', () => { reserveGb = Math.max(RESERVE_LEAST, reserveGb - 1); showReserve(); });
$('reserveUp').addEventListener('click', () => { reserveGb = Math.min(RESERVE_MOST, reserveGb + 1); showReserve(); });
$('reserveSet').addEventListener('click', async () => {
  await saveSettings({ reserve_ram_gb: reserveGb });
  showReserve();  // Set: nothing waits any more
  $('restartComfy').classList.add('pulse');
});
settingsDialog.addEventListener('change', e => {
  if (e.target.dataset && e.target.dataset.side) saveSettings({ default_workflow: { [e.target.dataset.side]: e.target.value } });
});
settingsDialog.addEventListener('click', async e => {
  const copy = e.target.closest ? e.target.closest('.copy-url') : null;
  if (!copy) return;
  try { await navigator.clipboard.writeText(copy.dataset.url); }
  catch (err) {
    const box = document.createElement('textarea');
    box.value = copy.dataset.url;
    document.body.appendChild(box);
    box.select();
    document.execCommand('copy');
    box.remove();
  }
  copy.textContent = 'Copied';
  setTimeout(() => { copy.textContent = 'Copy'; }, 1500);
});
// After a restart, the page waits for the server to answer again, then reloads onto the new code.
async function reloadWhenBack() {
  // The button says it, in yellow, rather than a line under it.
  const button = $('restartPanel');
  button.classList.add('restarting');
  button.disabled = true;
  button.querySelector('span').textContent = 'Restarting';
  button.setAttribute('aria-label', 'Restarting panel');
  settingsNote('');
  await new Promise(r => setTimeout(r, 3000));
  for (let i = 0; i < 60; i++) {
    try { await fetch('/api/status', { cache: 'no-store' }); location.reload(); return; } catch (e) {}
    await new Promise(r => setTimeout(r, 1000));
  }
  button.classList.remove('restarting');
  button.disabled = false;
  button.querySelector('span').textContent = 'Restart';
  button.setAttribute('aria-label', 'Restart panel');
  settingsNote('The panel did not come back. Start it with start_webapp.pyw.', true);
}
$('restartPanel').addEventListener('click', async () => {
  if (!confirmTap('restartPanel', 'Restart panel')) return;
  try {
    const response = await fetch('/restart/panel', { method: 'POST' });
    const body = await response.json();
    if (!body.ok) { settingsNote(body.error || 'Could not restart.', true); return; }
  } catch (e) { return; }
  reloadWhenBack();
});
// With ComfyUI off there is nothing to restart: the same button starts it.
let comfyOff = false;
const armed = {};
function syncComfyButton(c) {
  comfyOff = !c.online && !c.listening;
  const label = $('restartComfy').querySelector('span');
  const text = comfyOff ? (c.starting ? 'Wait' : 'Start') : 'Comfy';
  if (!armed.restartComfy) label.textContent = text;
  $('restartComfy').setAttribute('aria-label', c.starting ? 'Starting ComfyUI' : comfyOff ? 'Start ComfyUI' : 'Restart ComfyUI');
  $('restartComfy').disabled = comfyOff && (c.starting || !c.can_start);
  // Starting or restarting: in yellow, as Restart panel is while it restarts.
  $('restartComfy').classList.toggle('restarting', (comfyOff && !!c.starting) || !!c.restarting);
  $('forceRestartComfy').classList.toggle('restarting', !!c.restarting || (comfyOff && !!c.starting));
  if (!armed.forceRestartComfy) {
    $('forceRestartComfy').querySelector('span').textContent = c.restarting ? 'Wait' : 'Force';
    $('forceRestartComfy').setAttribute('aria-label', c.restarting ? 'Restarting ComfyUI' : 'Force restart ComfyUI');
  }
  if (comfyOff) $('restartComfy').classList.remove('pulse');
}
$('restartComfy').addEventListener('click', async () => {
  if (comfyOff) {
    const button = $('restartComfy'), failed = () => { button.disabled = false; button.classList.remove('restarting'); };
    button.disabled = true;
    button.classList.add('restarting');
    try {
      const body = await (await fetch('/comfyui/start', { method: 'POST' })).json();
      if (!body.ok) { settingsNote(body.error || 'Could not start it.', true); failed(); }
      else { settingsNote(''); poll(); }
    } catch (error) { settingsNote('Could not reach the panel. Try again.', true); failed(); }
    return;
  }
  if (!confirmTap('restartComfy', 'Restart ComfyUI')) return;
  $('restartComfy').classList.remove('pulse');
  const body = await (await fetch('/restart/comfyui', { method: 'POST' })).json();
  settingsNote(body.ok ? '' : body.error || 'Could not restart it.', !body.ok);
});
// Force: ComfyUI closed and started again at once, even while a run is going or the panel believes one is. That run
// fails and is tried once more (exit code 1 restarts and retries it).
$('forceRestartComfy').addEventListener('click', async () => {
  if (!confirmTap('forceRestartComfy', 'Force restart ComfyUI', 3)) return;
  $('restartComfy').classList.remove('pulse');
  try {
    const body = await (await fetch('/restart/comfyui', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: true }) })).json();
    settingsNote(body.ok ? '' : body.error || 'Could not restart it.', !body.ok);
    if (body.ok) poll();
  } catch (error) { settingsNote('Could not reach the panel. Try again.', true); }
});
// The buttons ask for more taps within a few seconds instead of a box: the first arms it, the last does it (a force
// restart takes three, and says how many are left).
const tapsLeft = {}, tapLabels = {};
function disarmTap(id) {
  const button = $(id), text = button.querySelector('span');
  clearTimeout(armed[id]); delete armed[id]; delete tapsLeft[id];
  if (text && tapLabels[id] !== undefined) text.textContent = button.dataset.shortLabel || tapLabels[id];
  if (tapLabels[id] !== undefined) button.setAttribute('aria-label', tapLabels[id]);
  button.classList.remove('armed');
  if (button.dataset) delete button.dataset.taps;
}
function confirmTap(id, label, taps = 2) {
  const button = $(id), text = button.querySelector('span');
  tapLabels[id] = label;
  if (tapsLeft[id] <= 1) { disarmTap(id); return true; }
  tapsLeft[id] = tapsLeft[id] ? tapsLeft[id] - 1 : taps - 1;
  clearTimeout(armed[id]);
  button.classList.add('armed');
  // For longer confirmations, keep the visible label short and announce the tap count accessibly.
  if (taps > 2) {
    if (button.dataset && button.dataset.shortLabel) button.setAttribute('aria-label', `${label}: ${tapsLeft[id]} more taps`);
    else text.textContent = tapsLeft[id] === 1 ? 'Tap once more' : `Tap ${tapsLeft[id]} more times`;
    if (button.dataset) button.dataset.taps = tapsLeft[id];
  }
  armed[id] = setTimeout(() => disarmTap(id), 4000);
  return false;
}
// A button waiting for its confirming tap goes back to what it was as soon as a tap lands anywhere else.
document.addEventListener('click', e => {
  const tapped = e.target && e.target.closest ? e.target.closest('button') : null;
  for (const button of document.querySelectorAll('button.armed')) {
    if (button === tapped) continue;
    if (button.id && armed[button.id] !== undefined) disarmTap(button.id); else disarm(button);
  }
}, true);

function clipCount(n) { return `${n} ${n === 1 ? 'clip' : 'clips'}`; }
function filmLengthEstimate(seconds, adjusted) {
  return `${seconds !== adjusted ? '≈' : ''}${fmt(adjusted)} · ${clipCount(shotCount(adjusted))}`;
}
// As the planner counts them: the shortest, longest and usual clip on the workflow's video model...
function modelClips() { return workflowClips[$('videoWorkflow').value] || BUILT_IN_CLIPS; }
// ...within the clip length chosen (pipelines/video/planner.py clip_seconds, the same sums).
function videoClips() {
  const [shortest, longest, usual] = modelClips(), chosen = /^(\d+)-(\d+)$/.exec($('videoClipSeconds').value || '');
  if (!chosen) return [shortest, longest, usual];
  const low = Math.max(shortest, +chosen[1]), high = Math.min(longest, +chosen[2]);
  return low <= high ? [low, high, Math.min(high, Math.max(low, Math.floor((low + high + 1) / 2)))] : [shortest, longest, usual];
}
// The slider spans what the model makes; at its full span nothing is chosen, and the model's own usual length holds.
function syncVideoClips(moved) {
  const [shortest, longest, usual] = modelClips(), box = $('videoClipRange'), [low, high] = box.querySelectorAll('input');
  const fixed = $('videoClipFixed').checked;
  for (const input of [low, high]) { input.min = shortest; input.max = longest; }
  if (!moved) {
    const chosen = /^(\d+)-(\d+)$/.exec($('videoClipSeconds').value || '');
    low.value = fixed ? Math.max(shortest, Math.min(longest, chosen ? +chosen[1] : usual)) : (chosen ? chosen[1] : shortest);
    high.value = fixed ? low.value : (chosen ? chosen[2] : longest);
  }
  if (fixed) high.value = low.value;
  high.hidden = fixed;
  high.disabled = fixed;
  low.setAttribute('aria-label', fixed ? 'Fixed clip length in seconds' : 'Shortest clip in seconds');
  const [from, to] = syncRange('videoClipRange', moved);
  $('videoClipSeconds').value = !fixed && from <= shortest && to >= longest ? '' : `${from}-${to}`;
  $('videoClipText').textContent = fixed ? `${from}s` : `${from}-${to}s`;
  $('videoClipFixedButton').setAttribute('aria-pressed', String(fixed));
  $('videoClipFixedHint').hidden = !fixed;
}
$('videoClipFixedButton').addEventListener('click', () => {
  const fixed = $('videoClipFixed');
  fixed.checked = !fixed.checked;
  if (fixed.checked) {
    const [, , usual] = videoClips();
    $('videoClipSeconds').value = `${usual}-${usual}`;
  } else $('videoClipSeconds').value = '';
  syncVideoForm();
  saveVideoForm();
  fixed.dispatchEvent(new Event('change', { bubbles: true }));
});
function shotCount(seconds) {
  const [shortest, longest, usual] = videoClips();
  const count = Math.max(Math.ceil(seconds / longest), Math.round(seconds / usual), 1);
  return seconds >= shortest ? Math.max(1, Math.min(count, Math.floor(seconds / shortest))) : 1;
}
