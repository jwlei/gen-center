// --- Image: a set of images from text or from an image, with prompts the LLM writes or you do ---
const IMAGE_STORE_KEY = 'comfyui-auto-gen.image.v1';
// An image is made in the shape of image 1 at its own size, within what the model makes well (media.pick_size).
const IMAGE_DEFAULTS = { llm: PANEL_CONFIG.default_llm, prompt_mode: 'llm', count: 1, aspect: 'image', megapixels: 'image', review: false };
const SIZE_STEP = PANEL_CONFIG.image_size_step, MEGAPIXEL = 1024 * 1024, MOST_MEGAPIXELS = 50, LARGE_MEGAPIXELS = 4;
const AUTOMATIC_TAKES = { min_images: 0, max_images: 1, size: true };
// What each model makes well, from pipelines/image/models.py.
const IMAGE_MODELS = PANEL_CONFIG.image_models;
let imageWorkflows = {}, imageWorkflowList = [], sourceSize = null;
function saveImageForm() {
  const data = {};
  for (const el of $('formImage').elements) {
    if (!remembered(el)) continue;
    data[el.name] = el.type === 'checkbox' ? el.checked : el.value;
  }
  try { draftWrite(IMAGE_STORE_KEY, JSON.stringify(data)); } catch (e) {}
}
function loadImageForm() {
  const data = { ...IMAGE_DEFAULTS, ...savedForm(IMAGE_STORE_KEY) };
  for (const el of $('formImage').elements) {
    if (!remembered(el) || !(el.name in data)) continue;
    if (el.type === 'checkbox') el.checked = !!data[el.name];
    else if (!el.options || [...el.options].some(o => o.value === String(data[el.name]) && !o.disabled)) el.value = data[el.name];
  }
  sizeFallback();
}
// An exact size with nothing typed (the box isn't remembered), or a choice that's gone: square, one megapixel.
function sizeFallback() {
  if (($('imageAspect').value === 'custom' && !$('imageSize').value.trim()) || !$('imageAspect').value) {
    $('imageAspect').value = '1:1';
    $('imageMegapixels').value = '1';
  }
}
function rememberedImageWorkflow() {
  try { return (JSON.parse(draftRead(IMAGE_STORE_KEY)) || {}).workflow || ''; } catch (e) { return ''; }
}
async function loadImageWorkflows(fresh) {
  // The list kept from last time at once (workflowList), drawn again if the one asked for behind it differs.
  let data = fresh && Array.isArray(fresh.workflows) ? fresh : null;
  if (!data) try { data = await workflowList('image', loadImageWorkflows); } catch (e) { return; }
  const select = $('imageWorkflow');
  const key = JSON.stringify(data);
  // Writing the options closes the list, and this also runs as it opens.
  if (select.dataset.key === key) return;
  const wanted = select.dataset.key ? select.value : startingWorkflow('image', rememberedImageWorkflow);
  select.dataset.key = key;
  const usable = data.workflows.filter(w => !w.problem), stuck = data.workflows.filter(w => w.problem);
  select.innerHTML = select.options[0].outerHTML + data.workflows.map(w =>
    `<option value="${esc(w.name)}"${w.problem ? ' disabled' : ''}>${esc(w.label)}${w.problem ? ' (can\'t run)' : ''}</option>`).join('');
  if (usable.some(w => w.name === wanted)) select.value = wanted;
  // Each knows its name, so what you set for it is remembered under it, Automatic's pick too.
  imageWorkflows = Object.fromEntries(usable.map(w => [w.name, { ...w.takes, name: w.name }]));
  imageWorkflowList = usable.map(w => ({ ...w.takes, name: w.name }));
  setGuides('image', data);
  const notes = stuck.map(w => `${w.label}: ${w.problem}`);
  if (!data.workflows.length) notes.push('Save one in ComfyUI with a name starting image_ and it appears here.');
  $('imageWorkflowHint').hidden = !notes.length;
  $('imageWorkflowHint').textContent = notes.join(' ');
  syncImageForm();
  queuePlan();
  applyDefaultPreset('image');
}
$('imageWorkflow').addEventListener('focus', loadImageWorkflows);
function sourceBoxes() { return [...$('imageSources').querySelectorAll('.image-box')]; }
// As the server picks on Automatic (panel/image.py): one made for what you gave it, then any that fits.
function automaticTakes(count) {
  const need = MODE_NEEDS[imageMode()];
  const usable = need ? imageWorkflowList.filter(t => IMAGE_MODELS[t.model] && IMAGE_MODELS[t.model][need]) : imageWorkflowList;
  const fits = usable.filter(t => t.min_images <= count && count <= t.max_images);
  const madeFor = fits.filter(t => count ? t.min_images >= 1 : t.max_images === 0);
  return madeFor[0] || fits[0] || null;
}
// What the form is for now: the workflow chosen, or the one Automatic would pick with the images given.
// With image to prompt, the workflow takes the picture it describes.
function imageTakes() {
  const takes = baseImageTakes(), role = imageRole();
  const found = role && (takes.options || []).find(option => option.id === role);
  return found && found.takes ? { ...takes, ...found.takes } : takes;
}
function baseImageTakes() {
  const chosen = imageWorkflows[$('imageWorkflow').value];
  if (chosen) return chosen;
  const most = Math.max(1, ...imageWorkflowList.map(t => t.max_images));
  return { ...AUTOMATIC_TAKES, ...(automaticTakes(chosenSources()) || {}), min_images: 0, max_images: Math.min(most, 20) };
}
function imageModel() { return IMAGE_MODELS[imageTakes().model] || null; }
// The painting of what to change in image 1, while it's being painted. See openPaint().
let paint = null;
// How many boxes are open: one to start with, and + adds the next, as on the Video side.
let sourcesShown = 1;
const GALLERY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>';
function outputPickerButton(number) {
  return `<button type="button" class="pick-output" data-pick="1" aria-label="Select image ${number} from Output" title="Select from Output">${GALLERY_ICON}</button>`;
}
function sourceHtml(number) {
  const name = number === 1 ? 'image' : `image_${number}`;
  return `
  <div class="image-box">
    <label for="source_${number}"></label>
    <div class="image-line">
      <label class="thumb" for="source_${number}" title="Choose another image"><img class="preview hidden" alt="Image ${number}"></label>
      <input id="source_${number}" name="${name}" type="file" accept="image/*">
      <input type="hidden" name="source_seed" class="source-seed" value="">
      ${outputPickerButton(number)}
      <button type="button" class="hidden" data-clear="1" aria-label="Remove image ${number}" title="Remove">✕</button>
    </div>
  </div>`;
}
function showSource(box, first) {
  const epoch = workspaceEpoch;
  const file = box.querySelector('input').files[0], preview = box.querySelector('img');
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.classList.toggle('hidden', !file);
  if (first) { sourceSize = null; forgetPaint(); }
  if (!file) return;
  if (first) preview.onload = () => {
    if (epoch !== workspaceEpoch) return;
    sourceSize = [preview.naturalWidth, preview.naturalHeight];
    syncImageForm();
  };
  preview.src = URL.createObjectURL(file);
}
function clearSource(box, first) {
  box.querySelector('input').value = '';
  const seed = box.querySelector('.source-seed');
  if (seed) seed.value = '';
  showSource(box, first);
}
// A new list, because two inputs sharing one would both empty when either is cleared.
function moveSource(from, to) {
  const file = from.querySelector('input').files[0], files = new DataTransfer();
  if (file) files.items.add(file);
  to.querySelector('input').files = files.files;
  to.querySelector('.source-seed').value = from.querySelector('.source-seed').value;
  showSource(to, sourceBoxes()[0] === to);
}
// The images after it move up, so the boxes stay filled in order.
function removeSource(box) {
  const open = sourceBoxes().filter(other => !other.hidden);
  for (let i = open.indexOf(box); i < open.length - 1; i++) moveSource(open[i + 1], open[i]);
  const last = open[open.length - 1];
  clearSource(last, last === open[0]);
  sourcesShown = Math.max(1, sourcesShown - 1);
}
function syncImageSources() {
  const { min_images: low, max_images: high } = imageTakes();
  const filled = sourceBoxes().reduce((last, box, i) => (box.querySelector('input').files.length ? i + 1 : last), 0);
  const shown = sourcesShown = Math.min(high, Math.max(low, 1, sourcesShown, filled));
  for (let number = sourceBoxes().length + 1; number <= shown; number++) $('imageSources').insertAdjacentHTML('beforeend', sourceHtml(number));
  const compose = imageMode() === 'compose';
  sourceBoxes().forEach((box, i) => {
    const input = box.querySelector('input');
    box.hidden = i >= shown;
    // Not sent, and what a workflow can't take doesn't wait there for the next one.
    // Not sent; but kept, so going back to a workflow that takes it finds it still there.
    input.disabled = box.hidden;
    const seed = box.querySelector('.source-seed');
    if (seed) seed.disabled = box.hidden;
    const optional = i >= low ? ', optional' : '';
    box.querySelector('label').textContent = compose ? `Image ${i + 1} (reference${optional})`
      : i ? `Image ${i + 1} (optional)`
      : low ? 'Image 1 to edit' : 'Image 1 to edit (optional: without one it makes them from text)';
    // A box opened by + can be closed again; the first only empties.
    const clear = box.querySelector('[data-clear]');
    if (clear) clear.classList.toggle('hidden', !i && !input.files.length);
  });
  const last = sourceBoxes()[shown - 1];
  $('addSource').hidden = shown >= high || !last || !last.querySelector('input').files.length;
}
function chosenSources() { return sourceBoxes().filter(box => !box.hidden && box.querySelector('input').files.length).length; }

