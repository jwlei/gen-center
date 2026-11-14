// --- Seeds: empty is random, the shuffle button picks one to keep, ✕ goes back to random ---
const SHUFFLE_ICON = '<svg class="icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/></svg>';
const MOST_SEED = 4294967295;
function randomSeed() {
  try { return crypto.getRandomValues(new Uint32Array(1))[0]; } catch (e) { return Math.floor(Math.random() * MOST_SEED); }
}
function setSeed(input, value) {
  input.value = value;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}
// The shuffle button picks a seed to keep; ✕ goes back to a random one each time.
document.querySelectorAll('[data-seed-pick]').forEach(button => { button.innerHTML = SHUFFLE_ICON; });
document.addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('[data-seed-pick], [data-seed-clear]');
  if (!button) return;
  if (button.dataset.seedPick) setSeed($(button.dataset.seedPick), randomSeed());
  else setSeed($(button.dataset.seedClear), '');
});
// Same seed: the seed of what Generate was opened from (the sliders on a picture or film), lit while the seed box holds
// it. Always there; greyed out with nothing to use again.
const SAME_SEED_ICON = '<svg class="icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22c4-3 7-6.5 7-11a7 7 0 0 0-14 0c0 4.5 3 8 7 11z"/><path d="M9 11h6M9 14h6"/></svg>';
const sameSeeds = {};
function offerSameSeed(field, seed) {
  sameSeeds[field] = seed == null || seed === '' ? null : String(seed);
  showSameSeed(field);
}
function showSameSeed(field) {
  const button = $(`${field}Same`), seed = sameSeeds[field] ?? null;
  if (!button) return;
  button.disabled = seed == null;
  button.title = seed == null ? 'Use the same seed again: open Generate from a picture or film with its sliders' : `Use the same seed again (${seed})`;
  button.setAttribute('aria-label', button.title);
  button.setAttribute('aria-pressed', String(seed != null && $(field).value === seed));
}
for (const button of document.querySelectorAll('[data-seed-same]')) {
  const field = button.dataset.seedSame;
  button.innerHTML = SAME_SEED_ICON;
  button.addEventListener('click', () => {
    const seed = sameSeeds[field];
    if (seed != null) setSeed($(field), $(field).value === seed ? '' : seed);
  });
  $(field).addEventListener('input', () => showSameSeed(field));
  $(field).addEventListener('change', () => showSameSeed(field));
  showSameSeed(field);
}
// Each upscale's header: a tap drops its hint down for the upscale chosen, the next tap folds it away.
const RES_HINTS = { videoLatentInfo: 'videoLatentHint', imageUpscaleInfo: 'imageUpscaleHint' }, resOpen = {};
document.addEventListener('click', e => {
  const info = e.target.closest && e.target.closest('.res-info');
  if (!info || !RES_HINTS[info.id]) return;
  resOpen[info.id] = !resOpen[info.id];
  info.setAttribute('aria-expanded', String(resOpen[info.id]));
  $(RES_HINTS[info.id]).hidden = !resOpen[info.id] || !$(RES_HINTS[info.id]).textContent;
});
function showResHint(info, text) {
  const hint = $(RES_HINTS[info]);
  hint.textContent = text;
  hint.hidden = !text || !resOpen[info];
}
// Digits only: anything else isn't a seed.
document.addEventListener('input', e => {
  if (e.target.name === 'seed' || e.target.dataset.seed !== undefined) {
    const digits = e.target.value.replace(/\D/g, '');
    if (digits !== e.target.value) e.target.value = digits;
  }
});
// In the shots and images editors: the seed it was made with, which the next render keeps unless it's changed.
function shownSeed(shot) { return shot.seed ?? shot.used_seed ?? null; }
// A shot's seed: an icon on the right of its row (lit when a seed is pinned) that opens the seed dialog.
// The value itself waits in a hidden field, which saving and rendering again read as before.
function seedIconTitle(seed) { return seed == null || seed === '' ? 'Seed: random' : `Seed: ${seed}`; }
function shotSeedHtml(run, shot, i, what) {
  const number = i + 1, seed = shownSeed(shot), pinned = seed != null && seed !== '';
  return `<input type="hidden" id="seed_${number}" data-seed value="${seed ?? ''}">`
    + `<button type="button" class="icon-btn seed-icon${pinned ? ' pinned' : ''}" data-seed-open="${number}" data-what="${what}"${run.busy ? ' data-locked="1"' : ''}`
    + ` aria-haspopup="dialog" title="${seedIconTitle(seed)}" aria-label="${seedIconTitle(seed)}, for ${what} ${number}">${ICONS.seed}</button>`;
}
function editedSeeds() { return [...$('shotsBody').querySelectorAll('[data-seed]')].map(input => input.value.trim() || null); }

