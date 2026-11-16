// --- Video: an image, a prompt, and prompts you can read before rendering ---
const VIDEO_STORE_KEY = 'comfyui-auto-gen.video.v1';
const VIDEO_DEFAULTS = { llm: PANEL_CONFIG.default_llm, review: false, duration: PANEL_CONFIG.film_seconds, privacy: 'private', start: 'chain', clip_relationship: 'progressive' };
// What belongs to one film rather than being the way you like to work.
// A seed is for one run: kept, it would quietly make the next film the same.
const NOT_REMEMBERED = ['prompt', 'size', 'narration', 'seed', 'areas', 'source_seed'];
// What this browser chose last, over the defaults (the local prompt model first among them).
function savedForm(key) {
  try { return JSON.parse(draftRead(key)) || {}; } catch (e) { return {}; }
}
// A file input also throws if you set its value. An image's role goes with that image.
// A workflow's own options start as it was saved, each time it's chosen.
function remembered(el) { return el.id !== 'startSingle' && el.name && el.type !== 'file' && !NOT_REMEMBERED.includes(el.name) && !/^(image_\d+|ref_media(_\d+)?)_role$/.test(el.name) && !el.name.startsWith('opt_'); }

// --- Remember the last options (per browser) ---
function saveVideoForm() {
  const data = {};
  for (const el of $('formVideo').elements) {
    if (!remembered(el)) continue;
    data[el.name] = el.type === 'checkbox' ? el.checked : el.value;
  }
  try { draftWrite(VIDEO_STORE_KEY, JSON.stringify(data)); } catch (e) {}
}
function loadVideoForm(skip = []) {
  const data = { ...VIDEO_DEFAULTS, ...savedForm(VIDEO_STORE_KEY) };
  for (const el of $('formVideo').elements) {
    if (!remembered(el) || !(el.name in data) || skip.includes(el.name)) continue;
    // A checkbox is put back even while disabled: it is only disabled until its mode is chosen, as Multishot's first frame.
    if (el.type === 'checkbox') el.checked = !!data[el.name];
    else if (!el.options || [...el.options].some(o => o.value === String(data[el.name]) && !o.disabled)) el.value = data[el.name];
  }
}
// --- Workflows saved in ComfyUI ---
const BUILT_IN_TAKES = { min_images: 1, max_images: 1, max_videos: 0, max_audios: 0, max_references: 1 };
const BUILT_IN_SAVED = 'video_LTX23_I2V_T2V.json';
// How long the built-in workflow's video model makes a clip: [shortest, longest, usual] seconds.
const BUILT_IN_CLIPS = PANEL_CONFIG.clip_seconds;
let workflowTakes = {}, workflowClips = {}, workflowMost = {}, workflowH3 = {}, workflowMultishot = {}, workflowDirector = {};
function rememberedVideoWorkflow() {
  try { return (JSON.parse(draftRead(VIDEO_STORE_KEY)) || {}).workflow || ''; } catch (e) { return ''; }
}
async function loadVideoWorkflows() {
  let data;
  try { data = await (await fetch('/api/workflows?pipeline=video')).json(); } catch (e) { return; }
  const select = $('videoWorkflow');
  const key = JSON.stringify(data);
  // Writing the options closes the list, and this also runs as it opens.
  if (select.dataset.key === key) return;
  const firstLoad = !select.dataset.key;
  const wanted = select.dataset.key ? select.value : startingWorkflow('video', rememberedVideoWorkflow);
  select.dataset.key = key;
  // Its saved copy in ComfyUI is the same workflow with its options: it takes the built-in's place in the list.
  const saved = data.workflows.find(w => w.name === BUILT_IN_SAVED && !w.problem);
  const builtIn = saved ? '' : '<option value="">LTX23_I2V_T2V</option>';
  select.innerHTML = builtIn + data.workflows.map(w =>
    `<option value="${esc(w.name)}">${esc(w.label)}</option>`).join('');
  const target = saved && !wanted ? BUILT_IN_SAVED : wanted;
  if (data.workflows.some(w => w.name === target)) select.value = target;
  workflowTakes = Object.fromEntries(data.workflows.map(w => [w.name, w.takes]));
  workflowClips = Object.fromEntries(data.workflows.map(w => [w.name, w.clip_seconds || BUILT_IN_CLIPS]));
  workflowMost = Object.fromEntries(data.workflows.map(w => [w.name, w.most_pixels || 0]));
  workflowH3 = Object.fromEntries(data.workflows.map(w => [w.name, !!w.openh3]));
  workflowMultishot = Object.fromEntries(data.workflows.map(w => [w.name, !!w.h3_multishot]));
  workflowDirector = Object.fromEntries(data.workflows.map(w => [w.name, !!w.h3_director]));
  setGuides('video', data);
  if (firstLoad) {
    // Read before the workflows were known, the form fell back on the built-in model: its 10 s clip cap cut a
    // remembered 12 s clip, and the H3 modes weren't there to choose. Now they are, so read it again.
    syncVideoForm();
    loadVideoForm(['workflow']);
  }
  syncVideoForm();
  applyDefaultPreset('video');
}
$('videoWorkflow').addEventListener('focus', loadVideoWorkflows);
function imageBoxes() { return [...$('imageBoxes').querySelectorAll('.image-box')]; }
const MOST_IMAGES = PANEL_CONFIG.most_images;
// How many boxes are open: one to start with, and + adds the next.
let imagesShown = 1;
// Clips with room for one image still leave image 2 for the LLM to put into words.
function imageBoxCount(high) { return Math.min(MOST_IMAGES, high === 1 ? 2 : high); }
function imageLabel(number, low, high) {
  const optional = number > low ? ' (optional)' : '';
  // Clips start on image 1 only when it's all they take; a reference workflow such as H3 starts none on it.
  if (number === 1 && high === 1) return low ? 'Image 1: first frame' : 'Image 1: first frame (optional)';
  if (number === 1) return `Image 1: main character${optional}`;
  return `Image ${number}${optional}`;
}
// What each image after the first is. The pipeline also knows "context", where the LLM tells by looking.
const IMAGE_ROLES = [['view', 'Same character, new view'], ['character', 'Another character'], ['place', 'Environment']];
function imageBoxHtml(number) {
  const name = number === 1 ? 'image' : `image_${number}`;
  const role = number === 1 ? '' : `
      <select class="hidden" id="${name}_role" name="${name}_role" aria-label="What image ${number} is" title="What image ${number} is" disabled>${IMAGE_ROLES.map(([value, text]) => `<option value="${value}">${text}</option>`).join('')}</select>`;
  return `
  <div class="image-box">
    <label for="${name}"></label>
    <div class="image-line">
      <label class="thumb" for="${name}" title="Choose another image"><img class="preview hidden" alt="Image ${number}"></label>
      <input id="${name}" name="${name}" type="file" accept="image/*">${role}
      ${outputPickerButton(number)}
      <button type="button" class="hidden" data-clear="1" aria-label="Remove image ${number}" title="Remove">✕</button>
    </div>
  </div>`;
}
function showImage(box) {
  const epoch = workspaceEpoch;
  const file = box.querySelector('input').files[0], preview = box.querySelector('img');
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.classList.toggle('hidden', !file);
  if (file) preview.src = URL.createObjectURL(file);
  preview.onload = () => { if (epoch === workspaceEpoch) syncSize(); };
  // A role only goes with an image, so an empty box sends none.
  const role = box.querySelector('select');
  if (role) {
    role.classList.toggle('hidden', !file);
    role.disabled = !file;
    box.classList.toggle('compact', !!file);
  }
}
function clearImage(box) {
  box.querySelector('input').value = '';
  showImage(box);
}
// A new list, because two inputs sharing one would both empty when either is cleared.
function moveImage(from, to) {
  const file = from.querySelector('input').files[0], files = new DataTransfer();
  if (file) files.items.add(file);
  to.querySelector('input').files = files.files;
  const fromRole = from.querySelector('select'), toRole = to.querySelector('select');
  if (fromRole && toRole) toRole.value = fromRole.value;
  showImage(to);
}
// The images after it move up, so the boxes stay filled in order.
function removeImage(box) {
  const open = imageBoxes().filter(other => !other.hidden);
  for (let i = open.indexOf(box); i < open.length - 1; i++) moveImage(open[i + 1], open[i]);
  const last = open[open.length - 1], role = last.querySelector('select');
  clearImage(last);
  if (role) role.value = 'view';
  imagesShown--;
}
function syncImageInput() {
  const { min_images: low, max_images: high } = workflowTakes[$('videoWorkflow').value] || BUILT_IN_TAKES;
  const room = imageBoxCount(high);
  // Images kept from a workflow that took more open their boxes again, as far as this one can take them.
  const filled = imageBoxes().reduce((last, box, i) => (box.querySelector('input').files.length ? i + 1 : last), 0);
  const shown = imagesShown = Math.min(room, Math.max(imagesShown, low, 1, filled));
  for (let number = imageBoxes().length + 1; number <= shown; number++) $('imageBoxes').insertAdjacentHTML('beforeend', imageBoxHtml(number));
  imageBoxes().forEach((box, i) => {
    const input = box.querySelector('input');
    box.hidden = i >= shown;
    // Not sent; but kept, so going back to a workflow that takes it finds it still there.
    input.disabled = box.hidden;
    box.querySelector('label').textContent = imageLabel(i + 1, low, high);
    // An empty box after the first was opened by +, so it can be closed again.
    box.querySelector('[data-clear]').classList.toggle('hidden', !i && !input.files.length);
  });
  const last = imageBoxes()[shown - 1];
  $('addImage').hidden = shown >= room || !last || !last.querySelector('input').files.length;
  const second = imageBoxes()[1];
  $('imagesHint').hidden = !(second && !second.hidden && second.querySelector('input').files.length);
  $('imagesHint').textContent = $('start').value === 'infinite' && !$('start').disabled
    ? 'Image 1 is the first frame of clip 1. Image 2 is where clip 1 ends, image 3 where clip 2 ends, and so on: a clip without one goes where its prompt takes it.'
    : high === 1
    ? 'This workflow gives its clips one image, so the video model never sees image 2. The LLM looks at it and puts what matters into the prompts in words.'
    : 'Every clip gets all of these images, and the LLM is told what each one is for.' + (shown === room && room < MOST_IMAGES ? ` This workflow takes ${room} at most.` : '');
  const workflow = $('videoWorkflow').value, chain = high === 1, director = !!workflowDirector[workflow],
        multishot = !!workflowMultishot[workflow];
  $('startChain').disabled = !chain;
  $('startDirector').disabled = !director;
  $('startMultishot').disabled = !multishot;
  // H3 Infinite takes its text encoder and VAEs from the same H3 reference workflows as Multishot.
  $('startInfinite').disabled = !multishot;
  const available = chain || director || multishot;
  if (available && (($('start').value === 'chain' && !chain) || ($('start').value === 'director' && !director)
      || (['multishot', 'infinite'].includes($('start').value) && !multishot))) $('start').value = 'image';
  $('start').disabled = !available;
  $('start').hidden = !available;
  $('startUnavailable').hidden = available;
}

