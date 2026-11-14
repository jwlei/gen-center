function onGrid(value) { return Math.max(256, Math.round(value / SIZE_STEP) * SIZE_STEP); }
// As the pipeline works it out, so you see the size before you press Generate. mp: the megapixels asked for, or null for
// the image's own (within cap) or one megapixel.
function pickedSize(mp = null, cap = null) {
  const aspect = $('imageAspect').value;
  const [width, height] = sourceSize || [1, 1];
  const parts = aspect.split(':');
  const ratio = aspect === 'image' || !/^[\d.]+:[\d.]+$/.test(aspect) ? width / height : +parts[0] / +parts[1];
  const model = imageModel();
  const most = (cap || (model && model.most_megapixels) || MOST_MEGAPIXELS) * MEGAPIXEL;
  const area = mp == null ? (sourceSize ? Math.min(width * height, most) : Math.min(MEGAPIXEL, most)) : mp * MEGAPIXEL;
  return gridSides(Math.sqrt(area * ratio), Math.sqrt(area / ratio), most / MEGAPIXEL);
}
// Greys out the sizes and pixel counts a model doesn't make well. Returns what the hint should say about it.
function syncImageLimits() {
  const model = imageModel(), most = model && model.most_megapixels;
  startAtLeast(model);
  // Qwen edit works up to 1.6 MP, so there it's only an aspect ratio and a pixel count, not screens or an exact size.
  const plain = imageTakes().model === 'qwen_image_21_edit';
  const tooBig = (width, height) => !!most && width * height > most * MEGAPIXEL;
  for (const group of [...($('imageAspect').querySelectorAll ? $('imageAspect').querySelectorAll('optgroup') : [])]) group.hidden = plain && group.label !== 'Aspect ratio';
  for (const option of [...($('imageAspect').options || [])]) {
    const sides = /^(\d+)x(\d+)$/.exec(option.value);
    if (sides) option.disabled = plain;
    else if (option.value === 'custom') { option.disabled = plain; option.hidden = plain; }
  }
  for (const option of [...($('imageMegapixels').options || [])]) {
    if (option.value === '1.6') { option.disabled = option.hidden = !plain; continue; }
    if (option.value !== 'image') option.disabled = !!most && +option.value > most;
  }
  const picked = select => [...(select.options || [])].find(o => o.value === select.value);
  if (plain && picked($('imageAspect')) && picked($('imageAspect')).disabled) $('imageAspect').value = 'image';
  if (picked($('imageMegapixels')) && picked($('imageMegapixels')).disabled && $('imageMegapixels').value === '1.6') $('imageMegapixels').value = 'image';
  if (most && $('imageMegapixels').value !== 'image' && +$('imageMegapixels').value > most) $('imageMegapixels').value = String(most);
  return most ? ` ${model.label} makes images up to ${most} MP.` : '';
}
// On coming to a model, the size starts where it does best: its own default (MOSS Image 2 MP, MiniMax H3 Image 16), or, for
// one that does poorly small (MiniMax H3 Image, under 4 MP), at its least. It can still be stepped after. Only on the
// change, so it never fights the stepper. A screen or an exact size starts as itself, and is held to the cap as it's drawn.
let imageLeastModel;
let imageDefaulted = false;  // The stepper is where a model's default put it, not where it was stepped to
function startAtLeast(model) {
  const key = imageTakes().model || '';
  if (key === imageLeastModel) return;
  imageLeastModel = key;
  if (!model || imageUpscaleOn()) return;
  // The held size is stale once this moves the stepper, and mustn't be taken for one set from outside.
  const start = mp => { imageStep = mp; $('imageMegapixels').value = $('imageMegapixels').dataset.sent = 'image'; };
  const aspect = $('imageAspect').value, fixed = aspect === 'custom' || /^\d+x\d+$/.test(aspect);
  if (model.default_megapixels && !fixed) { start(Math.min(model.default_megapixels, model.most_megapixels || model.default_megapixels)); imageDefaulted = true; return; }
  if (imageDefaulted && !fixed) { start(null); imageDefaulted = false; }
  const least = model.least_megapixels;
  if (!least || imageResolution().mp >= least - 1e-9) return;
  start(least);
}
const MP_STEP = 0.1;
// Resolution, Upscale and the stepper as one block. The resolution is what the model makes (a screen exactly, an aspect
// ratio at the image's own pixel count or 1 MP); the stepper scales it, whatever was picked. With Upscale on, the
// stepper sets the size it ends at. A pixel count that would very likely run out of memory is held to the nearest below.
let imageStep = null;  // The megapixels the stepper set for the resolution, or null for it as picked
let imageMadeAt = null;  // With Upscale on: the megapixels it is made at, for Upscale off to drop back to
let imageOffMp = null;  // With Upscale off: the megapixels of the resolution, for Upscale on to start from
let imageUpscaleWas = 'Off';
let imageShown = null;  // The size it is made at, as last shown: Exact size starts from it
function imageUpscaleOn() {
  return !$('imageUpscaleBox').hidden && !$('imageUpscale').disabled && !!$('imageUpscale').value && $('imageUpscale').value !== 'Off';
}
function imageLimit() { return ($('imageUpscaleBox').limits || {})[$('imageUpscale').value] || {}; }
// On the grid, nearest; if that goes past the cap, rounded down, so it never does. Silently: it varies by a few pixels.
function gridSides(a, b, cap) {
  const near = [onGrid(a), onGrid(b)];
  if (cap && near[0] * near[1] > cap * MEGAPIXEL + 1e-6) return [a, b].map(side => Math.max(256, Math.floor(side / SIZE_STEP) * SIZE_STEP));
  return near;
}
function shapedSize(ratio, mp, cap = null) { return gridSides(Math.sqrt(mp * MEGAPIXEL * ratio), Math.sqrt(mp * MEGAPIXEL / ratio), cap); }
const tenthBelow = mp => Math.floor(mp * 10 + 1e-6) / 10;
function imageResolution() {
  const model = imageModel(), modelMost = (model && model.most_megapixels) || MOST_MEGAPIXELS;
  const on = imageUpscaleOn(), limit = imageLimit(), cap = on && limit.base ? Math.min(modelMost, limit.base) : modelMost;
  const aspect = $('imageAspect').value, typed = aspect === 'custom', screen = /^\d+x\d+$/.test(aspect);
  const exact = screen ? aspect.split('x').map(Number) : typed ? ((/^(\d+)x(\d+)$/i.exec($('imageSize').value.trim()) || []).slice(1).map(Number)) : [];
  const isExact = exact.length === 2 && exact.every(n => n > 0);
  if (on) return upscaledResolution(isExact ? exact : null, cap, limit, typed);
  const step = imageStep, least = model && model.least_megapixels;
  let sides = null, send = 'image', note = '';
  if (screen || typed) {
    if (isExact) {
      const mp = exact[0] * exact[1] / MEGAPIXEL;
      if (step != null) {
        const m = Math.min(step, cap);
        sides = shapedSize(exact[0] / exact[1], m, cap);
        send = m.toFixed(1);
        // A typed size, stepped: the box holds the new size, and goes as it is (as video's does).
        if (typed && document.activeElement !== $('imageSize')) {
          $('imageSize').value = sides.join('x');
          send = 'image';
          imageStep = null;
        }
      }
      else if (mp > cap + 1e-9 || (screen && least && mp < least - 1e-9)) {
        // Outside the limits: made at its shape within them. A preset says so, until the stepper takes over.
        const m = mp > cap + 1e-9 ? tenthBelow(cap) : least;
        sides = shapedSize(exact[0] / exact[1], m, cap);
        send = m.toFixed(1);
        if (screen) note = `Rescaled to ${m.toFixed(1)} MP`;
      } else sides = exact;
    }
  } else {
    const m = step != null ? Math.min(step, cap) : null;
    sides = pickedSize(m, cap);
    send = m == null ? 'image' : m.toFixed(1);
  }
  const mp = sides ? sides[0] * sides[1] / MEGAPIXEL : (step ?? 1);
  return { sides, send, note, on, mp, least: MP_STEP, top: tenthBelow(cap), end: null };
}
// With Upscale on, the stepper sets the size it ends at, and the size it's made at follows: a quarter of the pixels
// (twice as big each way), within what the upscale starts from on this card. A screen or exact size is where it ends
// unless the stepper says otherwise.
const UPSCALE_AREA = 4, UPSCALE_LEAST = 0.4, UPSCALE_USUAL = 4;
// How many times the pixels it ends with: SeedVR2's 2×, 3× or 4× each way, the others twice each way.
function imageUpscaleArea() {
  return $('imageUpscale').value === 'SeedVR2' ? (Number($('imageUpscaleFactor').value) || 2) ** 2 : UPSCALE_AREA;
}
// typed: the exact size box holds the size it is made at, and the end follows it (four times the pixels) until stepped.
function upscaledResolution(exact, cap, limit, typed = false) {
  const [w, h] = sourceSize || [1, 1], parts = $('imageAspect').value.split(':');
  const ratio = exact ? exact[0] / exact[1] : /^[\d.]+:[\d.]+$/.test($('imageAspect').value) ? +parts[0] / +parts[1] : w / h;
  let top = Math.min(limit.final || 16, cap * 16);
  if (limit.shorter) top = Math.min(top, limit.shorter ** 2 * Math.max(ratio, 1 / ratio) / MEGAPIXEL);
  top = tenthBelow(top);
  const exactMp = exact ? exact[0] * exact[1] / MEGAPIXEL : null;
  const area = imageUpscaleArea();
  const wanted = Number($('imageUpscaleMp').value) || (typed && exactMp ? exactMp * area : exactMp) || UPSCALE_USUAL;
  const mp = Math.min(top, Math.max(UPSCALE_LEAST, Math.round(wanted * 10) / 10));
  const note = wanted > top + 0.05 ? `Held to ${top.toFixed(1)} MP: past that, ${$('imageUpscale').value} would very likely run out of memory on this card.` : '';
  const base = Math.min(cap, Math.max(MP_STEP, mp / area));
  const sides = shapedSize(ratio, base, cap);
  const end = exact && !typed && Math.abs(mp - exactMp) < 0.05 ? exact : shapedSize(ratio, mp);
  // The box shows the size it is made at, as the stepper moves it; not while it's being typed in.
  if (typed && document.activeElement !== $('imageSize')) $('imageSize').value = sides.join('x');
  return { sides, send: base.toFixed(2), note, on: true, mp, least: UPSCALE_LEAST, top, end, base };
}
function syncMegapixels() {
  const r = imageResolution();
  $('imageMegapixels').value = r.send;
  $('imageMegapixels').dataset.sent = r.send;
  if (r.end) {
    $('imageUpscaleMp').value = r.mp.toFixed(1);
    $('imageUpscaleFinal').value = r.end.join('x');
    $('imageUpscaleScale').value = (r.end[0] / r.sides[0]).toFixed(3);
  }
  for (const id of ['imageUpscaleFinal', 'imageUpscaleScale', 'imageUpscaleMp']) $(id).disabled = !r.on;
  // Resolution: the size it is made at. Upscale: the size it ends at.
  $('imagePixelSize').textContent = r.sides ? r.sides.join('×') : '';
  showUpscaleEnd($('imageUpscaleSize'), r.end, !r.on && r.sides);
  if (r.on && r.sides) imageMadeAt = r.base;
  if (!r.on && r.sides) imageOffMp = r.sides[0] * r.sides[1] / MEGAPIXEL;
  if (r.sides) imageShown = r.sides;
  if (!$('imageMegapixelsValue').querySelector('input')) $('imageMegapixelsValue').innerHTML = `${r.mp.toFixed(1)}<span class="mp-unit">MP</span>`;
  $('imageMegapixelsValue').title = r.on ? 'The size it ends at; the size it is made at follows' : '';
  $('imageMegapixelsValue').setAttribute('aria-label', r.on ? 'Megapixels it ends at' : 'Megapixels');
  $('imageMegapixelsDown').disabled = r.mp <= r.least + 1e-9;
  $('imageMegapixelsUp').disabled = r.mp + MP_STEP > r.top + 1e-9;
  $('imageResNote').textContent = r.note;
  $('imageResNote').hidden = !r.note;
  return r;
}
function stepMegapixels(by) {
  if (imageUpscaleOn()) {
    $('imageUpscaleMp').value = (Math.round((Number($('imageUpscaleMp').value) + by) * 10) / 10).toFixed(1);
  } else {
    const r = imageResolution(), from = r.sides ? r.sides[0] * r.sides[1] / MEGAPIXEL : (imageStep ?? 1);
    imageDefaulted = false;
    imageStep = Math.min(r.top, Math.max(MP_STEP, Math.round((from + by) * 10) / 10));
  }
  syncImageSize();
  $('imageMegapixels').dispatchEvent(new Event('change', { bubbles: true }));
}
$('imageMegapixelsDown').addEventListener('click', () => stepMegapixels(-MP_STEP));
$('imageMegapixelsUp').addEventListener('click', () => stepMegapixels(MP_STEP));
// A tap on the number turns it into a box to type in, as Steps is: Enter or leaving it keeps what was typed (past what
// is allowed it goes to the nearest limit), Escape leaves it as it was. apply gets the number, or null for none.
function editMegapixels(field, apply) {
  if (field.querySelector('input')) return;
  const input = document.createElement('input');
  input.type = 'number'; input.step = '0.1'; input.min = '0.1'; input.inputMode = 'decimal';
  input.value = parseFloat(field.textContent) || '';
  input.setAttribute('aria-label', 'Megapixels');
  field.textContent = '';
  field.append(input);
  input.focus(); input.select();
  let done = false;
  const finish = keep => {
    if (done) return;
    done = true;
    const value = Number(input.value.replace(',', '.'));
    input.remove();
    apply(keep && input.value !== '' && Number.isFinite(value) && value > 0 ? value : null);
  };
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
}
for (const id of ['imageMegapixelsValue', 'videoMegapixelsValue']) {
  $(id).addEventListener('keydown', e => { if (e.target === $(id) && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); $(id).click(); } });
}
$('imageMegapixelsValue').addEventListener('click', () => {
  editMegapixels($('imageMegapixelsValue'), value => {
    if (value != null) {
      const r = imageResolution(), mp = Math.min(r.top, Math.max(r.least, Math.round(value * 10) / 10));
      if (imageUpscaleOn()) $('imageUpscaleMp').value = mp.toFixed(1);
      else { imageDefaulted = false; imageStep = mp; }
    }
    syncImageSize();
    $('imageMegapixels').dispatchEvent(new Event('change', { bubbles: true }));
  });
});
// A screen or an exact size starts as itself; an aspect ratio keeps the pixel count stepped to.
// Typed with Upscale on: the size typed is the size it's made at, so where it ends follows it again.
$('imageSize').addEventListener('input', () => { if (imageUpscaleOn()) $('imageUpscaleMp').value = ''; });
$('imageSize').addEventListener('blur', () => syncImageSize());
$('imageAspect').addEventListener('change', () => {
  // Exact size starts from the size it was being made at, so nothing jumps; with an upscale, where it ends stays.
  if ($('imageAspect').value === 'custom' && imageShown) { $('imageSize').value = imageShown.join('x'); imageStep = null; return; }
  if (/^\d+x\d+$/.test($('imageAspect').value)) { imageStep = null; $('imageUpscaleMp').value = ''; }
});
function syncImageSize() {
  const takes = imageTakes();
  const limit = syncImageLimits();
  // Set from outside (a preset, a set reopened): what it holds is the stepper's now.
  const held = $('imageMegapixels').value;
  if (held !== $('imageMegapixels').dataset.sent && !imageUpscaleOn()) imageStep = held === 'image' || !+held ? null : +held;
  const aspect = $('imageAspect').value, typed = aspect === 'custom';
  const region = ['areas', 'expand'].includes(imageMode());
  const sized = !!takes.size && !region;
  $('imageSizeBox').classList.toggle('hidden', !sized);
  $('imageSize').hidden = !typed;
  const upscale = !$('imageUpscaleBox').hidden;
  $('imageMegapixelsBox').classList.toggle('hidden', !sized && !imageUpscaleOn());
  $('imageResBlock').hidden = !sized && !upscale;
  if (!sized && !imageUpscaleOn()) { $('imagePixelSize').textContent = $('imageUpscaleSize').textContent = ''; $('imageResNote').hidden = true; return; }
  const r = syncMegapixels();
  drawAspect($('imageAspectBox'), ...(r.sides || [0, 0]));
}
// A small box in the shape chosen, beside the picker. Nothing to draw for a size still being typed.
function drawAspect(box, width, height) {
  box.classList.toggle('hidden', !(width > 0 && height > 0));
  if (!(width > 0 && height > 0)) return;
  const scale = 22 / Math.max(width, height);
  box.style.width = `${Math.max(6, Math.round(width * scale))}px`;
  box.style.height = `${Math.max(6, Math.round(height * scale))}px`;
}