// --- One of your images in a box: Output opens to choose it, and a tap there puts it in the box ---
// The box and side to return to after choosing an image.
let choosingFor = null;
// kind: 'image' for an image box, 'media' for a reference box, which takes a film.
function chooseFromOutput(box, side = 'image', kind = 'image') {
  const boxes = kind === 'media' ? mediaBoxes() : side === 'video' ? imageBoxes() : sourceBoxes();
  if (!boxes.includes(box) || box.hidden || box.querySelector('input').disabled) return;
  choosingFor = { box, side, kind, outputKind };
  resetOutputView();
  $('chooseBannerText').textContent = kind === 'media' ? `Open a film and press Use for reference ${boxes.indexOf(box) + 1}.`
    : `Open an image and press Use for image ${boxes.indexOf(box) + 1}.`;
  $('chooseBanner').hidden = false;
  // Output shows only what goes in the box: images, or films for a reference. Generate stays on its side.
  outputKind = kind === 'media' ? 'video' : 'image';
  redrawFiltered();
  if (WIDE.matches) $('videosCard').scrollIntoView({ behavior: 'smooth' }); else showPage('output');
}
function stopChoosing() {
  choosingFor = null;
  $('chooseBanner').hidden = true;
}
function backToGenerate(side = 'image') {
  if (choosingFor) {
    desktopGenerateActive = false;
    outputKind = choosingFor.outputKind;
    redrawFiltered();
  }
  if (pipeline !== side) setPipeline(side, false, true);
  $(side === 'video' ? 'videoGeneration' : 'imageGeneration').open = true;
  if (WIDE.matches) $('optionsCard').scrollIntoView({ behavior: 'smooth' }); else showPage('generate');
}
async function chooseThis(id, position) {
  const choice = choosingFor;
  if (!choice) return;
  backToGenerate(choice.side);
  stopChoosing();
  await useOutput(choice.box, id, position, choice.side);
}
$('chooseCancel').addEventListener('click', () => {
  if (!choosingFor) return;
  backToGenerate(choosingFor.side);
  stopChoosing();
});
async function useOutput(box, id, position, side = 'image') {
  const epoch = workspaceEpoch;
  const input = box.querySelector('input[type="file"]'), previous = input.files[0];
  try {
    const file = await runFile(`/image-runs/${encodeURIComponent(id)}/files/${position}`, `image_${position}.png`);
    if (epoch !== workspaceEpoch) return;
    let seed = '';
    if (side === 'image') {
      const response = await fetch(`/image-runs/${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error('Could not load image details.');
      const detail = await response.json();
      const shot = detail.ok && detail.shots[position - 1];
      if (!shot) throw new Error('Could not find image details.');
      if (shot.used_seed !== null && shot.used_seed !== undefined) seed = String(shot.used_seed);
    }
    if (epoch !== workspaceEpoch) return;
    const boxes = side === 'video' ? imageBoxes() : sourceBoxes();
    if (!boxes.includes(box) || box.hidden || input.disabled || input.files[0] !== previous || pipeline !== side) {
      showFormError('The image box changed before the image was loaded. Choose it again.');
      return;
    }
    putFile(input, file);
    if (side === 'image') box.querySelector('.source-seed').value = seed;
  } catch (e) {
    if (epoch !== workspaceEpoch) return;
    showFormError('Could not fetch that image. Try again.');
    return;
  }
  if (side === 'video') { showImage(box); syncVideoForm(); }
  else { showSource(box, sourceBoxes()[0] === box); syncImageForm(); }
  queuePlan();
}
$('addSource').addEventListener('click', () => {
  sourcesShown++;
  syncImageForm();
});

// --- What to do with the images: edit image 1, a new picture from them, change painted parts of it, or expand it ---
const MODE_NEEDS = { compose: 'compose', areas: 'regions', expand: 'regions' };
function imageMode() { return $('imageModeBox').hidden ? 'edit' : $('imageMode').value || 'edit'; }
// Whether the workflow chosen can, or on Automatic any workflow can.
function modeSupport() {
  const chosen = imageWorkflows[$('imageWorkflow').value];
  const all = chosen ? [chosen] : imageWorkflowList;
  const has = key => all.some(t => IMAGE_MODELS[t.model] && IMAGE_MODELS[t.model][key]);
  return { edit: true, compose: has('compose'), areas: has('regions'), expand: has('regions') };
}
const MODE_HINTS = {
  edit: '',
  compose: 'The images are references for a new picture: a person, a product, a place, a style. Its size is the one under Resolution.',
  areas: 'Only what you paint changes, and the rest of the image stays exactly as it is.',
  expand: 'The new borders are drawn to continue the picture, and the picture itself stays exactly as it is.',
};
function syncImageMode() {
  const can = modeSupport();
  for (const option of [...($('imageMode').options || [])]) option.disabled = !can[option.value];
  if (!can[$('imageMode').value]) $('imageMode').value = 'edit';
  $('imageModeBox').hidden = !chosenSources() || !(can.compose || can.areas || can.expand);
  const mode = imageMode();
  $('imageModeHint').textContent = MODE_HINTS[mode] || '';
  $('areasBox').hidden = mode !== 'areas';
  $('expandBox').hidden = mode !== 'expand';
  $('detailBox').hidden = !(chosenSources() >= 2 || mode === 'compose');
  const model = imageModel();
  $('transparentBox').hidden = !(model && model.transparent) || mode === 'areas' || mode === 'expand';
  if (mode === 'expand') syncExpand();
}
function syncExpand() {
  const sides = ['expandLeft', 'expandTop', 'expandRight', 'expandBottom'].map(id => Math.max(0, +$(id).value || 0));
  if (!sourceSize) { $('expandHint').textContent = ''; return; }
  const [width, height] = sourceSize, percent = $('expandUnits').value === 'percent';
  const px = sides.map((value, i) => Math.round(percent ? value / 100 * (i % 2 ? height : width) : value));
  $('expandHint').textContent = px.some(Boolean)
    ? `From ${width}x${height} to ${width + px[0] + px[2]}x${height + px[1] + px[3]}.` : 'Say how far to expand it on at least one side.';
}
for (const id of ['expandLeft', 'expandTop', 'expandRight', 'expandBottom']) $(id).addEventListener('input', syncExpand);