// --- Reference videos and audio clips, for a workflow such as MiniMax H3 that takes them ---
const MOST_MEDIA = PANEL_CONFIG.most_media;
const VIDEO_ROLES = PANEL_CONFIG.video_roles, AUDIO_ROLES = PANEL_CONFIG.audio_roles;
let mediaShown = 1;
function mediaBoxes() { return [...$('mediaBoxes').querySelectorAll('.image-box')]; }
function mediaBoxHtml(number) {
  const name = number === 1 ? 'ref_media' : `ref_media_${number}`;
  return `
  <div class="image-box">
    <label for="${name}">Reference video or audio ${number} (optional)</label>
    <div class="image-line">
      <input id="${name}" name="${name}" type="file" accept="video/*,audio/*">
      <select class="hidden" id="${name}_role" name="${name}_role" aria-label="What reference ${number} is for" title="What reference ${number} is for" disabled></select>
      <button type="button" class="pick-output" data-pick="1" aria-label="Select reference ${number} from Output" title="Select a video from Output">${GALLERY_ICON}</button>
      <button type="button" class="hidden" data-clear="1" aria-label="Remove reference ${number}" title="Remove">✕</button>
    </div>
  </div>`;
}
function mediaKind(file) { return file && file.type.startsWith('audio') ? 'audio' : 'video'; }
// The role list follows what the file is: a video is for movement, a character or a place; audio for a voice, music or sound.
function showMedia(box) {
  const input = box.querySelector('input'), file = input.files[0], role = box.querySelector('select');
  const kind = file ? mediaKind(file) : '';
  if (role.dataset.kind !== kind) {
    role.innerHTML = (kind === 'audio' ? AUDIO_ROLES : VIDEO_ROLES).map(([value, text]) => `<option value="${value}">${text}</option>`).join('');
    role.dataset.kind = kind;
  }
  role.classList.toggle('hidden', !file);
  role.disabled = !file;
  box.querySelector('button').classList.toggle('hidden', !file);
}
function clearMedia(box) {
  box.querySelector('input').value = '';
  showMedia(box);
}
function removeMedia(box) {
  const open = mediaBoxes().filter(other => !other.hidden);
  for (let i = open.indexOf(box); i < open.length - 1; i++) {
    const files = new DataTransfer(), file = open[i + 1].querySelector('input').files[0];
    if (file) files.items.add(file);
    open[i].querySelector('input').files = files.files;
    showMedia(open[i]);
    open[i].querySelector('select').value = open[i + 1].querySelector('select').value;
  }
  clearMedia(open[open.length - 1]);
  mediaShown = Math.max(1, mediaShown - 1);
}
function syncMediaInput() {
  const takes = { ...BUILT_IN_TAKES, ...(workflowTakes[$('videoWorkflow').value] || {}) };
  const videos = takes.max_videos || 0, audios = takes.max_audios || 0;
  const images = imageBoxes().filter(box => !box.hidden && box.querySelector('input').files.length).length;
  const room = Math.max(0, Math.min(MOST_MEDIA, videos + audios, (takes.max_references ?? videos + audios + images) - images));
  $('mediaSection').hidden = !(videos + audios) || ($('start').value === 'infinite' && !$('start').disabled);
  const shown = mediaShown = Math.min(Math.max(room, 1), Math.max(mediaShown, 1));
  for (let number = mediaBoxes().length + 1; number <= shown; number++) $('mediaBoxes').insertAdjacentHTML('beforeend', mediaBoxHtml(number));
  mediaBoxes().forEach((box, i) => {
    const input = box.querySelector('input');
    box.hidden = $('mediaSection').hidden || i >= shown || !room;
    input.disabled = box.hidden;
    if (box.hidden && input.value) clearMedia(box);
  });
  const chosen = mediaBoxes().filter(box => !box.hidden && box.querySelector('input').files.length);
  const last = mediaBoxes()[shown - 1];
  $('addMedia').hidden = $('mediaSection').hidden || shown >= room || !last || !last.querySelector('input').files.length;
  const count = kind => chosen.filter(box => mediaKind(box.querySelector('input').files[0]) === kind).length;
  const over = count('video') > videos ? `This workflow takes ${videos} reference videos at most.`
    : count('audio') > audios ? `This workflow takes ${audios} reference audio clips at most.` : '';
  $('mediaHint').textContent = over || (room
    ? `Every clip gets these too: up to ${videos} videos and ${audios} audio clips, 2-15 seconds each (a longer one is cut to its first 15), and ${takes.max_references} references in all with the images. Say what each is for, and your prompt can say more.`
    : `The images take all ${takes.max_references} references this workflow has room for. Remove one to add a video or audio clip.`);
  $('mediaHint').style.color = over ? 'var(--err)' : '';
}
$('mediaBoxes').addEventListener('change', e => { showMedia(e.target.closest('.image-box')); syncMediaInput(); });
$('mediaBoxes').addEventListener('click', e => {
  const pick = e.target.closest && e.target.closest('[data-pick]');
  if (pick) { chooseFromOutput(pick.closest('.image-box'), 'video', 'media'); return; }
  if (!e.target.dataset.clear) return;
  removeMedia(e.target.closest('.image-box'));
  syncMediaInput();
});
$('addMedia').addEventListener('click', () => {
  mediaShown++;
  syncMediaInput();
});
