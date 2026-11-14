// Classic scripts share form bindings; startup.js initializes the panel after all topics load.
function presetValues(side) {
  const values = {};
  for (const el of $(SIDE_FORMS[side]).elements) {
    if (!el.name || el.type === 'file' || el.type === 'hidden' || el.disabled || PRESET_SKIP.includes(el.name) || /_role$/.test(el.name)) continue;
    values[el.name] = el.type === 'checkbox' ? el.checked : el.value;
  }
  return values;
}
function samePreset(preset, now) {
  return Object.keys(preset).every(key => String(preset[key] ?? '') === String(now[key] ?? ''));
}
function sameForm(a, b) {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every(key => String(a[key] ?? '') === String(b[key] ?? ''));
}
function presetFeedback(side, message, error = false) {
  const feedback = $(`${side}PresetFeedback`);
  feedback.textContent = message;
  feedback.dataset.error = String(error);
  const trigger = $(`${side}PresetOpen`);
  trigger.dataset.error = String(error);
  trigger.title = error ? message : 'Select, save or favourite a preset';
}
const presetBusy = new Set(), presetPending = {};
function capturePresetEditors() {
  return Object.fromEntries(Object.keys(SIDE_FORMS).map(side => [side, {
    pending: presetPending[side] ? { ...presetPending[side] } : null,
    name: $(`${side}PresetName`).value,
    nameHidden: $(`${side}PresetName`).hidden,
    hidden: $(`${side}PresetEditor`).hidden,
    confirm: $(`${side}PresetConfirm`).textContent,
    feedback: $(`${side}PresetFeedback`).textContent,
    error: $(`${side}PresetFeedback`).dataset.error,
  }]));
}
function restorePresetEditors(editors) {
  for (const [side, state] of Object.entries(editors)) {
    if (state.pending) presetPending[side] = { ...state.pending }; else delete presetPending[side];
    $(`${side}PresetName`).value = state.name;
    $(`${side}PresetName`).hidden = state.nameHidden;
    $(`${side}PresetEditor`).hidden = state.hidden;
    $(`${side}PresetConfirm`).textContent = state.confirm;
    presetFeedback(side, state.feedback, state.error === 'true');
  }
}
function closePresetEditor(side) {
  delete presetPending[side];
  $(`${side}PresetEditor`).hidden = true;
  $(`${side}PresetName`).value = '';
}
function editPreset(side, pending) {
  presetPending[side] = pending;
  const name = $(`${side}PresetName`), confirm = $(`${side}PresetConfirm`);
  name.hidden = pending.kind !== 'save';
  name.value = '';
  confirm.textContent = pending.kind === 'save' ? 'Save' : 'Apply & clear prompt';
  $(`${side}PresetEditor`).hidden = false;
  if (pending.kind === 'save') {
    presetFeedback(side, 'Save these settings under a name. Prompts and media are not included.');
    name.focus();
  } else {
    presetFeedback(side, `Apply "${pending.name}"? This replaces settings and clears the current prompt.`);
  }
}
async function presetRequest(body) {
  const side = body.side;
  const epoch = workspaceEpoch;
  if (presetBusy.has(side)) { presetFeedback(side, 'A preset change is still saving. Please wait.'); return false; }
  presetBusy.add(side);
  presetFeedback(side, 'Saving...');
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), POLL_TIMEOUT);
  try {
    const response = await fetch('/api/presets', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      signal: abort.signal,
    });
    const data = await response.json();
    if (response.ok === false || !data.ok || !data.presets) throw new Error(data.error || 'Could not save the preset.');
    presets = { ...presets, ...data.presets };
    Object.keys(SIDE_FORMS).forEach(syncPresets);
    if (epoch === workspaceEpoch) presetFeedback(side, body.delete ? 'Preset deleted.' : 'Preset saved.');
    return true;
  } catch (e) {
    if (epoch === workspaceEpoch) presetFeedback(side, abort.signal.aborted
      ? 'Preset save timed out. Reload presets before retrying; the save may have reached the panel.'
      : e.message || 'Could not reach the panel. Try again.', true);
    return false;
  } finally {
    presetBusy.delete(side);
    clearTimeout(timer);
  }
}
async function confirmPresetEdit(side) {
  const epoch = workspaceEpoch;
  const pending = presetPending[side];
  if (!pending || presetBusy.has(side)) return;
  if (pending.kind === 'apply') {
    clearPrompt(side);
    applyPreset(side, pending.name);
    closePresetEditor(side);
    presetFeedback(side, 'Preset applied. Previous prompt cleared.');
    return;
  }
  const name = $(`${side}PresetName`).value.trim();
  if (!name) { presetFeedback(side, 'Enter a preset name.', true); return; }
  if ((presets[side] || []).some(p => p.name === name) && pending.overwrite !== name) {
    pending.overwrite = name;
    $(`${side}PresetConfirm`).textContent = 'Replace saved preset';
    presetFeedback(side, `"${name}" already exists. Confirm to replace its settings.`);
    return;
  }
  const values = presetValues(side);
  if (await presetRequest({ side, name, values }) && epoch === workspaceEpoch) {
    presetPicked[side] = { name, values };
    syncPresets(side);
    closePresetEditor(side);
  }
}
function wirePresetActions() {
  document.addEventListener('click', async e => {
    const target = e.target.closest && e.target.closest('[data-preset-open], [data-preset-close], [data-preset-save], [data-preset-delete], [data-preset-default], [data-preset-confirm], [data-preset-cancel]');
    if (!target) return;
    if (target.dataset.presetOpen) {
      const side = target.dataset.presetOpen;
      syncPresets(side);
      $(`${side}PresetDialog`).showModal();
      return;
    }
    if (target.dataset.presetClose) {
      $(`${target.dataset.presetClose}PresetDialog`).close();
      return;
    }
    if (target.dataset.presetConfirm) { await confirmPresetEdit(target.dataset.presetConfirm); return; }
    if (target.dataset.presetCancel) {
      const side = target.dataset.presetCancel;
      closePresetEditor(side);
      syncPresets(side);
      presetFeedback(side, 'Cancelled. Your prompt and settings are unchanged.');
      return;
    }
    if (target.dataset.presetSave) { editPreset(target.dataset.presetSave, { kind: 'save' }); return; }
    const side = target.dataset.presetDefault || target.dataset.presetDelete;
    const name = $(`${side}Preset`).value;
    if (!name) return;
    if (target.dataset.presetDefault) {
      await presetRequest({ side, name, default: target.getAttribute('aria-pressed') !== 'true' });
    } else if (secondTap(target)) {
      await presetRequest({ side, name, delete: true });
    } else {
      presetFeedback(side, `Tap delete again to remove "${name}".`);
    }
  });
  for (const side of Object.keys(SIDE_FORMS)) {
    $(`${side}PresetName`).addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); confirmPresetEdit(side); }
      if (e.key === 'Escape') { e.preventDefault(); closePresetEditor(side); }
    });
  }
}

