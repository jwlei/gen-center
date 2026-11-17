// Upscale, under Resolution: each image made twice as big as it comes out, before it is saved.
const IMAGE_UPSCALE_OPTIONS = ['image_upscale', 'image_upscale_denoise', 'image_upscale_size', 'image_upscale_scale', 'image_upscale_mp'];
const IMAGE_UPSCALE_KEY = 'gen-center.imageUpscale';
const IMAGE_UPSCALE_HINTS = {
  Off: 'Each image is made at the resolution, as it is.',
  UltraSharp: '4x-UltraSharp: the picture as it is, enlarged to the size the stepper sets, with crisper edges. Seconds.',
  SeedVR2: 'SeedVR2 draws finer detail as it enlarges to the size the stepper sets (up to 4K on its shorter side). Minutes. Denoise adds noise as it does: 0 restores it as it is, more draws more in.',
};
function savedImageUpscale() {
  try { return JSON.parse(localStorage.getItem(IMAGE_UPSCALE_KEY) || '{}') || {}; } catch (e) { return {}; }
}
function rememberImageUpscale() {
  try { localStorage.setItem(IMAGE_UPSCALE_KEY, JSON.stringify({ method: $('imageUpscale').value, seedvr2Denoise: $('imageUpscaleDenoise').value, factor: $('imageUpscaleFactor').value })); } catch (e) {}
}
function syncImageUpscale(options) {
  const choice = options.find(option => option.id === 'image_upscale'), box = $('imageUpscaleBox');
  box.hidden = !choice;
  $('imageUpscale').disabled = $('imageUpscaleDenoise').disabled = !choice;
  box.limits = choice ? choice.limits || {} : {};
  if (choice) {
    const key = JSON.stringify(choice.choices);
    if (box.dataset.key !== key) {
      const first = !box.dataset.key, saved = savedImageUpscale(), was = first ? 'Off' : $('imageUpscale').value;
      box.dataset.key = key;
      $('imageUpscale').innerHTML = choice.choices.map(value => `<option>${esc(value)}</option>`).join('');
      $('imageUpscale').value = choice.choices.includes(was) ? was : choice.default;
      // SeedVR2's own: a denoise kept from Ultimate SD's means something else, so it isn't taken.
      if (first && saved.seedvr2Denoise) setImageUpscaleDenoise(saved.seedvr2Denoise);
      if (first && saved.factor) $('imageUpscaleFactor').value = saved.factor;
    }
  }
  showImageUpscale();
  syncImageSize();
}
function showImageUpscale() {
  const method = $('imageUpscale').value;
  // Only what goes with the upscale chosen: SeedVR2's 2×, 3× or 4× and its denoise.
  $('imageUpscaleDenoiseRow').hidden = method !== 'SeedVR2';
  $('imageUpscaleFactorRow').hidden = method !== 'SeedVR2';
  showResHint('imageUpscaleInfo', IMAGE_UPSCALE_HINTS[method] || '');
}
// Upscale off: back to the size it was being made at, 500×1000 for an upscale that ended at 1000×2000.
$('imageUpscale').addEventListener('change', () => {
  const now = $('imageUpscale').value;
  if (now === 'Off' && imageMadeAt != null) {
    imageStep = imageMadeAt;
    $('imageMegapixels').dataset.sent = $('imageMegapixels').value;
  }
  // Upscale on: made at the resolution there is now, ending as many times bigger as this upscale goes, not at where
  // the last one ended.
  if (imageUpscaleWas === 'Off' && now !== 'Off') $('imageUpscaleMp').value = imageOffMp != null ? (imageOffMp * imageUpscaleArea()).toFixed(2) : '';
  imageUpscaleWas = now;
  imageMadeAt = null;
  showImageUpscale();
  rememberImageUpscale();
  syncImageSize();
});
// SeedVR2's denoise in Generate: 0 to 0.05, a hundredth at a time, 0 unless set. What was kept from before is held
// to that: Ultimate SD's 0.2 or the 0.1 of a wider range would be far more than these go to.
const IMAGE_DENOISE_MOST = 0.05, IMAGE_DENOISE_STEP = 0.01;
function setImageUpscaleDenoise(value) {
  const hundredths = Math.min(Math.round(IMAGE_DENOISE_MOST / IMAGE_DENOISE_STEP), Math.max(0, Math.round((+value || 0) / IMAGE_DENOISE_STEP)));
  const denoise = +(hundredths * IMAGE_DENOISE_STEP).toFixed(2);
  $('imageUpscaleDenoise').value = String(denoise);
  $('imageUpscaleDenoiseValue').textContent = String(denoise);
  $('imageUpscaleDenoiseDown').disabled = hundredths <= 0;
  $('imageUpscaleDenoiseUp').disabled = denoise >= IMAGE_DENOISE_MOST;
}
for (const [id, by] of [['imageUpscaleDenoiseDown', -1], ['imageUpscaleDenoiseUp', 1]]) {
  $(id).addEventListener('click', () => {
    setImageUpscaleDenoise(+$('imageUpscaleDenoise').value + by * IMAGE_DENOISE_STEP);
    rememberImageUpscale();
    queuePlan();
  });
}
setImageUpscaleDenoise(0);
// Another factor keeps the size it's made at, and ends that many times bigger.
$('imageUpscaleFactor').addEventListener('change', () => {
  if (imageMadeAt != null) $('imageUpscaleMp').value = (imageMadeAt * imageUpscaleArea()).toFixed(2);
  rememberImageUpscale();
  syncImageSize();
});
// The workflow writing its own prompts: its prompt enhancer, or image to prompt.
const ROLE_LABELS = { image_to_prompt: 'Image to prompt', prompt_enhancer: 'Prompt enhancer' };
// One with a name of its own (named), such as MiniMax H3 Image's "Prompt enhancer H3"; otherwise the usual one.
function roleLabel(role) { return role.named ? role.label : ROLE_LABELS[role.id] || role.label; }
function syncImageLlm() {
  const select = $('imageLlm');
  const roles = (baseImageTakes().options || []).filter(option => option.role && !option.problem);
  const key = roles.map(option => `${option.id}:${roleLabel(option)}`).join(',');
  if (select.dataset.roles === key) return;
  select.dataset.roles = key;
  const wanted = select.value;
  for (const option of [...(select.options || [])].filter(option => option.dataset && option.dataset.role)) option.remove();
  const order = Object.keys(ROLE_LABELS);
  for (const role of [...roles].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))) {
    select.insertAdjacentHTML('beforeend', `<option value="${esc(role.id)}" data-role="1">${esc(roleLabel(role))}</option>`);
  }
  // What was chosen stays chosen: a workflow with its own prompt enhancer offers it, and never picks it by itself.
  if ([...(select.options || [])].some(option => option.value === wanted)) select.value = wanted;
  else if (ROLE_LABELS[wanted]) select.value = IMAGE_DEFAULTS.llm;
}
function imageRole() { return ROLE_LABELS[$('imageLlm').value] && $('imagePromptMode').value === 'llm' ? $('imageLlm').value : null; }
$('imageWords').addEventListener('input', () => syncWords('image', +$('imageCount').value || 1));
function syncImageForm() {
  syncGuideLink('image');
  syncImageLlm();
  // For image to prompt, the image it describes goes right under that choice; otherwise back in Generation.
  const slot = imageRole() === 'image_to_prompt' ? $('imageToPromptSlot') : $('imageSourcesHome');
  if ($('imageSources').parentNode !== slot) slot.appendChild($('imageSources'));
  syncImageSources();
  syncImageMode();
  syncImageSources();
  syncImageOptions();
  syncImageAmount();
  syncImageSize();
  const direct = $('imagePromptMode').value === 'direct';
  const editing = !!chosenSources();
  const mode = imageMode();
  $('imageLlmBox').classList.toggle('hidden', direct);
  // Variety and Explicit, under the prompt and negative prompt: for the LLM, so with it. An LLM comparison is written
  // whatever How says, so its words and Explicit show with it too: to test what each model writes.
  const comparingLlms = $('imageLlmTest').checked;
  $('imageWriterExtras').classList.toggle('hidden', direct && !comparingLlms);
  const local = !direct && $('imageLlm').value === 'local' && mode !== 'areas' && mode !== 'expand';
  $('imageLocalModelBox').hidden = !local;
  $('imageLocalModel').disabled = !local;
  // The workflow's prompt enhancer writes them in ComfyUI first, to read before rendering; image to prompt can't.
  $('imageReviewBox').classList.toggle('hidden', direct || mode === 'expand' || mode === 'areas' || (!!imageRole() && imageRole() !== 'prompt_enhancer'));
  $('imageHowDirect').hidden = !direct;
  $('imagePromptLabel').textContent = 'Prompt';
  $('imagePrompt').placeholder = direct
    ? (editing ? 'e.g. Change her coat to a red wool trench coat. Keep her face, pose and the background the same.' : 'e.g. Photo of a lighthouse at dusk, long exposure, wet rocks in the foreground.')
    : (editing ? 'e.g. Recreate this with different outfits and hairstyles' : 'e.g. A lighthouse in every season');
  // Written by an LLM, all in one reply: up to 30. Your prompt as it is: up to 50.
  const most = +(direct ? $('imageCount').dataset.most : $('imageCount').dataset.mostWritten) || 30;
  $('imageCount').max = most;
  // A LoRA comparison's own number, shown while it locks Amount, isn't held to that.
  if (!$('imageCount').disabled && +$('imageCount').value > most) $('imageCount').value = most;
  const count = +$('imageCount').value || 1;
  // Variety and its chips: how different the prompts are, so only for a set an LLM writes.
  // Each model in an LLM comparison writes one prompt: nothing to vary between them.
  $('imageVarietyBox').hidden = count < 2 || !!imageRole() || comparingLlms;
  // Words per prompt: for the pictures an LLM describes in prose. Edit instructions and Fibo 2.0's captions keep their own.
  $('imageWordsBox').hidden = !!imageRole() || imageTakes().model === 'fibo2' || (editing && mode !== 'compose');
  syncWords('image', count);
  const written = (imageModel() || {}).most_written;
  const tooMany = !direct && written && count > written ? ` ${imageModel().label}'s prompts are long, so the LLM writes at most ${written} at a time.` : '';
  $('imagePromptHint').textContent = direct
    ? (count > 1 ? `The same prompt ${count} times, each on a new seed.` : 'Goes to the model as you wrote it.')
    : (count > 1 ? `A sentence or two is enough. The LLM writes ${count} prompts that differ from each other.` : 'A sentence or two is enough.') + tooMany;
  // Painted areas carry their own words; an expansion only says what the new parts show, if anything.
  $('imagePromptSection').hidden = mode === 'areas';
  if (mode === 'expand') {
    $('imageLlmBox').classList.add('hidden');
    $('imageWriterExtras').classList.add('hidden');
    $('imageHowDirect').hidden = true;
    $('imagePromptMode').disabled = true;
    $('imagePromptLabel').textContent = 'What the new parts show (optional)';
    $('imagePrompt').placeholder = 'e.g. more of the beach, and a pier on the right';
    $('imagePromptHint').textContent = 'Left empty, the model continues what it sees.';
  } else {
    $('imagePromptMode').disabled = false;
  }
}
$('formImage').addEventListener('change', () => { syncImageForm(); saveImageForm(); });
$('imageLlm').addEventListener('change', async () => {
  if ($('imageLlm').value !== 'local') return;
  try { await refreshLocalModels(); } catch (e) {
    $('imagePromptWriteError').textContent = e.message || 'Could not load local models.';
    $('imagePromptWriteError').hidden = false;
  }
});
$('imageCount').addEventListener('input', syncImageForm);
$('imageSize').addEventListener('input', syncImageSize);
$('imageSources').addEventListener('change', e => {
  const seed = e.target.closest('.image-box').querySelector('.source-seed');
  // A file of your own: what made it isn't known here, and the panel reads it from the file itself.
  if (seed) seed.value = '';
  showSource(e.target.closest('.image-box'), sourceBoxes()[0] === e.target.closest('.image-box'));
  syncImageForm();
});
$('imageSources').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('button');
  if (!button) return;
  const box = button.closest('.image-box');
  if (button.dataset.pick) { chooseFromOutput(box); return; }
  if (!button.dataset.clear) return;
  removeSource(box);
  syncImageForm();
  queuePlan();
});
function imageOptionsOnly() {
  // The estimate only needs the options, so it doesn't send the whole images on every change.
  const body = new FormData($('formImage'));
  body.append('image_count', chosenSources());
  body.delete('prompt');
  for (const box of sourceBoxes()) body.delete(box.querySelector('input').name);
  return body;
}
