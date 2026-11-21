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
// A workflow's own default as the form shows it: what the form doesn't show (an option greyed out, or Private mode's)
// is no difference.
function sameShown(preset, now) {
  return Object.keys(preset).every(key => !(key in now) || String(preset[key] ?? '') === String(now[key] ?? ''));
}

// --- Workflow defaults: each workflow saved in ComfyUI is a preset of its own at once ---
// Made from its settings as saved there (and, where its model family has a default preset, that preset's on top), and
// listed under Workflow defaults. Saved over, it's kept as you saved it; deleted, it's ComfyUI's again. Choosing the
// workflow applies it, unless Settings says to keep what was last set. Nothing here knows any one workflow or model:
// the server says each workflow's family (core/model_families.py).
const sideWorkflows = side => ((workflowLists[side] || {}).workflows || []).filter(w => !w.problem);
const currentWorkflow = side => $(WORKFLOW_PICKERS[side]).value;
// A workflow's options at their defaults, by their names in the form, as useDefaultOptions sets them.
function optionDefaultValues(options) {
  const values = {};
  for (const option of options || []) {
    if (option.role || option.kind === 'lora_stack') continue;
    if (option.kind === 'switch') values[`opt_${option.id}`] = option.default === '1';
    else if (option.kind === 'strength') {
      const active = option.default !== '0';
      values[`opt_${option.id}_on`] = active;
      values[`opt_${option.id}_strength`] = active ? option.default : option.usual || '1';
    } else values[`opt_${option.id}`] = option.default;
  }
  return values;
}
// What a workflow keeps as its own under its family's default: how it samples and the files it runs (and what goes under
// them), as a turbo and a full workflow of one model differ in just those.
function ownedByWorkflow(options) {
  const own = new Set((options || []).filter(o => SAMPLING_OPTIONS.includes(o.id) || o.speed || o.model || o.under_sampling).map(o => o.id));
  for (const option of options || []) if (own.has(option.parent)) own.add(option.id);
  return key => [...own].some(id => [`opt_${id}`, `opt_${id}_on`, `opt_${id}_strength`].includes(key));
}
const familyDefault = (side, family) => family && (presets[side] || []).find(p => p.family_default === family);
// The preset a workflow starts from: the one saved as its default, else ComfyUI's settings with its family's default
// on top. null for one that isn't listed (the built-in).
function workflowDefault(side, workflow) {
  const saved = (presets[side] || []).find(p => p.workflow_default === workflow);
  if (saved) return saved;
  const w = sideWorkflows(side).find(w => w.name === workflow);
  if (!w) return null;
  const options = (w.takes || {}).options || [], family = familyDefault(side, w.family), own = ownedByWorkflow(options);
  const inherited = family ? Object.fromEntries(Object.entries(family.values).filter(([key]) => key !== 'workflow' && !own(key))) : {};
  const taken = (presets[side] || []).some(p => p.name === w.label);
  return { name: taken ? `${w.label} (workflow)` : w.label, auto: true, workflow_default: workflow, family: w.family || '',
           family_label: w.family_label || '', from_family: family ? family.name : '',
           values: { workflow, ...optionDefaultValues(options), ...inherited } };
}
// Every workflow's default, and any saved for a workflow ComfyUI no longer has.
function workflowPresets(side) {
  const listed = sideWorkflows(side).map(w => workflowDefault(side, w.name));
  const names = new Set(listed.map(p => p.workflow_default));
  return [...listed, ...(presets[side] || []).filter(p => p.workflow_default && !names.has(p.workflow_default))];
}
// Every preset a side can apply: those saved, and the workflow defaults made here.
const allPresets = side => [...(presets[side] || []), ...workflowPresets(side).filter(p => p.auto)];
const findPreset = (side, name) => allPresets(side).find(p => p.name === name);
// A workflow's default, then the size pinned for its family and mode, unless the default saved for it sets a size.
function applyWorkflowDefault(side) {
  const preset = workflowDefault(side, currentWorkflow(side));
  if (preset) applyPresetValues(side, preset);
  if (!preset || preset.auto || !(SIZE_FIELDS[side] || []).some(field => field in preset.values)) applySizeDefault(side);
}
// The workflow, and the family and mode, each side showed when its presets were last synced: what a tap on the form
// changed them from.
const presetWorkflowShown = {}, presetSizeShown = {};
// Another workflow chosen by hand (a real tap, so never a run being reopened or a preset applied): its default, once
// every handler has followed the change. The same workflow in another mode: the size pinned for that mode.
document.addEventListener('change', e => {
  if (!e.isTrusted || SETTINGS.workflow_switch === 'last' || !e.target || e.target.tagName !== 'SELECT' || String(e.target.name).startsWith('opt_')) return;
  const side = Object.keys(SIDE_FORMS).find(side => $(SIDE_FORMS[side]).contains(e.target));
  if (!side || e.target === $(`${side}Preset`) || !(side in presetWorkflowShown)) return;
  const before = presetWorkflowShown[side], sizeBefore = presetSizeShown[side];
  queueMicrotask(() => {
    if (currentWorkflow(side) !== before) applyWorkflowDefault(side);
    else if (sizeKey(side) !== sizeBefore) applySizeDefault(side);
  });
}, true);