// --- A film's shots ---
let shotsRun = null, shotsDirty = false;
function runUrl(id) { return `${id.startsWith('image_') ? '/image-runs' : '/runs'}/${id}`; }
// One item of a film or a set: its clip or picture, its prompt, and icons under them. On the left, what to do with
// it: more like this in Generate (its prompt as it stands, on new seeds), and what an enhancer wrote, if one did.
// Its prompt is the box, a tap away. On the right, keeping it: its seed, save, delete.
function shotItemHtml(run, shot, i) {
  const number = i + 1, film = !run.is_image, take = film && run.start === 'multishot';
  const icon = (data, label, svg, extra = '') => `<button type="button" class="icon-btn${extra}" ${data} title="${label}" aria-label="${label}">${svg}</button>`;
  const url = film ? '' : `/image-runs/${encodeURIComponent(run.id)}`;
  const media = !shot.rendered ? ''
    : film ? `<video controls preload="none" playsinline src="/runs/${esc(run.id)}/clips/${number}"></video>`
    : `<a href="${url}/files/${number}?v=${shot.version}" target="_blank" rel="noopener"><img class="shot-image" loading="lazy" alt="Image ${number}" src="${url}/thumbnails/${number}?v=${shot.version}"></a>`;
  const status = film ? `<span>${shot.seconds}s</span>` : '';
  const like = icon(`data-create="${number}"`, 'More like this: its prompt and settings in Generate, on new seeds', ICONS.config);
  // The prompt is the box itself: a tap opens it. Only what an enhancer wrote from it needs a button of its own.
  const enhanced = film ? icon(`data-history="${number}" aria-haspopup="dialog"`, 'Prompt history: original, planner, enhancer and final ComfyUI text', ICONS.enhanced)
    : shot.enhanced_prompt ? icon(`data-enhanced="${number}" aria-haspopup="dialog"`, 'Detailed prompt: what the prompt enhancer wrote', ICONS.enhanced) : '';
  // An image an upscale waits on stays; the rest of the set can go while upscales wait.
  const remove = !film && !run.busy && !run.pending && !shot.locked ? icon(`data-delete-image="${number}"`, 'Delete', ICONS.trash, ' del') : '';
  const save = run.busy ? '' : icon('data-save="1"', 'Save the prompts', ICONS.save);
  const seed = take && i ? `<input type="hidden" data-seed value="${shot.seed ?? ''}">` : shotSeedHtml(run, shot, i, film ? (take ? 'take' : 'shot') : 'image');
  return `
  <div class="shot">
    <div class="shot-title"><b>${number}. ${esc(shot.title)}</b>${status}</div>
    ${media}
    <textarea aria-label="Prompt for ${film ? 'shot' : 'image'} ${number}" data-prompt inputmode="none" ${run.busy ? 'readonly' : ''}>${esc(shot.prompt)}</textarea>
    <div class="shot-actions">
      <div class="shot-actions-left">${like}${enhanced}</div>
      <div class="shot-actions-right">${seed}${save}${remove}</div>
    </div>
  </div>`;
}
// A film or a set: one item at a time, swiped left and right, its count by the title, its brief a tap away.
function shotsHtml(run) {
  const film = !run.is_image, left = run.shots.filter(shot => !shot.rendered).length;
  const note = run.busy ? 'This run is going or queued, so its prompts can\'t change right now.'
    : run.pending ? 'Save changes here, then start this run from Pending.'
    : !film ? ''
    : run.start === 'multishot' ? 'H3 Multishot renders the whole take at once. Saving edits does not change a rendered take: render the whole take again to apply them. Only the first seed controls the take.'
    : ['chain', 'infinite'].includes(run.start) ? 'A continuous take: rendering a shot again also renders every shot after it, because they start from it.' : '';
  const action = !film ? (left === run.shots.length ? 'Make the images' : `Make the ${left} left`)
    : run.start === 'multishot' && run.take_rendered ? 'Finish the film' : left === run.shots.length ? 'Render the film' : left ? `Render the ${left} left` : 'Stitch the film';
  const done = film ? run.finished : !left;
  const go = done || run.busy || run.pending ? '' : `<button type="button" data-render="1">${action}</button>`;
  return `
  <div class="shots-head">
    <div class="shots-head-line">
      <h2 class="shots-title">${esc(run.title)}</h2>
      ${run.shots.length > 1 ? `<span class="shots-count" id="shotsCount">1 of ${run.shots.length}</span>` : ''}
    </div>
    ${note ? `<div class="hint">${note}</div>` : ''}
  </div>
  <div class="shots-list carousel" id="shotsCarousel">${run.shots.map((shot, i) => shotItemHtml(run, shot, i)).join('')}</div>
  <div class="shots-foot centred small">${go}<button type="button" class="plain" data-close="1">Close</button></div>`;
}
// page: the image to open on, from 1; the first otherwise.
async function openShots(id, page) {
  const epoch = workspaceEpoch;
  let data;
  try {
    data = await (await fetch(runUrl(id))).json();
  } catch (e) {
    data = { error: 'Could not reach the panel. Try again.' };
  }
  if (epoch !== workspaceEpoch) return;
  if (!data.ok) { alert(data.error || 'Could not open that run.'); return; }
  shotsRun = data;
  shotsDirty = false;
  $('shotsBody').innerHTML = shotsHtml(data);
  if (!$('shotsDialog').open) $('shotsDialog').showModal();
  const carousel = $('shotsBody').querySelector('#shotsCarousel');
  if (carousel && $('shotsBody').querySelector('#shotsCount')) {
    carousel.addEventListener('scroll', () => {
      const at = Math.round(carousel.scrollLeft / Math.max(carousel.clientWidth, 1)) + 1;
      $('shotsCount').textContent = `${at} of ${data.shots.length}`;
      if (carousel.dataset.at !== String(at)) $('shotsBody').querySelectorAll('video').forEach(video => video.pause());
      carousel.dataset.at = String(at);
      closeSeedFolds();
    }, { passive: true });
  }
  if (carousel && page > 1) carousel.scrollLeft = (Math.min(page, data.shots.length) - 1) * carousel.clientWidth;
}
// The arrow keys turn a set's pages, unless you're typing in a prompt or seed.
$('shotsDialog').addEventListener('keydown', e => {
  const carousel = $('shotsBody').querySelector('#shotsCarousel');
  if (!carousel || /^(TEXTAREA|INPUT)$/.test(e.target.tagName) || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
  e.preventDefault();
  carousel.scrollBy({ left: (e.key === 'ArrowRight' ? 1 : -1) * carousel.clientWidth, behavior: 'smooth' });
});
async function saveShots() {
  const epoch = workspaceEpoch;
  const seeds = editedSeeds();
  // The seed a shot was made with is shown, and kept, without being saved as its own yet.
  const keptSeeds = seeds.some((seed, i) => seed !== (shotsRun.shots[i].seed == null ? null : String(shotsRun.shots[i].seed)));
  if (!shotsDirty && !keptSeeds) return true;
  const prompts = [...$('shotsBody').querySelectorAll('textarea')].map(t => t.value);
  const data = await (await fetch(`${runUrl(shotsRun.id)}/shots`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompts, seeds }),
  })).json();
  if (epoch !== workspaceEpoch) return false;
  if (!data.ok) { alert(data.error || 'Could not save the prompts.'); return false; }
  shotsDirty = false;
  return true;
}
function closeShots() {
  if (shotsDirty && !confirm('Close without saving your changes to the prompts?')) return;
  shotsDirty = false;
  $('shotsBody').querySelectorAll('video').forEach(v => v.pause());
  $('shotsDialog').close();
}
async function runSaved(url, button) {
  const data = await queueRequest(button, async () => (await fetch(url, { method: 'POST' })).json());
  if (!data) return;
  closeShots();
  autoScroll = true;
  poll();
}
$('shotsBody').addEventListener('input', () => { shotsDirty = true; });
$('shotsBody').addEventListener('click', async e => {
  const button = (e.target.closest && e.target.closest('button')) || e.target, d = button.dataset || {};
  if (d.enhanced) {
    const number = Number(d.enhanced), shot = shotsRun.shots[number - 1];
    if (!shot) { alert('Could not open the detailed prompt.'); return; }
    closeSeedFolds();
    const box = $('shotsBody').querySelectorAll('textarea[data-prompt]')[number - 1];
    openPromptDetail(shot.enhanced_prompt || (box ? box.value : shot.prompt), shotsRun.brief);
    return;
  }
  if (d.history) {
    const shot = shotsRun.shots[Number(d.history) - 1];
    if (!shot) { alert('Could not open the prompt history.'); return; }
    openClipPromptHistory(shotsRun, shot);
    return;
  }
  const toggle = e.target.closest && e.target.closest('[data-fold]');
  if (toggle) {
    const fold = $(toggle.dataset.fold), open = fold.hidden;
    closeSeedFolds();
    fold.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    return;
  }
  const seedOpen = e.target.closest && e.target.closest('[data-seed-open]');
  if (seedOpen) { openSeedDialog(seedOpen); return; }
  const prompts = [...$('shotsBody').querySelectorAll('textarea[data-prompt]')];
  if (d.create) {
    // More like this one, from Generate: its prompt as it stands here, word for word, on new seeds.
    const number = Number(d.create), run = shotsRun, shot = run.shots[number - 1];
    const exact = { prompt: (prompts[number - 1] || {}).value ?? shot.prompt, seed: '', seconds: shot.seconds, count: VARIATIONS };
    closeShots();
    if ($('shotsDialog').open) return;  // Kept open to save changes first
    if (run.is_image) sameAgain(run.id, number, exact); else sameAgainFilm(run.id, exact);
    return;
  }
  if (d.close) closeShots();
  else if (d.save) {
    // Saved: a tick for a moment where the button was.
    if (await saveShots()) {
      button.innerHTML = ICONS.check;
      setTimeout(() => { button.innerHTML = ICONS.save; }, 1200);
    }
  }
  else if (d.render) {
    if (await saveShots()) runSaved(`/runs/${shotsRun.id}/continue`, button);
  } else if (d.deleteImage) {
    if (!secondTap(button)) return;
    if (!await saveShots()) return;
    const last = shotsRun.shots.length === 1, id = shotsRun.id;
    const data = await (await fetch(`${runUrl(id)}/delete/${d.deleteImage}`, { method: 'POST' })).json();
    if (!data.ok) { alert(data.error || 'Could not delete it.'); return; }
    if (last) closeShots(); else openShots(id);
    poll();
  } else if (d.redo && shotsRun.is_image) {
    const seed = $(`seed_${d.redo}`).value.trim();
    if (!confirm(`Generate image ${d.redo} again on ${seed ? `seed ${seed}` : 'a new seed'}? The new one replaces it.`)) return;
    if (await saveShots()) runSaved(`${runUrl(shotsRun.id)}/redo/${d.redo}`, button);
  } else if (d.redo) {
    const after = ['chain', 'infinite'].includes(shotsRun.start) ? shotsRun.shots.length - d.redo : 0;
    const also = after ? ` and the ${after} after it` : '';
    const seed = $(`seed_${d.redo}`).value.trim();
    const what = shotsRun.start === 'multishot' ? 'the whole take' : `shot ${d.redo}${also}`;
    if (!confirm(`Generate ${what} again on ${seed ? `seed ${seed}` : 'a new seed'}? The film replaces the one already finished.`)) return;
    if (await saveShots()) runSaved(`/runs/${shotsRun.id}/redo/${d.redo}`, button);
  }
});
// --- The seed dialog: one shot's seed, to type, roll or set back to random, then Save or Cancel ---
let seedButton = null;
function seedField(button) { return button.dataset.seedTarget ? $(button.dataset.seedTarget) : $(`seed_${button.dataset.seedOpen}`); }
function openSeedDialog(button) {
  seedButton = button;
  const number = button.dataset.seedOpen, locked = !!button.dataset.locked, value = seedField(button).value;
  $('seedDialogTitle').textContent = button.dataset.seedTarget ? `Seed for ${button.dataset.what}` : `Seed for ${button.dataset.what || 'shot'} ${number}`;
  $('seedDialogValue').value = value;
  $('seedDialogValue').readOnly = locked;
  $('seedDialogError').hidden = true;
  for (const id of ['seedDialogRoll', 'seedDialogClear', 'seedDialogSave']) $(id).hidden = locked;
  $('seedDialogCancel').textContent = locked ? 'Close' : 'Cancel';
  $('seedDialog').showModal();
}
function saveSeedDialog() {
  const value = $('seedDialogValue').value.trim();
  if (value && !/^\d+$/.test(value)) {
    $('seedDialogError').textContent = 'A seed is a whole number, or empty for a random one.';
    $('seedDialogError').hidden = false;
    return;
  }
  const number = seedButton.dataset.seedOpen, field = seedField(seedButton);
  if (field.value !== value) {
    field.value = value;
    shotsDirty = true;
  }
  seedButton.classList.toggle('pinned', !!value);
  seedButton.title = seedIconTitle(value);
  seedButton.setAttribute('aria-label', `${seedIconTitle(value)}, for ${seedButton.dataset.what || 'shot'} ${number}`);
  $('seedDialog').close();
}
$('seedDialogRoll').addEventListener('click', () => { $('seedDialogValue').value = randomSeed(); $('seedDialogError').hidden = true; });
$('seedDialogClear').addEventListener('click', () => { $('seedDialogValue').value = ''; $('seedDialogError').hidden = true; });
$('seedDialogSave').addEventListener('click', saveSeedDialog);
$('seedDialogCancel').addEventListener('click', () => $('seedDialog').close());
$('seedDialogValue').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); saveSeedDialog(); } });
$('seedDialogRoll').innerHTML = SHUFFLE_ICON;
function closeSeedFolds() {
  $('shotsBody').querySelectorAll('.seed-fold').forEach(fold => { fold.hidden = true; });
  $('shotsBody').querySelectorAll('[data-fold]').forEach(toggle => toggle.setAttribute('aria-expanded', 'false'));
}
// A tap anywhere else, even outside the dialog, puts an open fold away.
$('shotsDialog').addEventListener('click', e => {
  if (e.target.closest && (e.target.closest('.seed-fold') || e.target.closest('[data-fold]'))) return;
  closeSeedFolds();
});
// The original prompt, copied as it was written. The clipboard API needs https or this PC; a phone on the
// home network has neither, so the old way stands in.
async function copyText(text, parent) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) {}
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  parent.appendChild(area);
  area.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) {}
  area.remove();
  return ok;
}
let promptCopyTimer, promptDetailTexts = { detailed: '', yours: '' };
// The prompt as it went to the model (the enhancer's, else the one written for it), with your own prompt a tap away.
function openPromptDetail(detailed, yours, first = 'detailed') {
  promptDetailTexts = { detailed: detailed || '', yours: yours || '' };
  $('promptDetailStages').hidden = true;
  $('promptDetailYours').hidden = !yours;
  showPromptDetail(first === 'yours' && yours ? 'yours' : 'detailed');
  clearTimeout(promptCopyTimer);
  $('promptDetailCopy').classList.remove('done');
  $('promptDetailCopy').innerHTML = ICONS.copy;
  $('promptDetail').showModal();
}
function openClipPromptHistory(run, shot) {
  const stages = [
    ['yours', 'Original brief', run.brief],
    ['planner', 'Planner output', shot.planner_prompt || (run.direct ? 'Not used: Exact mode repeats your brief.' : 'Not recorded for this older run.')],
    ['enhancer', 'Enhancer output', shot.enhancer_prompt || shot.enhanced_prompt || (run.h3_mode && run.h3_mode !== 'off' ? 'Not generated yet, or not recorded for this older run.' : 'Not used.')],
    ['detailed', 'Final ComfyUI text', shot.comfy_prompt || (shot.rendered ? 'Not recorded for this older render.' : 'Not submitted to ComfyUI yet.')],
  ];
  if (shot.workflow_enhanced_prompt) stages.push(['workflow', 'Workflow enhancer', shot.workflow_enhanced_prompt]);
  openPromptDetail(stages[3][2], run.brief);
  promptDetailTexts = Object.fromEntries(stages.map(([key, , text]) => [key, text || 'No text recorded.']));
  const bar = $('promptDetailStages');
  bar.innerHTML = stages.map(([key, label]) => `<button type="button" data-stage="${key}" aria-pressed="${key === 'detailed'}">${label}</button>`).join('');
  bar.hidden = false;
  $('promptDetailTitle').textContent = 'Final ComfyUI text';
}
$('promptDetailStages').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('button[data-stage]');
  if (!button) return;
  showPromptDetail(button.dataset.stage);
  $('promptDetailTitle').textContent = button.textContent;
});
function showPromptDetail(which) {
  $('promptDetailTitle').textContent = which === 'yours' ? 'Your prompt' : 'Detailed prompt';
  $('promptDetailText').textContent = promptDetailTexts[which];
  $('promptDetailText').scrollTop = 0;
  $('promptDetailYours').setAttribute('aria-pressed', String(which === 'yours'));
  for (const button of $('promptDetailStages').querySelectorAll('button[data-stage]')) {
    button.setAttribute('aria-pressed', String(button.dataset.stage === which));
  }
  // The button below says where it goes: to the detailed prompt from yours, to yours from the detailed one.
  $('promptDetailYours').setAttribute('aria-label', which === 'yours' ? 'Show the detailed prompt' : 'Show your prompt');
  $('promptDetailYours').title = which === 'yours' ? 'Detailed prompt' : 'Your prompt';
  $('promptDetailYours').innerHTML = which === 'yours' ? ICONS.enhanced : ICONS.brief;
  $('promptDetailCopy').title = which === 'yours' ? 'Copy your prompt' : 'Copy detailed prompt';
  $('promptDetailCopy').setAttribute('aria-label', $('promptDetailCopy').title);
}
$('promptDetailYours').addEventListener('click', () =>
  showPromptDetail($('promptDetailYours').getAttribute('aria-pressed') === 'true' ? 'detailed' : 'yours'));
$('promptDetailCopy').addEventListener('click', async () => {
  const button = $('promptDetailCopy');
  if (!await copyText($('promptDetailText').textContent, $('promptDetail'))) { alert('Could not copy it.'); return; }
  button.classList.add('done');
  button.innerHTML = ICONS.check;
  clearTimeout(promptCopyTimer);
  promptCopyTimer = setTimeout(() => { button.classList.remove('done'); button.innerHTML = ICONS.copy; }, 1500);
});
$('promptDetailClose').addEventListener('click', () => $('promptDetail').close());
// A tap outside it closes it, as the other boxes over the page do; a tap on its own padding does not.
$('promptDetail').addEventListener('click', e => {
  if (e.target !== $('promptDetail')) return;
  const box = $('promptDetail').getBoundingClientRect();
  if (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom) $('promptDetail').close();
});
// Esc would otherwise close it without asking about unsaved changes.
$('shotsDialog').addEventListener('cancel', e => { e.preventDefault(); closeShots(); });
