// --- Video resolution: image 1's shape or an aspect ratio, sized a tenth of a megapixel at a time; or a preset ---
// Untouched, "same shape as image 1" sends no size: the pipeline makes it 480p's pixel count in image 1's shape.
const VIDEO_STEP = 32, VIDEO_DEFAULT_AREA = 864 * 480, VIDEO_FULL_AREA = 1280 * 736;
let videoMegapixels = null;  // null: the default pixel count; else what the stepper chose
function videoMostPixels() { return Math.min(workflowMost[$('videoWorkflow').value] || VIDEO_FULL_AREA, VIDEO_FULL_AREA); }
function videoArea() { return Math.min(videoMegapixels == null ? VIDEO_DEFAULT_AREA : videoMegapixels * 1e6, videoMostPixels()); }
// Image 1's shape, from its preview once that has loaded; 16:9 until then.
function videoImageShape() {
  const preview = imageBoxes()[0] && imageBoxes()[0].querySelector('img');
  return preview && preview.naturalWidth && !preview.classList.contains('hidden') ? [preview.naturalWidth, preview.naturalHeight] : [1280, 736];
}
// Rounded down onto the grid, so the pixel count stays within the model's.
function videoSized(ratio, area = videoArea()) {
  const side = value => Math.max(VIDEO_STEP, Math.floor(value / VIDEO_STEP) * VIDEO_STEP);
  return [side(Math.sqrt(area * ratio)), side(Math.sqrt(area / ratio))];
}
function videoLatentOn() {
  return !$('videoLatentBox').hidden && !$('videoLatentUpscale').disabled && $('videoLatentUpscale').value !== 'Off';
}
// Resolution, latent upscale and the stepper as one: the resolution is what the clip is made at (a screen exactly, an
// aspect ratio at 480p's pixel count); the stepper scales it, whatever was picked. With latent upscale on, the stepper
// sets the size it ends at instead. Past what the workflow makes well it would very likely run out of memory: held to
// the nearest below.
let videoBase = null;
function syncSize() {
  const most = videoMostPixels(), on = videoLatentOn();
  $('size').placeholder = `Up to ${(most / 1e6).toFixed(2)} megapixels, such as 960x544`;
  const preset = $('sizePreset').value, custom = preset === 'custom', fixed = /^\d+x\d+$/.test(preset), shape = /^\d+:\d+$/.test(preset);
  $('size').hidden = !custom;
  if (on) { syncUpscaledSize(preset, custom, fixed, shape, most); return; }
  const stepped = videoMegapixels != null;
  const area = videoArea();
  let sides = null, note = '';
  const held = (w, h) => {
    sides = videoSized(w / h, most);
    note = `${w}×${h} is past the ${(most / 1e6).toFixed(2)} MP this workflow makes well: made at ${sides.join('×')}, the nearest below.`;
  };
  if (fixed) {
    const [w, h] = preset.split('x').map(Number);
    if (stepped) sides = videoSized(w / h, area);
    else if (w * h > most) held(w, h);
    else sides = [w, h];
  } else if (shape) { const [w, h] = preset.split(':').map(Number); sides = videoSized(w / h, area); }
  else if (!custom) { const [w, h] = videoImageShape(); sides = videoSized(w / h, area); }
  else {
    const typed = /^(\d+)x(\d+)$/i.exec($('size').value.trim());
    if (typed) {
      const [w, h] = [+typed[1], +typed[2]];
      if (stepped) { sides = videoSized(w / h, area); $('size').value = sides.join('x'); videoMegapixels = null; }
      else if (w * h > most) { held(w, h); $('size').value = sides.join('x'); }
      else sides = [w, h];
    }
  }
  if (!custom) $('size').value = fixed || shape || stepped || note ? sides.join('x') : '';
  videoBase = sides;
  const base = sides ? sides[0] * sides[1] / 1e6 : area / 1e6;
  videoOffMp = sides ? base : null;
  showVideoStepper(base, 0.1, most / 1e6, sides, null, note, false);
}
// The size an upscale ends at; with it off, what twice each way would come to, faded and marked 2×, so the choice
// can be weighed before turning it on.
function showUpscaleEnd(out, end, off) {
  const would = !end && off ? off.map(side => side * 2) : null;
  if (would) out.innerHTML = `<span class="would-tag">2×</span>${would.join('×')}`;
  else out.textContent = end ? end.join('×') : '';
  out.classList.toggle('would-be', !!would);
  out.title = would ? 'What a 2× upscale would make' : '';
}
function showVideoStepper(mp, least, top, sides, end, note, on) {
  // Resolution: the size it is made at. Latent upscale: the size it ends at.
  $('videoPixelSize').textContent = sides ? sides.join('×') : '';
  showUpscaleEnd($('videoLatentSize'), end, !on && sides);
  drawAspect($('videoAspectBox'), ...(sides || [0, 0]));
  if (!$('videoMegapixelsValue').querySelector('input')) $('videoMegapixelsValue').innerHTML = `${mp.toFixed(1)}<span class="mp-unit">MP</span>`;
  $('videoMegapixelsValue').title = on ? 'The size it ends at; the size it is made at follows' : '';
  $('videoMegapixelsValue').setAttribute('aria-label', on ? 'Megapixels it ends at' : 'Megapixels');
  $('videoMegapixelsDown').disabled = mp <= least + 1e-9;
  $('videoMegapixelsUp').disabled = mp + 0.1 > top + 1e-9;
  $('videoResNote').textContent = note;
  $('videoResNote').hidden = !note;
  showVideoLatent();
}
// With latent upscale on, the stepper sets the size it ends at, within what the workflow makes well, and the size the
// clip is made at follows: a quarter of the pixels (twice as big each way). A screen is where it ends unless stepped.
const LATENT_AREA = 4, LATENT_LEAST = 0.2;
// Where latent upscale may end. The workflow's own limit (H3's 960x544) is what it *makes* a clip at in a sensible time;
// the refine is one to three steps, so what holds it back is memory, which follows pixels times frames. A clip at that
// limit and the model's longest length is known to fit: half as much again is allowed, spread over the longest clip
// chosen, up to the 4 MP the upscaler takes.
const LATENT_MOST = 4, LATENT_HEADROOM = 1.5;
function latentTop(most) {
  const [, longestChosen] = videoClips(), [, longestModel] = modelClips();
  const budget = most / 1e6 * longestModel * LATENT_HEADROOM;
  return Math.floor(Math.min(LATENT_MOST, Math.max(most / 1e6, budget / Math.max(1, longestChosen))) * 10) / 10;
}
let videoMadeAt = null;  // With latent upscale on: the megapixels the clip is made at, for Off to drop back to
let videoOffMp = null, videoLatentWas = 'Off';  // With it off: the resolution's megapixels, for On to start from
function syncUpscaledSize(preset, custom, fixed, shape, most) {
  let ratio, exact = null;
  if (fixed) exact = preset.split('x').map(Number);
  else if (custom) { const typed = /^(\d+)x(\d+)$/i.exec($('size').value.trim()); if (typed) exact = [+typed[1], +typed[2]]; }
  if (exact) ratio = exact[0] / exact[1];
  else if (shape) { const [w, h] = preset.split(':').map(Number); ratio = w / h; }
  else { const [w, h] = videoImageShape(); ratio = w / h; }
  // Typed, it is the size the clip is made at, and the end follows it (four times the pixels) until stepped.
  const typedMp = custom && exact ? exact[0] * exact[1] / 1e6 : null;
  const top = latentTop(most), exactMp = exact ? exact[0] * exact[1] / 1e6 : null;
  const wanted = Number($('videoLatentMp').value) || (typedMp ? typedMp * LATENT_AREA : exactMp) || Math.min(top, 1);
  const mp = Math.min(top, Math.max(LATENT_LEAST, Math.round(wanted * 10) / 10));
  const longest = videoClips()[1];
  const note = wanted > top + 0.05
    ? `Held to ${top.toFixed(1)} MP: refining ${longest}s clips any bigger would very likely run out of memory on this card. Shorter clips can go bigger.` : '';
  $('videoLatentMp').value = mp.toFixed(1);
  // Made at a quarter of where it ends, within what the workflow makes in a sensible time.
  const madeAt = Math.min(most / 1e6, Math.max(0.1, mp / LATENT_AREA)), sides = videoSized(ratio, madeAt * 1e6);
  const end = exact && !custom && Math.abs(mp - exactMp) < 0.05 ? exact : videoSized(ratio, mp * 1e6);
  // The size it's made at goes as the size, and shows in the box (not while it's being typed in).
  if (!custom || document.activeElement !== $('size')) $('size').value = sides.join('x');
  videoBase = sides;
  videoMadeAt = madeAt;
  showVideoStepper(mp, LATENT_LEAST, top, sides, end, note, true);
}
$('sizePreset').addEventListener('change', () => {
  // Custom size starts from the size the clip was being made at; with latent upscale on, where it ends stays.
  if ($('sizePreset').value === 'custom' && videoBase) { $('size').value = videoBase.join('x'); videoMegapixels = null; return; }
  videoMegapixels = null;
  $('videoLatentMp').value = '';
});
$('size').addEventListener('input', () => { if (videoLatentOn()) $('videoLatentMp').value = ''; });
$('size').addEventListener('blur', () => syncSize());
// Latent upscale, under Resolution: the clip is made at the size above, its latent made this big, then refined.
const LATENT_OPTIONS = ['latent_upscale', 'latent_upscale_mp', 'latent_upscale_denoise', 'latent_upscale_steps', 'latent_upscale_chunking', 'latent_upscale_sampler'];
const LATENT_FIELDS = ['videoLatentUpscale', 'videoLatentMp', 'videoLatentDenoise', 'videoLatentSteps', 'videoLatentSampler', 'videoLatentChunking', 'videoLatentChunkingOff'];
const LATENT_KEY = 'gen-center.videoLatent';
function savedLatent() {
  try { return JSON.parse(localStorage.getItem(LATENT_KEY) || '{}') || {}; } catch (e) { return {}; }
}
function rememberLatent() {
  try {
    localStorage.setItem(LATENT_KEY, JSON.stringify({ preset: $('videoLatentUpscale').value, mp: $('videoLatentMp').value,
      denoise: $('videoLatentDenoise').value, steps: $('videoLatentSteps').value, sampler: $('videoLatentSampler').value,
      chunking: $('videoLatentChunking').checked }));
  } catch (e) {}
}
// H3 Motion Director, Multishot and Infinite make their clips their own way: there is no latent between to upscale.
function latentUnavailable() {
  const start = $('start').hidden ? 'image' : $('start').value;
  return { director: 'H3 Motion Director', multishot: 'H3 Multishot', infinite: 'H3 Infinite continuation' }[start] || '';
}
function syncVideoLatent(options) {
  const preset = options.find(option => option.id === 'latent_upscale'), mp = options.find(option => option.id === 'latent_upscale_mp');
  const box = $('videoLatentBox'), h3 = !!workflowH3[$('videoWorkflow').value] || !!workflowMultishot[$('videoWorkflow').value] || !!workflowDirector[$('videoWorkflow').value];
  const unavailable = latentUnavailable() || (!preset && h3 ? 'this workflow' : '');
  // Shown greyed where it can't be used on an H3 workflow, and not at all on others.
  box.hidden = !preset && !unavailable;
  box.classList.toggle('unavailable', !!unavailable);
  for (const id of LATENT_FIELDS) $(id).disabled = box.hidden || !!unavailable;
  if (box.hidden) return;
  $('videoLatentNote').textContent = unavailable ? `Not available with ${unavailable}: it makes its clips without a latent to upscale.` : '';
  $('videoLatentNote').hidden = !unavailable;
  if (!preset) {
    $('videoLatentUpscale').innerHTML = '<option>Off</option>';
    // Its list is gone now: a workflow that has it fills it again.
    box.dataset.key = '';
    $('videoLatentCustom').hidden = true;
    $('videoLatentSize').textContent = '';
    showResHint('videoLatentInfo', '');
    return;
  }
  const sampler = options.find(option => option.id === 'latent_upscale_sampler');
  const samplerKey = JSON.stringify(sampler ? sampler.choices : []);
  if ($('videoLatentSampler').dataset.key !== samplerKey) {
    const was = $('videoLatentSampler').value || savedLatent().sampler;
    $('videoLatentSampler').dataset.key = samplerKey;
    $('videoLatentSampler').innerHTML = (sampler ? sampler.choices : ['Same as the clip']).map(value => `<option>${esc(value)}</option>`).join('');
    if (sampler && sampler.choices.includes(was)) $('videoLatentSampler').value = was;
  }
  const key = JSON.stringify([preset.choices, mp.min, mp.max]);
  if (box.dataset.key !== key) {
    const first = !box.dataset.key, saved = savedLatent(), was = first ? 'Off' : $('videoLatentUpscale').value;
    box.dataset.key = key;
    box.dataset.min = mp.min;
    box.dataset.max = mp.max;
    $('videoLatentUpscale').innerHTML = preset.choices.map(value => `<option>${esc(value)}</option>`).join('');
    $('videoLatentUpscale').value = preset.choices.includes(was) ? was : preset.default;
    if (first) {
      $('videoLatentMp').value = saved.mp || mp.default;
      if (saved.denoise) $('videoLatentDenoise').value = saved.denoise;
      if (saved.steps) $('videoLatentSteps').value = saved.steps;
      if (saved.chunking === false) $('videoLatentChunking').checked = false;
    }
  }
  if (unavailable) $('videoLatentUpscale').value = 'Off';
  syncSize();
}
const LATENT_HINTS = {
  Off: 'The clip is made at the resolution, as it is.',
  Clean: 'Made at the resolution, its latent enlarged to the size the stepper sets, then one light refine step: sharper, the clip as it was.',
  'Hires fix': 'Made at the resolution, enlarged to the size the stepper sets, then refined over two steps (about a 0.35 denoise): skin, hair and texture drawn in.',
  Heavy: 'Made at the resolution, enlarged, then refined over three steps (about 0.45): more new detail, a little drift from the clip.',
  Custom: 'Made at the resolution, enlarged to the size the stepper sets, then refined as set below: more denoise draws in more.',
};
function showVideoLatent() {
  if ($('videoLatentBox').hidden) return;
  $('videoLatentCustom').hidden = $('videoLatentUpscale').value !== 'Custom' || $('videoLatentUpscale').disabled;
  showResHint('videoLatentInfo', LATENT_HINTS[$('videoLatentUpscale').value] || '');
}
// Latent upscale off: back to the size the clip was being made at.
$('videoLatentUpscale').addEventListener('change', () => {
  const now = $('videoLatentUpscale').value;
  if (now === 'Off' && videoMadeAt != null) {
    videoMegapixels = videoMadeAt;
  }
  // On: made at the resolution there is now, ending four times the pixels (within what the workflow makes well).
  if (videoLatentWas === 'Off' && now !== 'Off') $('videoLatentMp').value = videoOffMp != null ? (videoOffMp * LATENT_AREA).toFixed(2) : '';
  videoLatentWas = now;
  videoMadeAt = null;
  syncSize();
  rememberLatent();
});
$('videoLatentCustom').addEventListener('change', rememberLatent);
$('videoLatentCustomToggle').addEventListener('click', () => {
  const open = $('videoLatentCustom').classList.toggle('open');
  $('videoLatentCustomToggle').setAttribute('aria-expanded', String(open));
});
function stepVideoMegapixels(by) {
  if (videoLatentOn()) {
    $('videoLatentMp').value = (Math.round((Number($('videoLatentMp').value) + by) * 10) / 10).toFixed(1);
    rememberLatent();
  } else {
    const from = videoBase ? videoBase[0] * videoBase[1] / 1e6 : videoArea() / 1e6;
    videoMegapixels = Math.min(videoMostPixels() / 1e6, Math.max(0.1, Math.round((from + by) * 10) / 10));
  }
  syncSize();
  $('size').dispatchEvent(new Event('change', { bubbles: true }));
}
$('videoMegapixelsDown').addEventListener('click', () => stepVideoMegapixels(-0.1));
$('videoMegapixelsUp').addEventListener('click', () => stepVideoMegapixels(0.1));
// A tap on the number asks for one: past what is allowed it goes to the nearest limit.
$('videoMegapixelsValue').addEventListener('click', () => {
  editMegapixels($('videoMegapixelsValue'), value => {
    if (value != null) {
      if (videoLatentOn()) { $('videoLatentMp').value = value.toFixed(1); rememberLatent(); }
      else videoMegapixels = Math.min(videoMostPixels() / 1e6, Math.max(0.1, Math.round(value * 10) / 10));
    }
    syncSize();
    $('size').dispatchEvent(new Event('change', { bubbles: true }));
  });
});
$('size').addEventListener('input', syncSize);
function syncAudio() {
  const mode = $('audioMode').value;
  $('audioFileBox').classList.toggle('hidden', mode !== 'file');
  $('narrationBox').classList.toggle('hidden', mode !== 'text');
  $('audioHint').hidden = mode === 'none';
  // The audio sets the length, so the slider has nothing to say.
  $('durationBox').classList.toggle('hidden', mode !== 'none');
}
function syncH3Controls(side, available) {
  const box = $(side + 'H3Box'), mode = $(side + 'H3Mode'), creativity = $(side + 'H3Creativity');
  box.hidden = !available;
  mode.disabled = !available;
  const enabled = available && mode.value !== 'off';
  $(side + 'H3Enabled').checked = enabled;
  $(side + 'H3Enabled').disabled = !available;
  $(side + 'H3CreativityBox').hidden = !enabled;
  creativity.disabled = !enabled;
}
for (const side of ['video', 'shorts']) {
  $(side + 'H3Enabled').addEventListener('change', e => {
    const mode = $(side + 'H3Mode');
    if (!e.target.checked && mode.value !== 'off') mode.dataset.lastMode = mode.value;
    mode.value = e.target.checked ? (mode.dataset.lastMode || 'render') : 'off';
  });
}
function syncVideoForm() {
  syncGuideLink('video');
  syncImageInput();
  const seconds = +$('duration').value, [shortest] = videoClips();
  const adjusted = $('videoClipFixed').checked
    ? Math.min(Math.floor(+$('duration').max / shortest), Math.max(1, Math.floor(seconds / shortest + .5))) * shortest : seconds;
  const single = $('audioMode').value === 'none' && $('duration').value && Number.isInteger(seconds)
    && seconds >= +$('duration').min && seconds <= +$('duration').max && shotCount(adjusted) === 1;
  // One clip has nothing to connect to: it shows as Separate moments, and goes as one.
  $('startSingle').disabled = !single;
  if (single) {
    $('start').disabled = $('start').hidden = true;
    $('startUnavailable').hidden = false;
  }
  const multishot = !single && $('start').value === 'multishot' && !!workflowMultishot[$('videoWorkflow').value];
  if (multishot && !$('videoClipFixed').checked) {
    const [, , usual] = videoClips();
    $('videoClipFixed').checked = true;
    $('videoClipSeconds').value = `${usual}-${usual}`;
  }
  $('videoClipFixedButton').disabled = multishot;
  $('multishotOptions').hidden = !multishot;
  $('h3FirstFrame').disabled = !multishot;
  $('h3MultishotSteps').disabled = !multishot;
  syncPreviewRun();
  syncVideoClips();
  // Your prompt as it is, for every clip, or the LLM writing one per clip from it.
  const direct = $('videoPromptMode').value === 'direct';
  const infinite = !single && $('start').value === 'infinite' && !!workflowMultishot[$('videoWorkflow').value];
  // It makes its own sound, from the clip before's: no narration, audio file or reference media.
  if (infinite && $('audioMode').value !== 'none') { $('audioMode').value = 'none'; syncAudio(); }
  $('audioMode').disabled = infinite;
  syncH3Controls('video', !multishot && !infinite && !!workflowH3[$('videoWorkflow').value]);
  $('videoLlmBox').classList.toggle('hidden', direct);
  $('videoLocalModelBox').hidden = direct || $('llm').value !== 'local';
  $('videoLocalModel').disabled = $('videoLocalModelBox').hidden;
  $('videoPromptHint').textContent = direct ? (multishot ? 'Every shot gets it as you wrote it.' : 'Every clip gets it as you wrote it, each on its own seed.') : 'A sentence or two is enough.';
  const videoOptions = (workflowTakes[$('videoWorkflow').value] || {}).options || [];
  syncOptions('videoOptions', 'videoOptionsBox', videoOptions.filter(option => !LATENT_OPTIONS.includes(option.id)), $('videoWorkflow').value);
  syncVideoLatent(videoOptions);
  syncMediaInput();
  syncSize();
  syncAudio();
  const [low] = videoClips();
  const estimate = $('videoClipFixed').checked
    ? Math.min(Math.floor(+$('duration').max / low), Math.max(1, Math.floor(seconds / low + .5))) * low : seconds;
  $('durationText').textContent = $('duration').value && Number.isInteger(seconds) && seconds >= +$('duration').min && seconds <= +$('duration').max
    ? filmLengthEstimate(seconds, estimate) : '';
}
$('formVideo').addEventListener('change', () => { syncVideoForm(); saveVideoForm(); });
$('duration').addEventListener('input', syncVideoForm);
$('videoClipRange').addEventListener('input', e => { syncVideoClips(e.target); syncVideoForm(); saveVideoForm(); });
$('imageBoxes').addEventListener('change', e => showImage(e.target.closest('.image-box')));
$('imageBoxes').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('button');
  if (!button) return;
  const box = button.closest('.image-box');
  if (button.dataset.pick) { chooseFromOutput(box, 'video'); return; }
  if (!button.dataset.clear) return;
  removeImage(box);
  syncImageInput();
});
$('addImage').addEventListener('click', () => {
  imagesShown++;
  syncImageInput();
});
