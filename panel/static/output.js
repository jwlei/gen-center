// --- Videos ---
function esc(s) { return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
const CAN_UPLOAD = PANEL_CONFIG.can_upload;
const CAN_OPEN_FOLDERS = PANEL_CONFIG.can_open_folders;
const NO_KEYS = 'Set the YouTube keys in .env first (run scripts/authorize_youtube.py once).';
let busy = false;  // An upload is in progress or queued, or a run is uploading its own video: a new one waits.
let uploadingNow = new Set(), uploadQueued = new Set();  // Videos an upload has already claimed.

function slides() { return [...$('videos').querySelectorAll('.vid')]; }
function currentSlide() {
  const c = $('videos');
  let best = 0, bestDist = Infinity;
  slides().forEach((el, i) => {
    const dist = Math.abs(el.offsetLeft - c.scrollLeft - (c.clientWidth - el.clientWidth) / 2);
    if (dist < bestDist) { best = i; bestDist = dist; }
  });
  return best;
}
function goToSlide(i, smooth = true) {
  const el = slides()[i];
  if (!el) return;
  slides().forEach(s => s.querySelector('video').pause());
  const c = $('videos');
  c.scrollTo({ left: el.offsetLeft - (c.clientWidth - el.clientWidth) / 2, behavior: smooth ? 'smooth' : 'auto' });
}
function updateNav() {
  const n = slides().length;
  $('cnav').hidden = n < 2;
  const i = currentSlide();
  $('vidPos').textContent = `${i + 1} / ${n}`;
  $('prevVid').disabled = i === 0;
  $('nextVid').disabled = i >= n - 1;
}

function unclaimedVideos() {
  return lastVideos.output.filter(v => !uploadingNow.has(v.name) && !uploadQueued.has(v.name));
}

// --- Output: images and videos in one list, or either alone, or the collections; Shorts on its own ---
// Shorts' output is Shorts' (pipeline === 'shorts'); the others show what outputKind says, whichever side Generate is on.
const OUTPUT_KINDS = ['both', 'image', 'video'];
const OUTPUT_KIND_KEY = 'gen-center.outputKind';
let outputKind = 'both';
try { const kept = localStorage.getItem(OUTPUT_KIND_KEY); if (OUTPUT_KINDS.includes(kept)) outputKind = kept; } catch (e) {}
// The other view (NSFW): only what is tagged, and nothing tagged anywhere else. Never on Shorts.
let nsfwView = false;
function filtered(list) {
  return list.filter(item => nsfwView ? !!item.nsfw : !item.nsfw);
}
function showsImages() { return pipeline !== 'shorts' && (outputKind === 'both' || outputKind === 'image'); }
function showsFilms() { return pipeline !== 'shorts' && (outputKind === 'both' || outputKind === 'video'); }
function setOutputKind(kind) {
  if (!OUTPUT_KINDS.includes(kind)) return;
  outputKind = kind;
  try { localStorage.setItem(OUTPUT_KIND_KEY, kind); } catch (e) {}
  redrawFiltered();
}
function setNsfwView(on) {
  if (pipeline === 'shorts') on = false;
  if (nsfwView === on) return;
  nsfwView = on;
  redrawFiltered();
}
$('outputKinds').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('[data-kind]');
  if (button) setOutputKind(button.dataset.kind);
});
$('viewToggle').addEventListener('click', () => setNsfwView(!nsfwView));
function syncOutputLine() {
  if (pipeline === 'shorts') nsfwView = false;
  $('outputKinds').dataset.kind = outputKind;
  for (const button of $('outputKinds').querySelectorAll('[data-kind]')) {
    const on = button.dataset.kind === outputKind;
    button.classList.toggle('active', on);
    button.setAttribute('aria-selected', String(on));
  }
  placeKindsThumb();
  $('viewToggle').classList.toggle('on', nsfwView);
  $('viewToggle').setAttribute('aria-pressed', String(nsfwView));
  // A folder of its own only for Images or Videos (Shorts: its tab's).
  $('openFolder').hidden = !CAN_OPEN_FOLDERS || (pipeline !== 'shorts' && !['image', 'video'].includes(outputKind));
  $('jumpResults').textContent = 'Output';
}
// The lit pill under the kind shown: it slides there. Placed without sliding the first time it can be measured
// (the line is out of sight on Shorts and on a phone's other pages).
function placeKindsThumb() {
  const thumb = $('kindsThumb'), active = $('outputKinds').querySelector && $('outputKinds').querySelector('button.active');
  if (!thumb || !active || !active.offsetWidth) return;
  const first = !thumb.dataset.placed;
  if (first) thumb.classList.add('still');
  thumb.style.width = `${active.offsetWidth}px`;
  thumb.style.transform = `translateX(${active.offsetLeft}px)`;
  thumb.dataset.placed = '1';
  if (first) requestAnimationFrame(() => requestAnimationFrame(() => thumb.classList.remove('still')));
}
window.addEventListener('resize', () => { const thumb = $('kindsThumb'); if (thumb) { delete thumb.dataset.placed; placeKindsThumb(); } });
// A <select> as the switch Output uses. Its value and disabled still work as ever, set by code or by a tap: the switch follows.
function segmentSelect(select) {
  const options = [...select.options];
  select.insertAdjacentHTML('afterend', `<div class="switch segmented" role="radiogroup" style="--n:${options.length}"><span class="seg-thumb" aria-hidden="true"></span>`
    + options.map(o => `<button type="button" role="radio" data-value="${esc(o.value)}">${esc(o.textContent)}</button>`).join('') + '</div>');
  const box = select.nextElementSibling;
  const paint = () => {
    box.style.setProperty('--i', Math.max(0, options.findIndex(o => o.value === select.value)));
    box.classList.toggle('off', select.disabled);
    for (const button of box.querySelectorAll('button')) {
      const on = button.dataset.value === select.value;
      button.classList.toggle('active', on);
      button.setAttribute('aria-checked', String(on));
    }
  };
  box.addEventListener('click', e => {
    const button = e.target.closest('button');
    if (!button || select.disabled || button.dataset.value === select.value) return;
    select.value = button.dataset.value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  for (const name of ['value', 'disabled']) {
    const own = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, name);
    Object.defineProperty(select, name, { configurable: true, get() { return own.get.call(this); }, set(v) { own.set.call(this, v); paint(); } });
  }
  select.addEventListener('change', paint);
  if (select.form) select.form.addEventListener('reset', () => setTimeout(paint));
  paint();
}
for (const select of document.querySelectorAll('select[data-segmented]')) segmentSelect(select);
// All that the kind and the view decide: Output, its collections, and Finished (NSFW only in the NSFW view).
function redrawFiltered() {
  $('videos').dataset.key = $('imageSets').dataset.key = '';
  renderVideos();
  renderImageSets();
  renderCollections();
  if (lastFinished) renderFinished(...lastFinished);
}
// The films Output lists: Shorts' tab, or the made films. What moved to a collection is only in its collection.
function visibleFilms() { return filtered(lastVideos[pipeline === 'shorts' ? folder : 'video'] || []).filter(v => !v.collection); }
function renderVideos() {
  syncOutputLine();
  const videos = pipeline === 'shorts' ? visibleFilms() : [];
  $('countOutput').textContent = lastVideos.output.length;
  $('countUploaded').textContent = lastVideos.uploaded.length;
  $('uploadAll').hidden = folder !== 'output';
  if (!$('uploadAll').classList.contains('queue-request') && !$('uploadAll').classList.contains('queue-request-done')) {
    $('uploadAll').disabled = !CAN_UPLOAD || !unclaimedVideos().length;
    $('uploadAll').textContent = busy ? 'Queue upload all' : 'Upload all';
  }

  const key = pipeline + '|' + folder + '|' + !!choosingFor + '|' + JSON.stringify(videos.map(v => [v.name, v.mtime, v.topic, v.title, v.model, v.resolution, v.duration, v.size_mb, v.loras, v.h3_mode, v.h3_creativity, v.pills, v.nsfw]));
  // Keep players that already exist so a poll does not interrupt playback.
  if ($('videos').dataset.key !== key) {
    const was = (slides()[currentSlide()] || {}).dataset;
    $('videos').classList.add('as-list');
    // Shorts only: the made films are listed with the image sets, in the order they were made (renderImageSets).
    $('videos').innerHTML = pipeline !== 'shorts' ? ''
      : videos.length ? videos.map(v => filmHtml(v, folder)).join('')
      : `<div class="empty">${folder === 'uploaded' ? 'Nothing uploaded yet.' : 'No videos waiting. Press Generate to make one.'}</div>`;
    $('videos').dataset.key = key;
    requestAnimationFrame(() => markPillOverflow($('videos')));
    const back = was && slides().findIndex(s => s.dataset.name === was.name);
    if (back > 0) goToSlide(back, false);
  }
  // The upload icon says where it's at in its name, and pulses while it's claimed.
  for (const b of $('videos').querySelectorAll('[data-up]')) {
    if (b.classList.contains('queue-request') || b.classList.contains('queue-request-done')) continue;
    const now = uploadingNow.has(b.dataset.up), queued = uploadQueued.has(b.dataset.up);
    const label = now ? 'Uploading…' : queued ? 'Queued to upload' : busy ? 'Queue upload to YouTube' : 'Upload to YouTube';
    b.disabled = now || queued || !CAN_UPLOAD;
    b.title = CAN_UPLOAD ? label : NO_KEYS;
    b.setAttribute('aria-label', label);
    b.classList.toggle('working', now || queued);
  }
  updateNav();
}

async function queueRequest(button, request, doneText = 'Queued', pendingText = 'Adding…') {
  if (button.disabled) return null;
  const original = button.innerHTML;
  const label = button.getAttribute('aria-label');
  button.disabled = true;
  button.classList.add('queue-request');
  button.setAttribute('aria-busy', 'true');
  if (button.classList.contains('icon-btn') || button.classList.contains('run-item')) {
    button.textContent = '…';
  } else {
    button.textContent = pendingText;
  }
  try {
    const data = await request();
    if (!data.ok) {
      alert(data.error || 'Could not add it. Try again.');
      return null;
    }
    button.classList.remove('queue-request');
    button.classList.add('queue-request-done');
    button.setAttribute('aria-label', doneText);
    if (button.classList.contains('icon-btn') || button.classList.contains('run-item')) button.innerHTML = ICONS.check;
    else button.textContent = doneText;
    await new Promise(resolve => setTimeout(resolve, 800));
    return data;
  } catch (error) {
    alert('Could not reach the panel. Try again.');
    return null;
  } finally {
    button.disabled = false;
    button.classList.remove('queue-request', 'queue-request-done');
    button.removeAttribute('aria-busy');
    if (label === null) button.removeAttribute('aria-label'); else button.setAttribute('aria-label', label);
    button.innerHTML = original;
  }
}
async function startUpload(fields, button) {
  const body = new FormData();
  body.append('privacy', $('privacy').value);
  for (const [k, v] of Object.entries(fields)) body.append(k, v);
  const data = await queueRequest(button, async () => (await fetch('/publish', { method: 'POST', body })).json());
  if (data) poll();
}
function privacyNote() { return `as ${$('privacy').value} (change it under Publish)`; }

// The first tap turns the button red and asks; the second, within a few seconds, confirms.
const ARMED_MS = 3000;
function disarm(button) {
  clearTimeout(button._disarm);
  if (!button.classList.contains('armed')) return;
  button.classList.remove('armed');
  button.innerHTML = button.dataset.label;
  button.style.width = button.style.height = '';
}
function secondTap(button) {
  if (button.classList.contains('armed')) {
    disarm(button);
    return true;
  }
  button.dataset.label = button.innerHTML;
  // Held at its size, so "Confirm" or the tick doesn't move or grow past what's beside it.
  const box = button.getBoundingClientRect();
  button.style.width = `${box.width}px`;
  if (box.height) button.style.height = `${box.height}px`;
  button.classList.add('armed');
  if (button.classList.contains('icon-btn')) button.innerHTML = ICONS.check; else button.textContent = 'Confirm';
  button._disarm = setTimeout(() => disarm(button), ARMED_MS);
  return false;
}

// A film's buttons, in Videos, or among the image sets in the NSFW view.
const onFilmClick = async e => {
  const play = e.target.closest && e.target.closest('[data-play-film]');
  if (play) {
    e.preventDefault();
    openFilm(play.dataset.playFilm, play.dataset.filmFolder || folder);
    return;
  }
  const d = e.target.dataset || {};
  const filmFolder = d.filmFolder || folder;
  if (d.nsfwVideo) {
    await tagOutput('video', d.nsfwVideo, !nsfwView, e.target);
  } else if (d.downloadFilm) {
    downloadFile(`/download/${filmFolder}/${encodeURIComponent(d.downloadFilm)}`);
  } else if (d.againFilm) {
    await sameAgainFilm(d.againFilm);
  } else if (d.del) {
    if (!secondTap(e.target)) return;
    const body = await (await fetch(`/delete/${filmFolder}/` + encodeURIComponent(d.del), { method: 'POST' })).json();
    if (body.warning) alert(body.warning);
    if (!body.ok) alert(body.error || 'Could not delete it.');
    poll();
  } else if (d.shots) {
    openShots(d.shots);
  } else if (d.up) {
    let topic = '';
    if (!d.topic) {
      topic = (prompt(`No topic was recorded for ${d.up}. What is it about? Gemini writes the title and description from this.`) || '').trim();
      if (!topic) return;
    }
    const when = busy ? ' when the current upload is done' : '';
    if (!confirm(`Upload ${d.up} to YouTube ${privacyNote()}${when}?`)) return;
    startUpload(topic ? { video: d.up, topic } : { video: d.up }, e.target);
  }
};
$('videos').addEventListener('click', onFilmClick);
$('uploadAll').addEventListener('click', () => {
  const videos = unclaimedVideos();
  const missing = videos.filter(v => !v.topic).length;
  const skip = missing ? `\n\n${missing} without a recorded topic will be skipped; upload those on their own.` : '';
  const when = busy ? ' when the current upload is done' : '';
  if (!confirm(`Upload ${videos.length} video(s) to YouTube ${privacyNote()}${when}?${skip}`)) return;
  startUpload({}, $('uploadAll'));
});
$('openFolder').onclick = async () => {
  const data = await (await fetch(`/folders/${pipeline === 'shorts' ? folder : outputKind}/open`, { method: 'POST' })).json();
  if (!data.ok) alert(data.error || 'Could not open the folder.');
};
$('prevVid').onclick = () => goToSlide(currentSlide() - 1);
$('nextVid').onclick = () => goToSlide(currentSlide() + 1);
let navFrame = 0;
$('videos').addEventListener('scroll', () => {
  cancelAnimationFrame(navFrame);
  navFrame = requestAnimationFrame(updateNav);
});
window.addEventListener('resize', () => goToSlide(currentSlide(), false));

function setTab(f) {
  folder = f;
  $('tabOutput').classList.toggle('active', f === 'output');
  $('tabUploaded').classList.toggle('active', f === 'uploaded');
  $('videos').dataset.key = '';
  $('videos').scrollLeft = 0;
  renderVideos();
}
$('tabOutput').onclick = () => setTab('output');
$('tabUploaded').onclick = () => setTab('uploaded');