// --- A default size for each model family and mode, pinned beside Resolution ---
// Krea-2's T2I at 2 MP 3:2, its Edit at the image's own size: the pin saves the size shown as the one its family and
// mode start at, for every workflow of them, a new one included. Kept by the server (Settings' default_sizes).
const SIZE_FIELDS = { image: ['aspect', 'megapixels', 'size'], video: ['size'] };
// "krea2|text" on the image side; the video side has one mode, the family's.
function sizeKey(side) {
  if (side === 'image') {
    const takes = imageWorkflows[$('imageWorkflow').value];
    return takes ? `${familyOf(takes)}|${currentImageMode(takes)}` : '';
  }
  const workflow = side === 'video' && sideWorkflows(side).find(w => w.name === currentWorkflow(side));
  return workflow && workflow.family ? `${workflow.family}|any` : '';
}
function sizeLabel(side) {
  const [family, mode] = sizeKey(side).split('|');
  if (side === 'image') return `${familyLabel(family)} ${MODE_LABELS[mode] || mode}`;
  const workflow = sideWorkflows(side).find(w => w.family === family);
  return (workflow && workflow.family_label) || family;
}
const savedSizes = side => ((SETTINGS.default_sizes || {})[side]) || {};
function sizeNow(side) {
  return side === 'image' ? { aspect: $('imageAspect').value, megapixels: $('imageMegapixels').value, size: $('imageSize').value }
    : { preset: $('sizePreset').value, size: $('size').value };
}
function applySizeDefault(side) {
  const saved = SIZE_FIELDS[side] && savedSizes(side)[sizeKey(side)];
  if (!saved) return;
  const set = (id, value) => {
    const el = $(id);
    if (typeof value === 'string' && (!el.options || [...el.options].some(o => o.value === value))) el.value = value;
  };
  if (side === 'image') { set('imageAspect', saved.aspect); set('imageMegapixels', saved.megapixels); set('imageSize', saved.size); }
  else { set('sizePreset', saved.preset); set('size', saved.size); }
  SIDE_SYNC[side]();
  SIDE_SAVE[side]();
  syncPresets(side);
}
// Resolution's heading: a small pin after it while the size shown is the one pinned for this model and mode.
const pinnable = side => { const key = SIZE_FIELDS[side] ? sizeKey(side) : ''; return key && !key.startsWith('workflow:') ? key : ''; };
const isPinned = side => { const saved = savedSizes(side)[pinnable(side)]; return !!saved && JSON.stringify(saved) === JSON.stringify(sizeNow(side)); };
function syncSizePin(side) {
  const heading = document.querySelector(`[data-size-menu="${side}"]`);
  if (heading) heading.dataset.pinned = String(!!pinnable(side) && isPinned(side));
}
// A size in words, as its pickers show it: "3:2 · 2 MP", "1920x1080", "Same as the image".
function sizeWords(side, size) {
  const shown = (id, value) => { const option = [...$(id).options].find(o => o.value === value); return option ? option.textContent.trim() : value; };
  if (side === 'image') {
    if (size.aspect === 'custom') return size.size || 'Exact size';
    const mp = Number(size.megapixels);
    return shown('imageAspect', size.aspect) + (Number.isFinite(mp) && size.megapixels !== '' ? ` · ${+mp.toFixed(2)} MP` : '');
  }
  return size.preset === 'custom' ? size.size || 'Custom size' : shown('sizePreset', size.preset);
}
// Grown up out of the heading: as wide as Resolution's box, its bottom on the heading's; never off the top.
function placeOverHeading(box, heading) {
  const block = (heading.closest('.res-block, #videoSizeBox, .field') || heading.parentNode).getBoundingClientRect(), at = heading.getBoundingClientRect();
  Object.assign(box.style, { margin: '0', inset: 'auto', height: 'auto', minHeight: '0', left: `${block.left}px`, width: `${block.width}px` });
  box.style.top = `${Math.max(8, at.bottom + 4 - box.getBoundingClientRect().height)}px`;
}
let sizeMenuSide = null;
function openSizeMenu(side, heading) {
  sizeMenuSide = side;
  const key = pinnable(side), saved = savedSizes(side)[key], pinned = isPinned(side);
  $('sizeMenuTitle').textContent = key ? `Resolution for ${sizeLabel(side)}` : 'Resolution';
  $('sizeMenuNow').textContent = sizeWords(side, sizeNow(side));
  $('sizeMenuPinned').hidden = !saved || pinned;
  $('sizeMenuPinned').textContent = saved ? `Pinned: ${sizeWords(side, saved)}` : '';
  $('sizeMenuUse').hidden = !saved || pinned;
  $('sizeMenuPin').disabled = !key;
  $('sizeMenuPin').textContent = !key ? "This workflow's model isn't known: nothing to pin it for" : pinned ? 'Forget the pinned resolution' : 'Pin this resolution';
  const box = $('sizeMenu');
  box.classList.remove('closing');
  if (!box.open) box.showModal();
  placeOverHeading(box, heading);
}
function closeSizeMenu() {
  const box = $('sizeMenu');
  if (!box.open || box.classList.contains('closing')) return;
  box.classList.add('closing');
  setTimeout(() => { box.close(); box.classList.remove('closing'); }, 150);
}
document.addEventListener('click', e => {
  const heading = e.target.closest && e.target.closest('[data-size-menu]');
  if (heading) openSizeMenu(heading.dataset.sizeMenu, heading);
});
// Around the menu (its backdrop) or Esc: closed.
$('sizeMenu').addEventListener('click', e => { if (e.target === $('sizeMenu')) closeSizeMenu(); });
$('sizeMenu').addEventListener('cancel', e => { e.preventDefault(); closeSizeMenu(); });
$('sizeMenuUse').addEventListener('click', () => { const side = sizeMenuSide; closeSizeMenu(); applySizeDefault(side); });
$('sizeMenuPin').addEventListener('click', async () => {
  const side = sizeMenuSide, key = pinnable(side);
  if (!key) return;
  const mine = { ...savedSizes(side) };
  if (isPinned(side)) delete mine[key]; else mine[key] = sizeNow(side);
  closeSizeMenu();
  await saveSettings({ default_sizes: { ...(SETTINGS.default_sizes || {}), [side]: mine } }, message => message && showFormError(message));
  syncSizePin(side);
});
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
    const target = e.target.closest && e.target.closest('[data-preset-open], [data-preset-close], [data-preset-save], [data-preset-delete], [data-preset-default], [data-preset-confirm], [data-preset-cancel], [data-preset-workflow]');
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
    if (target.dataset.presetWorkflow) {
      // The form as it is, as the chosen workflow's own default, under the name its default already has.
      const side = target.dataset.presetWorkflow, workflow = currentWorkflow(side), now = workflowDefault(side, workflow);
      if (!now) return;
      const values = presetValues(side);
      if (await presetRequest({ side, name: now.name, values, workflow_default: workflow })) presetPicked[side] = { name: now.name, values };
      syncPresets(side);
      return;
    }
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
  const select = $(`${side}Preset`), list = allPresets(side), now = presetValues(side);
  presetWorkflowShown[side] = currentWorkflow(side);
  presetSizeShown[side] = SIZE_FIELDS[side] ? sizeKey(side) : '';
  syncSizePin(side);
  const key = JSON.stringify(list.map(p => p.name));
  if (select.dataset.key !== key) {
    select.dataset.key = key;
    select.innerHTML = '<option value="">None</option>' + list.map(p => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
  }
  const picked = presetPicked[side] && list.find(p => p.name === presetPicked[side].name);
  const match = picked && (samePreset(picked.values, now) || sameForm(presetPicked[side].values, now))
    ? picked : list.find(p => (p.auto ? sameShown : samePreset)(p.values, now));
  select.value = match ? match.name : '';
  $(`${side}PresetOpen`).textContent = match ? match.name : 'Preset';
  document.querySelector(`[data-preset-save="${side}"]`).hidden = false;
  // One made here from ComfyUI's settings isn't saved, so has nothing to delete or flag until it's saved over.
  const saved = match && !match.auto;
  const remove = document.querySelector(`[data-preset-delete="${side}"]`);
  remove.hidden = !saved;
  remove.title = saved && match.workflow_default ? "Back to the workflow's settings as saved in ComfyUI" : 'Delete this preset';
  remove.setAttribute('aria-label', remove.title);
  const star = document.querySelector(`[data-preset-default="${side}"]`), isDefault = !!(saved && match.default);
  star.hidden = !saved;
  star.setAttribute('aria-pressed', String(isDefault));
  star.title = isDefault ? 'Favourite preset: used when this side opens. Tap to remove favourite.' : 'Favourite this preset: use it when this side opens';
  star.setAttribute('aria-label', star.title);
  const workflow = sideWorkflows(side).find(w => w.name === currentWorkflow(side));
  const own = document.querySelector(`[data-preset-workflow="${side}"]`);
  own.hidden = !workflow;
  own.title = workflow ? `Save these settings as ${workflow.label}'s default: used when it's chosen` : '';
  own.setAttribute('aria-label', own.title);
  drawPresetList(side, (presets[side] || []).filter(p => !p.workflow_default), match);
  drawWorkflowPresets(side, workflowPresets(side), match);
}
const presetRow = (p, match, note = '') => `<button type="button" class="preset-row" role="option" aria-selected="${!!(match && match.name === p.name)}" data-preset-pick="${esc(p.name)}">`
  + `<span class="preset-row-name">${esc(p.name)}</span>${note ? `<span class="preset-row-note">${esc(note)}</span>` : ''}`
  + (p.family_default ? `<span class="preset-row-family" title="Default for its model family's workflows">${esc(familyName(p.family_default))}</span>` : '')
  + `${p.default ? '<span class="preset-row-star" title="Favourite: used when this side opens">★</span>' : ''}</button>`;
