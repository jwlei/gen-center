// --- The same again: a set's settings back in Generate, its images too, to change before pressing it ---
// Alone (a set's sliders): the settings the set was made with, its seed fixed only if it was.
// With position: more like that one image: its own prompt, word for word, four times on new seeds.
// With from: exactly what made that one image (the sliders in the viewer), to make it again: its own settings, its
// prompt word for word as the model got it, one image, and its seed only if that was fixed (a random one stays a tap
// away, under Same seed).
async function sameAgain(id, position = null, exact = null, from = null) {
  const epoch = workspaceEpoch;
  let data;
  try { data = await (await fetch(`/image-runs/${encodeURIComponent(id)}`)).json(); } catch (e) { data = { error: 'Could not reach the panel. Try again.' }; }
  if (epoch !== workspaceEpoch) return false;
  if (!data.ok) { alert(data.error || 'Could not open that set.'); return false; }
  const shot = position && data.shots[position - 1], picked = shot || (from && data.shots[from - 1]);
  // One image's own setup where it kept one; else the set's.
  const s = { ...((picked && picked.settings) || data.settings) };
  // The set's brief, for Brief beside I2P.
  const brief = s.prompt || '';
  if (shot) Object.assign(s, { prompt: shot.prompt, direct: true, count: VARIATIONS });
  if (!shot && picked && !exact) exact = recreated(picked);
  // Created again from a set's prompts: that one image, its prompt word for word, on its own seed.
  if (exact) Object.assign(s, { prompt: exact.prompt, direct: true, count: exact.count || 1 });
  reopening('image');
  setPromptSources(null);
  if (pipeline !== 'image') setPipeline('image');
  await loadImageWorkflows();
  if (epoch !== workspaceEpoch) return false;
  $('imageWorkflow').value = [...$('imageWorkflow').options].some(o => o.value === s.workflow && !o.disabled) ? s.workflow : '';
  syncImageForm();
  applySavedForm($('formImage'), s.form);
  // One picture from a test (the preview's sliders): what made it alone, its own LoRA strength, file or workflow, so
  // none of the test's ticks, which would run the test again over it. A test batch's own sliders keep them.
  const ticks = from && !shot ? [...$('imageComparisons').querySelectorAll('input[type=checkbox]')] : [];
  // Its seed too, fixed by the test so its images compare, not by you: random again unless the form had one of yours.
  const testSeed = ticks.some(box => box.checked) && !(s.form && s.form.seed);
  for (const box of ticks) box.checked = false;
  syncImageForm();
  $('imagePromptMode').value = s.direct ? 'direct' : 'llm';
  $('imagePrompt').value = s.prompt || '';
  syncPromptWriter('image');
  $('imageCount').value = s.count;
  $('imageAspect').value = 'custom';
  $('imageSize').value = s.size;
  // Its images, as files in the boxes again, so they go up with the rest.
  sourceBoxes().forEach((box, i) => clearSource(box, i === 0));
  clearSource(promptImageBox(), false);
  // Image to prompt's picture was the last, and goes back on its own line.
  const described = s.llm === 'image_to_prompt' ? s.inputs : 0;
  for (let number = 1; number <= s.inputs; number++) {
    try {
      const blob = await (await fetch(`/image-runs/${encodeURIComponent(id)}/inputs/${number}`)).blob();
      if (epoch !== workspaceEpoch) return false;
      syncImageSources();
      const box = number === described ? promptImageBox() : sourceBoxes()[number - 1], files = new DataTransfer();
      if (!box) break;
      files.items.add(new File([blob], `image_${number}.png`, { type: 'image/png' }));
      box.querySelector('input').files = files.files;
      showSource(box, box === sourceBoxes()[0]);
    } catch (e) { if (epoch !== workspaceEpoch) return false; break; }
  }
  syncImageForm();
  // Reopened, a set comes back with every setting it was made with, its prompt model too.
  if ([...$('imageLlm').options].some(o => o.value === s.llm && !o.disabled)) $('imageLlm').value = s.llm;
  if (s.local_model && [...$('imageLocalModel').options].some(o => o.value === s.local_model && !o.disabled)) $('imageLocalModel').value = s.local_model;
  $('imagePromptWriterModel').value = s.local_model || '';
  syncImageForm();
  applyOptions($('imageOptionsBox'), imageTakes().options || [], s.options);
  syncImageForm();
  // A fixed seed comes back fixed; a random one stays random (an empty box). A set from before the form was kept: random.
  $('imageSeed').value = exact ? (testSeed ? '' : exact.seed ?? '') : (s.form && s.form.seed) || '';
  // From one picture: its seed, a tap away, to make it again with other settings.
  offerSameSeed('imageSeed', picked ? picked.used_seed ?? picked.seed : null);
  saveImageForm();
  // From a preview, where the set's brief isn't the picture's own prompt: either a tap away, Detailed first.
  if (from && !shot && exact && brief.trim() && brief.trim() !== (s.prompt || '').trim())
    setPromptSources({ current: 'detailed', brief: { prompt: brief }, detailed: { prompt: s.prompt } });
  reopened('image');
  showFormError(($('imageOptionsBox').unavailable || []).join(' '));
  $('imageGeneration').open = $('imagePromptSection').open = true;
  $('imageOptions').open = !$('imageOptions').hidden;
  if (WIDE.matches) $('optionsCard').scrollIntoView({ behavior: 'smooth' }); else showPage('generate');
  queuePlan();
  return true;
}
// Brief / Detailed, beside I2P when a picture is opened from the preview: the set's brief or the picture's own prompt
// in the box. Only the text: LLM or Exact prompt, Amount and the rest stay as they are. A prompt changed by hand isn't
// lost to a tap without asking.
let promptSources = null;
function setPromptSources(sources) {
  promptSources = sources;
  $('imagePromptSource').hidden = !sources;
  if (sources) paintPromptSource();
}
function paintPromptSource() {
  for (const part of $('imagePromptSource').querySelectorAll('[data-source]')) part.classList.toggle('on', part.dataset.source === promptSources.current);
  $('imagePromptSource').querySelector('.check').setAttribute('aria-label', `Prompt from: ${promptSources.current === 'brief' ? 'the brief' : 'the detailed prompt'}. Tap for the other.`);
}
function usePromptSource(name) {
  if (!promptSources || name === promptSources.current) return;
  const was = promptSources[promptSources.current], to = promptSources[name];
  if ($('imagePrompt').value.trim() !== was.prompt.trim()
      && !confirm(`Replace the prompt you changed with the ${name === 'brief' ? 'brief' : 'detailed prompt'}?`)) return;
  promptSources.current = name;
  $('imagePrompt').value = to.prompt;
  syncPromptWriter('image');
  saveImageForm();
  queuePlan();
  paintPromptSource();
}
$('imagePromptSource').addEventListener('click', () => {
  if (promptSources) usePromptSource(promptSources.current === 'brief' ? 'detailed' : 'brief');
});
// Words like I2P's, so not a <button>: Enter and Space work it as one.
$('imagePromptSource').addEventListener('keydown', e => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  e.preventDefault();
  $('imagePromptSource').click();
});
// One image made again: what the model was given, word for word, as your own prompt. Where the workflow's own prompt
// enhancer or image to prompt wrote it as the image was made, that is what it wrote: run again, they would write
// another (as your own prompt, neither runs). Its seed only if it was fixed: one picked at random is random again.
function recreated(picture) {
  const prompt = picture.enhanced_prompt || picture.prompt;
  return prompt ? { prompt, seed: picture.seed ?? '', count: 1 } : null;
}
// A file a run was given, back as a file for a form's box.
async function runFile(url, name) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load ${name}.`);
  const blob = await response.blob();
  return new File([blob], name, { type: blob.type || 'application/octet-stream' });
}
function putFile(input, file) {
  const files = new DataTransfer();
  files.items.add(file);
  input.files = files.files;
}
// The form a run was queued with, back in its fields. Called first: what the run itself recorded is set after it and wins.
// The workflow is chosen before and its own options after; files go back as files.
function applySavedForm(formEl, form) {
  for (const el of formEl.elements) {
    if (!form || !el.name || el.type === 'file' || el.name === 'workflow' || el.name.startsWith('opt_') || !(el.name in form)) continue;
    const value = form[el.name];
    if (el.type === 'checkbox') el.checked = ['on', '1', 'true', true].includes(value);
    else if (el.type === 'radio') el.checked = el.value === String(value);
    else if (!el.options || [...el.options].some(o => o.value === String(value))) el.value = value;
  }
}
// --- The same again for a film: its settings, images, references and audio back in Generate ---
async function sameAgainFilm(id, exact = null) {
  const epoch = workspaceEpoch;
  let data;
  try { data = await (await fetch(`/runs/${encodeURIComponent(id)}`)).json(); } catch (e) { data = { error: 'Could not reach the panel. Try again.' }; }
  if (epoch !== workspaceEpoch) return false;
  if (!data.ok) { alert(data.error || 'Could not open that film.'); return false; }
  const s = data.settings, base = `/runs/${encodeURIComponent(id)}/inputs`;
  reopening('video');
  if (pipeline !== 'video') setPipeline('video');
  await loadVideoWorkflows();
  if (epoch !== workspaceEpoch) return false;
  $('videoWorkflow').value = [...$('videoWorkflow').options].some(o => o.value === s.workflow && !o.disabled) ? s.workflow : '';
  syncVideoForm();
  applySavedForm($('formVideo'), s.form);
  syncVideoForm();
  $('prompt').value = s.prompt || '';
  syncPromptWriter('video');
  $('start').value = s.start;
  $('h3FirstFrame').checked = !!s.h3_first_frame;
  $('h3MultishotSteps').value = s.h3_multishot_steps || 20;
  $('videoH3Mode').value = s.h3_enhance || 'off';
  $('videoH3Creativity').value = s.h3_creativity || 'balanced';
  $('sizePreset').value = 'custom';
  $('size').value = s.size;
  syncSize();
  $('duration').value = s.seconds;
  $('videoClipFixed').checked = !!s.clip_fixed;
  $('videoClipSeconds').value = s.clip_fixed && s.clip_seconds ? `${s.clip_seconds}-${s.clip_seconds}`
    : s.clip_range ? `${s.clip_range[0]}-${s.clip_range[1]}` : (s.form ? $('videoClipSeconds').value : '');
  $('videoPromptMode').value = s.prompt_mode || 'llm';
  syncPromptWriter('video');
  $('videoSeed').value = s.seed ?? '';
  $('review').checked = !!s.review;
  $('previewRun').checked = !!s.try_first;
  try {
    imageBoxes().forEach(clearImage);
    imagesShown = Math.max(1, s.images);
    syncImageInput();
    for (let number = 1; number <= s.images; number++) {
      const box = imageBoxes()[number - 1];
      if (!box) break;
      const file = await runFile(`${base}/image/${number}`, `image_${number}.png`);
      if (epoch !== workspaceEpoch) return false;
      putFile(box.querySelector('input[type="file"]'), file);
      showImage(box);
      syncImageInput();
      if (number > 1 && s.image_roles?.[number - 2]) box.querySelector('select').value = s.image_roles[number - 2];
    }
    // Its own audio track, as a file: a voiced film's voice isn't paid for again.
    $('audioMode').value = s.track ? 'file' : 'none';
    if (s.track) {
      const file = await runFile(`${base}/track/1`, 'audio.wav');
      if (epoch !== workspaceEpoch) return false;
      putFile($('audioFile'), file);
    }
    else $('audioFile').value = '';
    mediaBoxes().forEach(clearMedia);
    mediaShown = Math.max(1, s.references.length);
    syncMediaInput();
    const counts = { video: 0, audio: 0 };
    for (const [i, reference] of s.references.entries()) {
      const box = mediaBoxes()[i];
      if (!box) break;
      const number = ++counts[reference.kind];
      const file = await runFile(`${base}/${reference.kind}/${number}`, `${reference.kind}_${number}`);
      if (epoch !== workspaceEpoch) return false;
      putFile(box.querySelector('input'), file);
      showMedia(box);
      box.querySelector('select').value = reference.role;
      syncMediaInput();
    }
  } catch (e) {
    if (epoch !== workspaceEpoch) return false;
    alert('Some of its files could not be put back: add them again before pressing Generate.');
  }
  syncVideoForm();
  applyOptions($('videoOptionsBox'), (workflowTakes[$('videoWorkflow').value] || {}).options || [], s.options);
  // Reopened, a film comes back with every setting it was made with, its prompt model too.
  if ([...$('llm').options].some(o => o.value === s.llm && !o.disabled)) $('llm').value = s.llm;
  if (s.local_model && [...$('videoLocalModel').options].some(o => o.value === s.local_model && !o.disabled)) $('videoLocalModel').value = s.local_model;
  $('videoPromptWriterModel').value = s.local_model || '';
  if (exact) {
    // Created again from a film's shots: that one shot as a film of its own, its prompt word for word, on its seed.
    $('videoPromptMode').value = 'direct';
    $('prompt').value = exact.prompt;
    $('videoSeed').value = exact.seed || '';
    $('duration').value = exact.seconds;
    $('audioMode').value = 'none';
  }
  syncPromptWriter('video');
  syncVideoForm();
  const modelSetting = $(s.llm === 'local' ? 'videoLocalModel' : 'h3Model');
  const runModel = [...modelSetting.options].find(o => o.value === s.h3_model);
  showFormError(runModel && modelSetting.value !== s.h3_model
    ? `Made with ${runModel.textContent} as the local model. Settings now has ${modelSetting.selectedOptions[0]?.textContent}.` : '');
  offerSameSeed('videoSeed', (data.shots && data.shots[0] && (data.shots[0].used_seed ?? data.shots[0].seed)) ?? s.seed);
  saveVideoForm();
  reopened('video');
  if (WIDE.matches) $('optionsCard').scrollIntoView({ behavior: 'smooth' }); else showPage('generate');
  return true;
}
const VARIATIONS = 5;
// A Shorts run's settings back in Generate. With the same topic, pressing Generate continues that run with what you changed.
async function sameAgainShorts(id) {
  const epoch = workspaceEpoch;
  let data;
  try { data = await (await fetch(`/shorts-runs/${encodeURIComponent(id)}/form`)).json(); } catch (e) { data = { error: 'Could not reach the panel. Try again.' }; }
  if (epoch !== workspaceEpoch) return;
  if (!data.ok) { alert(data.error || 'Could not open that run.'); return; }
  reopening('shorts');
  if (pipeline !== 'shorts') setPipeline('shorts');
  await loadWorkflows();
  if (epoch !== workspaceEpoch) return;
  for (const el of $('formShorts').elements) {
    if (!el.name || el.type === 'file' || !(el.name in data.form)) continue;
    const value = data.form[el.name];
    if (el.type === 'checkbox') el.checked = !!value;
    else if (!el.options || [...el.options].some(o => o.value === String(value) && !o.disabled)) el.value = value;
  }
  syncForm();
  applyOptions($('shortsOptionsBox'), (shortsTakes[$('workflow').value] || {}).options || [], data.options);
  syncForm();
  saveForm();
  reopened('shorts');
  showFormError('');
  if (WIDE.matches) $('optionsCard').scrollIntoView({ behavior: 'smooth' }); else showPage('generate');
}
$('viewerVariations').addEventListener('click', () => {
  if (!viewing) return;
  const { id, position, film, run } = viewing;
  if (film && !run) return;
  closeViewer();
  // A picture: exactly what made it, to make it again. A film: the settings it was made with.
  if (film) sameAgainFilm(run); else sameAgain(id, null, null, position);
});
// A cut title shows whole on a click, and is cut again on the next click, or for the next picture or film (setViewerTitle).
$('viewerTitle').addEventListener('click', () => $('viewerTitle').classList.toggle('full'));
function setViewerTitle(text) {
  $('viewerTitle').classList.remove('full');
  $('viewerTitle').textContent = text;
}
let upscaleMethod = 'fast';
// The ways an image is upscaled now: a queued one from before (Ultimate SD) opens as SeedVR2.
const UPSCALE_METHODS_OFFERED = ['fast', 'ultrasharp', 'seedvr2'];
$('viewerUpscale').addEventListener('click', () => {
  const box = $('viewerUpscaleBar');
  if (box.open) return;
  const film = !!(viewing && viewing.film);
  for (const b of box.querySelectorAll('[data-for]')) b.hidden = (b.dataset.for === 'film') !== film;
  // Latent upscale only for a film it can make again: greyed out for Motion Director, Multishot, Infinite and others.
  const latent = box.querySelector('[data-method="latent"]');
  latent.disabled = film && !viewing.latent;
  latent.title = latent.disabled ? 'Not available for this film: it needs an H3 reference-to-video run that is still saved, not Motion Director, Multishot or Infinite'
    : 'H3 latent upscaler: the film is made again on the same seeds, then upscaled and refined';
  if (!film) {
    // The picture's own size: the viewer shows a screen-sized copy of a big one.
    const size = viewedImageSize(), problem = method => upscaleProblem(method, size[0], size[1]);
    for (const b of box.querySelectorAll('[data-for="image"]')) {
      const why = size ? problem(b.dataset.method) : '';
      b.disabled = !!why;
      if (!b.dataset.title) b.dataset.title = b.title;
      b.title = why || b.dataset.title;
    }
  }
  const options = [...box.querySelectorAll('button[data-method]')].filter(b => !b.hidden);
  if (options.length === 1 && !options[0].disabled) { openUpscaleSettings(options[0].dataset.method); return; }
  box.classList.remove('closing');
  box.showModal();
  placeOverViewerButtons(box);
});
// Both upscale dialogs sit over the viewer's buttons: as wide as its button bar, on its bottom edge, and at least as tall as the buttons.
function placeOverViewerButtons(box) {
  const bar = document.querySelector('#imageViewer .viewer-bar').getBoundingClientRect();
  const first = $('viewerTools').hidden ? $('viewerDownload') : $('viewerTools');
  const bottom = Math.min(bar.bottom, window.innerHeight);
  Object.assign(box.style, { margin: '0', inset: 'auto', height: 'auto', left: `${bar.left}px`, width: `${bar.width}px`,
    minHeight: `${bottom - first.getBoundingClientRect().top}px` });
  box.style.top = `${bottom - box.getBoundingClientRect().height}px`;
}
// The size of what is upscaled: the viewer's picture, or a queued upscale's source (its edit's size).
let upscaleSource = null;
// Selects a value, adding it first if the list doesn't have it (a queued job's 0.6 strength, say).
function pickOption(select, value, label) {
  value = String(value);
  if (![...select.options].some(o => o.value === value)) select.add(new Option(label || value, value));
  select.value = value;
}
// Shows the rows for this way of upscaling, and says it in the title.
function showUpscaleMethod(method) {
  upscaleMethod = method;
  if (method === 'latent') showFilmLatent();
  $('upscaleTitle').textContent = (queueUpscaleEdit ? 'Edit: ' : '') + { fast: 'Fast upscale 2×', ultrasharp: 'UltraSharp upscale 2×', seedvr2: 'SeedVR2 upscale', vsr: 'RTX VSR upscale', latent: 'Latent upscale' }[method];
  for (const row of $('upscaleSettings').querySelectorAll('[data-show]')) row.hidden = !row.dataset.show.split(' ').includes(method);
  const shorter = upscaleSource ? Math.min(...upscaleSource) : 0;
  for (const o of $('viewerUpscaleSize').options) o.disabled = !!shorter && +o.value > 0 && +o.value <= shorter;
  showUpscaleTarget();
}
// From the viewer (edit null), or for a queued upscale being edited (edit: its settings, as the queue gives them).
function openUpscaleSettings(method, edit = null) {
  upscaleSource = edit ? edit.size || null : viewedImageSize();
  $('upscaleMethodRow').hidden = !edit || edit.kind !== 'image_upscale';
  $('upscaleGo').textContent = edit ? 'Save' : 'Add to queue';
  $('upscaleGo').title = edit ? 'Saves it in the queue as it now is' : 'Adds it to the queue';
  if (edit) {
    // As it was queued: a size 3x or 4x made is said as that, a strength or denoise not in the list is added to it.
    const shorter = upscaleSource ? Math.min(...upscaleSource) : 0, resolution = +edit.resolution || 0;
    const times = [2, 3, 4].find(n => shorter && resolution === Math.min(SEEDVR2_MOST_EDGE, n * shorter));
    pickOption($('viewerUpscaleSize'), !resolution ? 'x2' : times ? `x${times}` : resolution, `${resolution}p`);
    pickOption($('viewerUpscaleDenoise'), edit.denoise || '0', `Denoise ${edit.denoise}`);
    pickOption($('viewerUpscaleStrength'), edit.strength || '1', `Upscaler ${Math.round(100 * (+edit.strength || 1))}%`);
    pickOption($('filmUpscaleScale'), edit.scale || '2', `${edit.scale}×`);
    $('filmUpscaleQuality').value = edit.quality || 'HIGHBITRATE_HIGH';
    $('upscaleMethodChoice').value = method;
  } else {
    $('viewerUpscaleSize').value = 'x2';
    if (method === 'seedvr2') $('viewerUpscaleDenoise').value = '0';
  }
  showUpscaleMethod(method);
  $('upscaleSettings').showModal();
  // Over the viewer's buttons from the viewer; in the middle of the page for a queued one.
  if (edit) $('upscaleSettings').removeAttribute('style'); else placeOverViewerButtons($('upscaleSettings'));
}
$('upscaleMethodChoice').addEventListener('change', () => showUpscaleMethod($('upscaleMethodChoice').value));
// The size it is now and the size it ends at, in the box's heading, following its settings.
const FAST_MOST_EDGE = 8192, SEEDVR2_MOST_EDGE = 2560;
// SeedVR2's shorter side for the size chosen: 2×, 3×, 4× (x2, x3, x4: within SEEDVR2_MOST_EDGE, as the server holds
// it), or a resolution such as 1080.
function seedvr2Shorter(value, shorter) {
  const times = /^x(\d)$/.exec(value || '');
  return times ? Math.min(SEEDVR2_MOST_EDGE, +times[1] * shorter) : +value || Math.min(SEEDVR2_MOST_EDGE, 2 * shorter);
}
function upscaleTarget() {
  const method = upscaleMethod;
  if (method === 'vsr' || method === 'latent') {
    const res = (upscaleSource ? upscaleSource.join('x') : $('viewerRes').textContent || '').match(/(\d+)\D+(\d+)/);
    if (!res) return null;
    const [w, h] = [+res[1], +res[2]];
    if (method === 'vsr') { const scale = +$('filmUpscaleScale').value || 2; return [[w, h], [Math.round(w * scale), Math.round(h * scale)]]; }
    const grid = n => Math.max(32, Math.round(n / 32) * 32), area = filmLatentMp * 1e6;
    return [[w, h], [grid(Math.sqrt(area * w / h)), grid(Math.sqrt(area * h / w))]];
  }
  if (!upscaleSource) return null;
  const [w, h] = upscaleSource;
  let scale = Math.min(2, FAST_MOST_EDGE / Math.max(w, h));
  if (method === 'seedvr2') scale = seedvr2Shorter($('viewerUpscaleSize').value, Math.min(w, h)) / Math.min(w, h);
  return [[w, h], [Math.round(w * scale), Math.round(h * scale)]];
}
function showUpscaleTarget() {
  const target = upscaleTarget();
  $('upscaleSettingsNote').textContent = target ? `${target[0].join('×')} → ${target[1].join('×')}` : queueUpscaleEdit ? '' : ($('viewerRes').textContent || '');
}
for (const id of ['viewerUpscaleSize', 'filmUpscaleScale']) $(id).addEventListener('change', showUpscaleTarget);
// A tap outside either dialog, on the dimmed viewer, closes it.
for (const id of ['viewerUpscaleBar', 'upscaleSettings']) $(id).addEventListener('click', e => {
  const r = e.currentTarget.getBoundingClientRect();
  if (e.target === e.currentTarget && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) {
    if (id === 'viewerUpscaleBar') closeUpscaleMenu(); else if (queueUpscaleEdit) cancelQueueUpscale(); else e.currentTarget.close();
  }
});
function closeUpscaleMenu(then) {
  const box = $('viewerUpscaleBar');
  if (!box.open || box.classList.contains('closing')) return;
  box.classList.add('closing');
  setTimeout(() => { box.close(); box.classList.remove('closing'); if (then) then(); }, 150);
}
$('viewerUpscaleBar').addEventListener('click', e => {
  const pick = e.target.closest && e.target.closest('button[data-method]');
  if (pick) closeUpscaleMenu(() => openUpscaleSettings(pick.dataset.method));
});
// A film's latent upscale: made again on the same seeds at its size, then upscaled to this many megapixels.
let filmLatentMp = 1;
function showFilmLatent() {
  const sides = ($('viewerRes').textContent || '').match(/(\d+)\D+(\d+)/);
  const area = sides ? Number(sides[1]) * Number(sides[2]) / 1e6 : 0;
  filmLatentMp = Math.min(4, Math.max(0.5, Math.round(filmLatentMp * 10) / 10));
  $('filmLatentMpValue').innerHTML = `${filmLatentMp.toFixed(1)}<span class="mp-unit">MP</span>`;
  $('filmLatentDown').disabled = filmLatentMp <= 0.5 + 1e-9;
  $('filmLatentUp').disabled = filmLatentMp >= 4 - 1e-9;
  $('filmLatentHint').textContent = area && filmLatentMp <= area ? `It is ${area.toFixed(1)} MP already: choose more.`
    : 'Renders the film again on the seeds it was made with, then upscales it: about as long as it took to make.';
  if (upscaleMethod === 'latent') showUpscaleTarget();
}
$('filmLatentDown').addEventListener('click', () => { filmLatentMp -= 0.1; showFilmLatent(); });
$('filmLatentUp').addEventListener('click', () => { filmLatentMp += 0.1; showFilmLatent(); });
$('upscaleSettings').addEventListener('click', async e => {
  if (e.target.closest && e.target.closest('#upscaleCancel')) {
    if (queueUpscaleEdit) cancelQueueUpscale(); else $('upscaleSettings').close();
    return;
  }
  const button = e.target.closest && e.target.closest('#upscaleGo');
  if (button && queueUpscaleEdit) { saveQueueUpscale(button); return; }
  if (!button || !viewing) return;
  const done = body => {
    if (!body) return;
    $('upscaleSettings').close();
    $('viewerUpscale').innerHTML = ICONS.check;
    $('viewerUpscale').title = body.queued ? 'Queued' : 'Upscaling…';
    setTimeout(() => { $('viewerUpscale').innerHTML = ICONS.upscale; $('viewerUpscale').title = 'Upscale'; }, 2500);
    poll();
  };
  let body;
  if (viewing.film) {
    const query = upscaleMethod === 'latent'
      ? `method=latent&preset=${encodeURIComponent($('filmLatentPreset').value)}&mp=${filmLatentMp.toFixed(1)}`
      : `scale=${encodeURIComponent($('filmUpscaleScale').value)}&quality=${encodeURIComponent($('filmUpscaleQuality').value)}`;
    body = await queueRequest(button, async () => (await fetch(`/films/${encodeURIComponent(viewing.name)}/upscale?${query}`, { method: 'POST' })).json());
    done(body);
    return;
  }
  const { id, position } = viewing;
  const size = $('viewerUpscaleSize').value, times = /^x(\d)$/.exec(size);
  const query = upscaleMethod === 'seedvr2' ? `?method=seedvr2&${times ? `scale=${times[1]}` : `resolution=${encodeURIComponent(size)}`}&denoise=${encodeURIComponent($('viewerUpscaleDenoise').value)}`
    : `?method=${upscaleMethod}&strength=${encodeURIComponent($('viewerUpscaleStrength').value)}`;
  body = await queueRequest(button, async () => (await fetch(`/image-runs/${encodeURIComponent(id)}/upscale/${position}${query}`, { method: 'POST' })).json());
  done(body);
});
