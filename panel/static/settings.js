// --- Settings (the gear in the header) ---
const SETTINGS_BUILTIN = { shorts: 'LTX23_I2V_T2V_shorts', video: 'LTX23_I2V_T2V', image: 'Automatic' };
const settingsDialog = $('settingsDialog');
function settingsNote(text, bad) {
  // In Settings, and under the power buttons in the box the dots open, where Restart, Comfy and Power are now.
  for (const id of ['settingsNote', 'powerNote']) {
    if (!$(id)) continue;
    $(id).hidden = !text;
    $(id).textContent = text || '';
    $(id).style.color = bad ? 'var(--err)' : '';
  }
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
  // The phone's bars (and the installed app's) in the theme's background too.
  const bar = document.querySelector('meta[name="theme-color"]');
  const background = typeof getComputedStyle === 'function' ? getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() : '';
  if (bar && bar.setAttribute && background) bar.setAttribute('content', background);
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
  // The panel's own short name (panel/settings.py short_name): family, what sets it apart, quantisation.
  if (model.short) return model.short;
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
// The local models as a select's options, in a group for each family (one sees images, one doesn't); the full folder
// name is each one's tooltip.
function localModelOptions() {
  const groups = new Map();
  for (const model of LOCAL_MODELS) {
    const group = model.group || '';
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(`<option value="${esc(model.id)}" title="${esc(model.label)}">${esc(localModelLabel(model))}</option>`);
  }
  return [...groups].map(([group, options]) => group ? `<optgroup label="${esc(group)}">${options.join('')}</optgroup>` : options.join('')).join('');
}
function renderLocalModels() {
  for (const [id, fallback] of [['h3Model', SETTINGS.h3_model], ['localLlmModel', SETTINGS.local_llm_model || SETTINGS.h3_model],
                                 ['videoLocalModel', SETTINGS.local_llm_model || SETTINGS.h3_model],
                                 ['imageLocalModel', SETTINGS.local_llm_model || SETTINGS.h3_model]]) {
    const select = $(id), selected = select.value || fallback;
    select.innerHTML = localModelOptions();
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
  $('topProgress').checked = SETTINGS.top_progress !== false;
  $('pinProgress').disabled = SETTINGS.top_progress === false;
  $('statusProgress').checked = !!SETTINGS.status_progress;
  $('themeBoxes').checked = SETTINGS.theme_boxes !== false;
  $('pageSwipe').checked = SETTINGS.page_swipe !== false;
  $('pageAnimation').value = SETTINGS.page_animation || 'push';
  $('workflowSwitch').value = SETTINGS.workflow_switch || 'default';
  $('loraRange').value = SETTINGS.lora_range || 'author';
  syncPageSwipe();
  $('pageSpeed').value = SETTINGS.page_speed || 'normal';
  showGpuGuard();
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
    // The image side has no built-in one any more (Automatic is gone): the model used last, or a workflow named here.
    select.innerHTML = `<option value="">Last one used</option>${side === 'image' ? '' : `<option value="@builtin">${SETTINGS_BUILTIN[side]}</option>`}`;
    select.value = chosen;
    workflowList(side).then(data => {
      const usable = data.workflows.filter(w => !w.problem);
      select.innerHTML += usable.map(w => `<option value="${esc(w.name)}">${esc(w.label)}</option>`).join('');
      select.value = chosen;
      if (select.value !== chosen) select.add(new Option(chosen, chosen, false, true));
    }).catch(() => {});
  }
}
$('settingsBtn').addEventListener('click', e => {
  e.preventDefault();
  settingsNote('');
  fillSettings();
  settingsDialog.showModal();
  // On the section it was last on, its line under its name.
  $('settingsTabGlider').dataset.place = '';
  showSettingsSection(settingsSection, 0);
});
// --- Its sections: General, Theme, Models, Workflows, Machine, Connection, one at a time ---
// A tap on one's name shows it; a swipe left or right goes to the next or the one before, round in a loop. It comes in from the side
// it's on, as Generate's sections do, and the line under the names glides to it. Kept for this browser.
const SETTINGS_SECTIONS = ['general', 'theme', 'models', 'workflows', 'machine', 'connection'], SETTINGS_SECTION_KEY = 'gen-center.settings-section';
let settingsSection = 'general';
try { if (SETTINGS_SECTIONS.includes(localStorage.getItem(SETTINGS_SECTION_KEY))) settingsSection = localStorage.getItem(SETTINGS_SECTION_KEY); }
catch (e) {}
function showSettingsSection(name, direction) {
  if (!SETTINGS_SECTIONS.includes(name)) return;
  settingsSection = name;
  try { localStorage.setItem(SETTINGS_SECTION_KEY, name); } catch (e) {}
  for (const section of document.querySelectorAll('[data-settings-section]')) section.hidden = section.dataset.settingsSection !== name;
  const buttons = [...$('settingsTabs').querySelectorAll('[data-settings-tab]')];
  for (const button of buttons) button.setAttribute('aria-selected', String(button.dataset.settingsTab === name));
  if (typeof placeUnderline === 'function') placeUnderline($('settingsTabGlider'), buttons.find(b => b.dataset.settingsTab === name), $('settingsTabs'));
  const shown = document.querySelector(`[data-settings-section="${name}"]`), body = shown && shown.parentNode;
  if (body) body.scrollTop = 0;
  if (name === 'workflows') showWorkflowCheck();
  if (direction && shown && shown.animate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    shown.animate([{ transform: `translateX(${direction > 0 ? '24%' : '-24%'})`, opacity: 0 }, { transform: 'none', opacity: 1 }],
                  { duration: 260, easing: 'cubic-bezier(.3, .7, .3, 1)' });
  }
}
$('settingsTabs').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('[data-settings-tab]');
  if (!button || button.dataset.settingsTab === settingsSection) return;
  showSettingsSection(button.dataset.settingsTab, SETTINGS_SECTIONS.indexOf(button.dataset.settingsTab) - SETTINGS_SECTIONS.indexOf(settingsSection));
});
// A swipe across its sections, not one along a slider or a box being typed in, and more across than down.
let settingsSwipe = null;
settingsDialog.addEventListener('touchstart', e => {
  const target = e.target;
  const own = target.closest && target.closest('input[type=range], textarea, input[type=text], .settings-tabs');
  settingsSwipe = e.touches.length === 1 && !own ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
}, { passive: true });
settingsDialog.addEventListener('touchend', e => {
  const start = settingsSwipe, end = e.changedTouches && e.changedTouches[0];
  settingsSwipe = null;
  if (!start || !end) return;
  const dx = end.clientX - start.x, dy = end.clientY - start.y;
  if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
  // Round in a loop: on from the last is the first, back from the first the last.
  const count = SETTINGS_SECTIONS.length, next = (SETTINGS_SECTIONS.indexOf(settingsSection) + (dx < 0 ? 1 : -1) + count) % count;
  showSettingsSection(SETTINGS_SECTIONS[next], dx < 0 ? 1 : -1);
});
window.addEventListener('resize', () => { if (settingsDialog.open) { $('settingsTabGlider').dataset.place = ''; showSettingsSection(settingsSection, 0); } });
$('settingsClose').addEventListener('click', () => settingsDialog.close());
settingsDialog.addEventListener('click', e => { if (e.target === settingsDialog) settingsDialog.close(); });
$('lowPriority').addEventListener('change', () => saveSettings({ low_priority: $('lowPriority').checked }));
$('pageSwipe').addEventListener('change', async () => { await saveSettings({ page_swipe: $('pageSwipe').checked }); syncPageSwipe(); });
$('pageAnimation').addEventListener('change', () => saveSettings({ page_animation: $('pageAnimation').value }));
$('workflowSwitch').addEventListener('change', () => saveSettings({ workflow_switch: $('workflowSwitch').value }));
// The ranges beside each LoRA follow at once.
$('loraRange').addEventListener('change', async () => {
  if (await saveSettings({ lora_range: $('loraRange').value })) Object.values(OPTION_BOXES).forEach(box => syncLoraRanges($(box)));
});
// --- Workflows: what the panel made of each workflow saved in ComfyUI (/api/workflow-check) ---
// Each a line: its name, its model family, and whether it's offered; tapped, the node each input was found on, so a
// wrong guess is seen and a tag (gc:prompt...) put on the right node in ComfyUI. Asked for each time the tab opens.
const FIELD_NAMES = { prompt: 'Prompt', negative: 'Negative prompt', width: 'Width', height: 'Height', seconds: 'Clip length (s)',
                      frames: 'Frames', fps: 'Frame rate', audio: 'Audio', text_to_video: 'Text-to-video switch' };