function familyName(family) {
  const found = Object.values(workflowLists).flatMap(list => (list && list.workflows) || []).find(w => w.family === family);
  return (found && found.family_label) || family;
}
// The presets as lines in the box, as Finished lists what's done: the one the form matches outlined, the favourite
// starred. A tap picks it in the (hidden) select, which applies it as picking it there always has.
function drawPresetList(side, list, match) {
  const box = $(`${side}PresetList`);
  if (!box) return;
  const key = JSON.stringify([list.map(p => [p.name, !!p.default, p.family_default || '']), match ? match.name : '']);
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  box.innerHTML = list.map(p => presetRow(p, match)).join('');
}
// Under them, folded: each workflow's default, by model family, and where each came from.
function drawWorkflowPresets(side, list, match) {
  const box = $(`${side}PresetWorkflowList`);
  if (!box) return;
  $(`${side}PresetWorkflows`).hidden = !list.length;
  $(`${side}PresetWorkflowCount`).textContent = list.length ? `(${list.length})` : '';
  const mine = (presets[side] || []).filter(p => !p.workflow_default);
  const key = JSON.stringify([list.map(p => [p.name, p.auto, p.from_family, p.family]), mine.map(p => [p.name, p.family_default || '']), match ? match.name : '']);
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  const listed = new Set(sideWorkflows(side).map(w => w.name)), groups = new Map();
  for (const p of list) {
    const workflow = sideWorkflows(side).find(w => w.name === p.workflow_default);
    const family = (workflow && workflow.family) || p.family || '';
    const group = groups.get(family) || { label: (workflow && workflow.family_label) || p.family_label || 'Family unknown', items: [] };
    groups.set(family, { ...group, items: [...group.items, p] });
  }
  const note = p => !listed.has(p.workflow_default) ? 'Workflow gone from ComfyUI' : !p.auto ? 'Saved by you'
    : p.from_family ? `ComfyUI's, with ${p.from_family}` : 'As saved in ComfyUI';
  // Its family's default: any preset of yours, applied to each of its workflows that has no default of its own.
  const picker = family => {
    const chosen = familyDefault(side, family);
    return `<select class="preset-family-default" data-family-default="${esc(family)}" data-side="${side}" aria-label="Default preset for the family">`
      + `<option value="">No family default</option>${mine.map(p => `<option value="${esc(p.name)}"${chosen && chosen.name === p.name ? ' selected' : ''}>Family default: ${esc(p.name)}</option>`).join('')}</select>`;
  };
  box.innerHTML = [...groups].map(([family, group]) => `<div class="preset-family" role="presentation"><span>${esc(group.label)}</span>${family && mine.length ? picker(family) : ''}</div>`
    + group.items.map(p => presetRow(p, match, note(p))).join('')).join('');
}
document.addEventListener('change', async e => {
  const picker = e.target.closest && e.target.closest('[data-family-default]');
  if (!picker) return;
  const side = picker.dataset.side, family = picker.dataset.familyDefault, held = familyDefault(side, family);
  if (picker.value) await presetRequest({ side, name: picker.value, family_default: family });
  else if (held) await presetRequest({ side, name: held.name, family_default: '' });
});
document.addEventListener('click', e => {
  const row = e.target.closest && e.target.closest('[data-preset-pick]');
  if (!row) return;
  const side = row.closest('.preset-dialog').id.replace('PresetDialog', ''), select = $(`${side}Preset`);
  select.value = row.dataset.presetPick;
  select.dispatchEvent(new Event('change', { bubbles: true }));
});
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
  const preset = findPreset(side, name);
  if (preset) applyPresetValues(side, preset, atStart);
}
function applyPresetValues(side, preset, atStart = false) {
  const name = preset.name, form = $(SIDE_FORMS[side]), values = preset.values;
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