// --- Presets: a side's settings under a name, kept by the panel so every device has them ---
// Everything you'd set again, but not what each run is about: its prompt, narration, seed, topic, files and their roles.
const PRESET_SKIP = ['prompt', 'narration', 'seed', 'topic', 'output', 'review'];
const SIDE_SYNC = { shorts: () => syncForm(), video: () => syncVideoForm(), image: () => syncImageForm() };
const SIDE_SAVE = { shorts: () => saveForm(), video: () => saveVideoForm(), image: () => saveImageForm() };
const OPTION_BOXES = { shorts: 'shortsOptionsBox', video: 'videoOptionsBox', image: 'imageOptionsBox' };
let presets = { shorts: [], video: [], image: [] };
// The preset last picked on each side, and the form as picking it left it: a field it couldn't set, such as an option
// the workflow no longer has, no longer makes the picker fall back to None.
const presetPicked = {};
// The workflow label names the matching preset; its modal holds the management controls.
function syncPresets(side) {
  const select = $(`${side}Preset`), list = presets[side] || [], now = presetValues(side);
  const key = JSON.stringify(list.map(p => p.name));
  if (select.dataset.key !== key) {
    select.dataset.key = key;
    select.innerHTML = '<option value="">None</option>' + list.map(p => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
  }
  const picked = presetPicked[side] && list.find(p => p.name === presetPicked[side].name);
  const match = picked && (samePreset(picked.values, now) || sameForm(presetPicked[side].values, now))
    ? picked : list.find(p => samePreset(p.values, now));
  select.value = match ? match.name : '';
  $(`${side}PresetOpen`).textContent = match ? match.name : 'Preset';
  document.querySelector(`[data-preset-save="${side}"]`).hidden = false;
  document.querySelector(`[data-preset-delete="${side}"]`).hidden = !match;
  const star = document.querySelector(`[data-preset-default="${side}"]`), isDefault = !!(match && match.default);
  star.hidden = !match;
  star.setAttribute('aria-pressed', String(isDefault));
  star.title = isDefault ? 'Favourite preset: used when this side opens. Tap to remove favourite.' : 'Favourite this preset: use it when this side opens';
  star.setAttribute('aria-label', star.title);
}
let presetsLoaded = false;
const defaultsDue = new Set(['shorts', 'video', 'image']);
const WORKFLOW_PICKERS = { shorts: 'workflow', video: 'videoWorkflow', image: 'imageWorkflow' };
// A side's default preset, set once as the page opens: after its workflows are listed, so the one it names can be picked.
function applyDefaultPreset(side) {
  if (!presetsLoaded || !defaultsDue.has(side) || !$(WORKFLOW_PICKERS[side]).dataset.key) return;
  defaultsDue.delete(side);
  const preset = (presets[side] || []).find(p => p.default);
  if (preset) applyPreset(side, preset.name, true);
}
// A form filled from something made, or a queued job: the starred preset isn't put over it, and the picker shows a
// preset only where one holds what the form now does, not the one picked before.
function reopening(side) { defaultsDue.delete(side); }
function reopened(side) {
  delete presetPicked[side];
  syncPresets(side);
}
async function loadPresets() {
  try {
    const response = await fetch('/api/presets');
    const data = await response.json();
    if (response.ok === false || !data.presets) throw new Error(data.error || 'Invalid preset response.');
    presets = { ...presets, ...data.presets };
  } catch (e) {
    for (const side of Object.keys(SIDE_FORMS)) presetFeedback(side, `Presets unavailable: ${e.message} Reload to retry.`, true);
    return;
  }
  presetsLoaded = true;
  Object.keys(SIDE_FORMS).forEach(syncPresets);
  Object.keys(SIDE_FORMS).forEach(applyDefaultPreset);
}
function applyPreset(side, name, atStart = false) {
  const preset = (presets[side] || []).find(p => p.name === name);
  if (!preset) return;
  const form = $(SIDE_FORMS[side]), values = preset.values;
  const set = el => {
    if (!(el.name in values) || el.type === 'file' || (el.type === 'hidden' && el.name !== 'opt_additional_loras')) return;
    if (el.type === 'checkbox') el.checked = !!values[el.name];
    else if (!el.options || [...el.options].some(o => o.value === String(values[el.name]))) el.value = values[el.name];
  };
  // The workflow first: what the rest offers follows from it. A default workflow in the settings beats the starred preset's.
  const keepWorkflow = atStart && defaultWorkflow(side) !== null;
  if (form.elements.workflow && !keepWorkflow) set(form.elements.workflow);
  SIDE_SYNC[side]();
  [...form.elements].filter(el => !el.name.startsWith('opt_') && !(keepWorkflow && el.name === 'workflow')).forEach(set);
  SIDE_SYNC[side]();
  const box = $(OPTION_BOXES[side]);
  [...form.elements].filter(el => el.name.startsWith('opt_')).forEach(set);
  renderLoraStack(box);
  if (box.dataset.workflow) rememberOptions(box);
  SIDE_SYNC[side]();
  SIDE_SAVE[side]();
  presetPicked[side] = { name, values: presetValues(side) };
  syncPresets(side);
}
// Wired at start-up, once the forms and their names are all known.
function wirePresets() {
  wirePresetActions();
  for (const side of Object.keys(SIDE_FORMS)) {
    $(`${side}Preset`).addEventListener('change', e => {
      closePresetEditor(side);
      if (!e.target.value) return;
      if ($(PROMPT_FIELDS[side]).value.trim()) {
        editPreset(side, { kind: 'apply', name: e.target.value });
        return;
      }
      clearPrompt(side);
      applyPreset(side, e.target.value);
      presetFeedback(side, 'Preset applied.');
    });
    // Not for the picker itself: picking fires "input" before "change", and checking then put it back to None
    // before the preset it named was set.
    for (const kind of ['change', 'input']) $(SIDE_FORMS[side]).addEventListener(kind, e => { if (e.target !== $(`${side}Preset`)) syncPresets(side); });
  }
}