const fieldName = field => FIELD_NAMES[field] || field.replace(/^image(?:_(\d+))?$/, (_, n) => `Image ${n || 1}`)
  .replace(/^ref_(video|audio)(?:_(\d+))?$/, (_, kind, n) => `Reference ${kind} ${n || 1}`);
function workflowCheckHtml(w) {
  const family = w.family_label ? `<span class="workflow-check-family">${esc(w.family_label)}</span>` : '<span class="workflow-check-family unknown">Family unknown</span>';
  const head = `<summary><span class="workflow-check-name">${esc(w.label)}</span><span class="workflow-check-side">${esc(w.pipeline)}</span>${family}`
    + `<span class="workflow-check-state" data-ok="${!w.problem}">${w.problem ? "Can't run" : 'Ready'}</span></summary>`;
  if (w.problem) return `<details class="workflow-check-item">${head}<div class="workflow-check-problem">${esc(w.problem)}</div></details>`;
  const rows = (w.inputs || []).map(i => `<tr><th>${esc(fieldName(i.field))}</th><td>${esc(i.title || i.type)} <span class="workflow-check-node">#${esc(i.node)}.${esc(i.input)}</span></td>`
    + `<td>${i.tagged ? '<span class="workflow-check-tag">tag</span>' : 'guess'}</td></tr>`).join('');
  return `<details class="workflow-check-item">${head}<table class="workflow-check-inputs">${rows}</table>`
    + `<div class="hint">${w.options} setting${w.options === 1 ? '' : 's'} on the form.</div></details>`;
}
// Refresh reads them from ComfyUI there and then, with the model families it can load now, and the forms follow.
async function showWorkflowCheck(refresh = false) {
  const box = $('workflowCheck');
  if (!box.innerHTML || refresh) box.innerHTML = `<div class="hint">${refresh ? 'Reading them from ComfyUI...' : 'Reading the workflows...'}</div>`;
  $('workflowCheckRefresh').disabled = true;
  try {
    const data = await (await fetch('/api/workflow-check' + (refresh ? '?refresh=1' : ''))).json();
    if (!data.ok) throw new Error(data.error || 'Could not read the workflows.');
    $('workflowCheckTags').textContent = (data.tags || []).join(', ');
    if (refresh) {
      $('workflowCheckWhen').textContent = `Read at ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
      $('workflowFamilies').innerHTML = data.families ? data.families.map(f => `<span class="family-chip" data-known="${f.known}" title="${esc(f.kind || 'new')}">${esc(f.label)}${f.known ? '' : ' (new)'}</span>`).join('')
        : `<span class="hint">${esc(data.families_problem || 'ComfyUI is off: start it, then refresh.')}</span>`;
      loadImageWorkflows();
      loadVideoWorkflows();
      loadWorkflows();
    }
    const offline = data.online ? '' : '<div class="hint">ComfyUI is off: these are the workflows it had last time.</div>';
    box.innerHTML = offline + (data.workflows.length ? data.workflows.map(workflowCheckHtml).join('')
      : '<div class="hint">No workflows are saved in ComfyUI yet. Save one there and it appears here.</div>');
  } catch (e) {
    box.innerHTML = `<div class="hint" data-error="true">${esc(e.message || 'Could not read the workflows.')}</div>`;
  } finally {
    $('workflowCheckRefresh').disabled = false;
  }
}
$('workflowCheckRefresh').addEventListener('click', () => showWorkflowCheck(true));
$('pageSpeed').addEventListener('change', () => saveSettings({ page_speed: $('pageSpeed').value }));
$('titleSource').addEventListener('change', () => saveSettings({ title_source: $('titleSource').value }));
$('pinProgress').addEventListener('change', async () => { await saveSettings({ pin_progress: $('pinProgress').checked }); syncPin(); });
$('topProgress').addEventListener('change', async () => {
  await saveSettings({ top_progress: $('topProgress').checked });
  $('pinProgress').disabled = !$('topProgress').checked;
  syncStrips();
  syncPin();
});
$('themeBoxes').addEventListener('change', async () => {
  if (await saveSettings({ theme_boxes: $('themeBoxes').checked })) {
    if (SETTINGS.theme_boxes === false) document.documentElement.dataset.boxes = 'off'; else delete document.documentElement.dataset.boxes;
  }
});
$('statusProgress').addEventListener('change', async () => { await saveSettings({ status_progress: $('statusProgress').checked }); syncStatusFill(runShare); });
// GPU heat guard: restart MSI Afterburner above one temperature, again only once cooled to the other (panel/gpu_guard.py).
// A page from before a panel restart has none of these: the rest of Settings must still work.
function showGpuGuard() {
  if (!$('gpuGuard')) return;
  $('gpuGuard').checked = SETTINGS.gpu_guard !== false;
  $('gpuRestartAbove').value = SETTINGS.gpu_restart_above ?? 78;
  $('gpuRearmAt').value = SETTINGS.gpu_rearm_at ?? 75;
  $('gpuProfile').value = String(SETTINGS.gpu_profile ?? 3);
  for (const id of ['gpuRestartAbove', 'gpuRearmAt', 'gpuProfile']) $(id).disabled = !$('gpuGuard').checked;
}
async function saveGpuGuard(changes) {
  await saveSettings(changes);
  showGpuGuard();  // Refused (cool-down not below restart, out of range): back to what is saved
}
// Whether MSI Afterburner is running (the status's afterburner, from the heat guard's last check): null, not known.
function renderAfterburner(running) {
  if (!$('afterburnerState')) return;
  const known = running === true || running === false;
  $('afterburnerDot').className = 'dot ' + (running === true ? 'ok' : running === false ? 'fail' : '');
  $('afterburnerText').textContent = !known ? 'Afterburner: not known' : running ? 'Afterburner running' : 'Afterburner not running';
  $('afterburnerState').classList.toggle('off', running === false);
  // Start is for when it isn't running; while it is, there is nothing to start.
  $('startAfterburner').disabled = running === true;
}
if ($('gpuGuard')) {
  $('gpuGuard').addEventListener('change', () => saveGpuGuard({ gpu_guard: $('gpuGuard').checked }));
  $('gpuRestartAbove').addEventListener('change', () => saveGpuGuard({ gpu_restart_above: Number($('gpuRestartAbove').value) }));
  $('gpuRearmAt').addEventListener('change', () => saveGpuGuard({ gpu_rearm_at: Number($('gpuRearmAt').value) }));
  $('gpuProfile').addEventListener('change', () => saveGpuGuard({ gpu_profile: Number($('gpuProfile').value) }));
  $('restartAfterburner').addEventListener('click', async () => {
    const button = $('restartAfterburner');
    if (!confirmTap('restartAfterburner', 'Restart Afterburner')) return;
    button.disabled = true;
    settingsNote('Restarting MSI Afterburner…');
    try {
      const body = await (await fetch('/restart/afterburner', { method: 'POST' })).json();
      settingsNote(body.ok ? `MSI Afterburner restarted with profile ${body.profile}.` : body.error || 'Could not restart it.', !body.ok);
      if (body.ok) renderAfterburner(true);
    } catch (error) { settingsNote('Could not reach the panel. Try again.', true); }
    button.disabled = false;
  });
  // Start: one tap, as starting it stops nothing.
  $('startAfterburner').addEventListener('click', async () => {
    const button = $('startAfterburner');
    button.disabled = true;
    settingsNote('Starting MSI Afterburner…');
    try {
      const body = await (await fetch('/start/afterburner', { method: 'POST' })).json();
      settingsNote(body.ok ? (body.started ? `MSI Afterburner started with profile ${body.profile}.` : 'MSI Afterburner is already running.')
        : body.error || 'Could not start it.', !body.ok);
      if (body.ok) { renderAfterburner(true); return; }
    } catch (error) { settingsNote('Could not reach the panel. Try again.', true); }
    button.disabled = false;
  });
}
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
// Restart's first tap grows a menu up from it with Force restart; a second tap on Restart restarts as it always has.
let restartMenuTimer = null;
function openRestartMenu() {
  const menu = $('restartMenu');
  menu.classList.remove('closing');
  menu.hidden = false;
  $('restartPanel').setAttribute('aria-expanded', 'true');
  // Goes again with Restart's confirming tap, a little after it would have.
  clearTimeout(restartMenuTimer);
  restartMenuTimer = setTimeout(closeRestartMenu, 6000);
}
function closeRestartMenu() {
  const menu = $('restartMenu');
  clearTimeout(restartMenuTimer);
  if (menu.hidden || menu.classList.contains('closing')) return;
  menu.classList.add('closing');
  $('restartPanel').setAttribute('aria-expanded', 'false');
  setTimeout(() => {
    if (menu.classList.contains('closing')) { menu.hidden = true; menu.classList.remove('closing'); }
  }, 150);
}
document.addEventListener('click', e => {
  if (!$('restartMenu').hidden && !(e.target.closest && e.target.closest('#restartMenu, #restartPanel'))) closeRestartMenu();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeRestartMenu(); });
if (typeof settingsDialog !== 'undefined') settingsDialog.addEventListener('close', closeRestartMenu);
async function restartPanel(force) {
  closeRestartMenu();
  try {
    const response = await fetch('/restart/panel', force
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: true }) }
      : { method: 'POST' });
    const body = await response.json();
    if (!body.ok) { settingsNote(body.error || 'Could not restart.', true); return; }
  } catch (e) { return; }
  reloadWhenBack();
}
$('restartPanel').addEventListener('click', () => {
  if (!confirmTap('restartPanel', 'Restart panel')) { openRestartMenu(); return; }
  restartPanel(false);
});
// Force: the run or upload going stopped first, then the panel restarted, however stuck it is.
$('forceRestartPanel').addEventListener('click', () => {
  if (!confirmTap('forceRestartPanel', 'Force restart panel')) { openRestartMenu(); return; }
  restartPanel(true);
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
// Comfy's first tap grows a menu down from it with Force, as Restart's does; a second tap on Comfy restarts it.
let comfyMenuTimer = null;
function openComfyMenu() {
  const menu = $('comfyMenu');
  menu.classList.remove('closing');
  menu.hidden = false;
  $('restartComfy').setAttribute('aria-expanded', 'true');
  clearTimeout(comfyMenuTimer);
  comfyMenuTimer = setTimeout(closeComfyMenu, 6000);
}
function closeComfyMenu() {
  const menu = $('comfyMenu');
  clearTimeout(comfyMenuTimer);
  if (menu.hidden || menu.classList.contains('closing')) return;
  menu.classList.add('closing');
  $('restartComfy').setAttribute('aria-expanded', 'false');
  setTimeout(() => {
    if (menu.classList.contains('closing')) { menu.hidden = true; menu.classList.remove('closing'); }
  }, 150);
}
document.addEventListener('click', e => {
  if (!$('comfyMenu').hidden && !(e.target.closest && e.target.closest('#comfyMenu, #restartComfy'))) closeComfyMenu();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeComfyMenu(); });
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
  if (!confirmTap('restartComfy', 'Restart ComfyUI')) { openComfyMenu(); return; }
  closeComfyMenu();
  $('restartComfy').classList.remove('pulse');
  const body = await (await fetch('/restart/comfyui', { method: 'POST' })).json();
  settingsNote(body.ok ? '' : body.error || 'Could not restart it.', !body.ok);
});
// Force: ComfyUI closed and started again at once, even while a run is going or the panel believes one is. That run
// fails and is tried once more (exit code 1 restarts and retries it).
$('forceRestartComfy').addEventListener('click', async () => {
  // Its taps keep the menu up while they're asked for.
  if (!confirmTap('forceRestartComfy', 'Force restart ComfyUI', 3)) { openComfyMenu(); return; }
  closeComfyMenu();
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
