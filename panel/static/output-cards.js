// The sets made so far. Small pictures, because a set of big PNGs would crawl over a phone connection.
let imageSets = [];
// The LoRAs it was made with, on a line of their own under its details.
// One line, cut short with … when it doesn't fit; a tap shows the whole of it.
function lorasLine(loras) {
  if (!loras || !loras.length) return '';
  const text = `LoRA: ${loras.map(esc).join(', ')}`;
  return `<div class="meta loras" role="button" tabindex="0" title="${text}">${text}</div>`;
}
function h3Description(item) {
  if (!item.h3_mode || item.h3_mode === 'off') return '';
  const mode = { review: 'Before review', render: 'Before each clip' }[item.h3_mode] || item.h3_mode;
  const creativity = item.h3_creativity;
  return `OpenH3-IR: ${mode}${creativity ? ` · ${creativity.charAt(0).toUpperCase() + creativity.slice(1)}` : ''}`;
}
// What it was made with, as pills on one line (core/pills.py); those that tell it apart from what its prompt
// made besides come first, in its side's colour. A tap shows them all when they don't fit.
function pillsHtml(pills) {
  // The workflow first and always in colour; the others in colour when they tell it apart from its siblings.
  return (pills || []).map(p => `<span class="pill${p.kind === 'workflow' ? ' workflow' : ''}${p.comparison ? ' comparison' : ''}${p.diff ? ' diff' : ''}">${esc(p.text)}</span>`).join('');
}
function pillsLine(pills, side, lines = 2) {
  return pills && pills.length ? `<div class="pills ${side}" data-lines="${lines}" role="button" tabindex="0" title="Tap to show all">${pillsHtml(pills)}</div>` : '';
}
// Which lines of pills hold more than fits (two lines in Output, one in the preview): they say how many more, and a
// tap opens them.
function markPillOverflow(root) {
  if (!root || !root.querySelectorAll) return;
  for (const line of root.querySelectorAll('.pills')) fitPills(line);
}
// Fills its lines in order, but a pill too long for what is left steps aside (into the "+N") and the shorter ones
// after it take the room: a long pill second no longer leaves the first alone on its line. Measured once without the
// room the "+N" takes, then again with it if anything stepped aside.
function fitPills(line) {
  if (line.classList.contains('open')) return;
  const pills = [...line.children], lines = +(line.dataset.lines || 2);
  const pass = () => {
    for (const pill of pills) pill.classList.remove('spill');
    const tops = new Set();
    let hidden = 0;
    for (const pill of pills) {
      const top = pill.offsetTop;
      if (!tops.has(top) && tops.size >= lines) { pill.classList.add('spill'); hidden++; } else tops.add(top);
    }
    return hidden;
  };
  line.classList.remove('more');
  let hidden = pass();
  if (hidden) { line.classList.add('more'); hidden = pass(); }
  line.classList.toggle('more', hidden > 0);
  line.dataset.more = hidden ? `+${hidden}` : '';
}
document.addEventListener('click', e => {
  const line = e.target.closest && e.target.closest('.pills');
  if (!line) return;
  if (line.closest('.viewer-meta-details')) {
    if (line.classList.contains('more')) openPillsMenu(line);
    return;
  }
  if (!line.classList.contains('more') && !line.classList.contains('open')) return;
  line.classList.toggle('open');
  if (!line.classList.contains('open')) fitPills(line);
});
// The preview's pills, all of them, in a box growing over its buttons as Move's menu does.
function openPillsMenu(line) {
  const body = $('pillsMenuBody');
  body.className = `pills ${line.classList.contains('image') ? 'image' : 'video'} open`;
  body.innerHTML = line.innerHTML;
  for (const pill of body.querySelectorAll ? body.querySelectorAll('.spill') : []) pill.classList.remove('spill');
  const box = $('pillsMenu');
  box.classList.remove('closing');
  if (!box.open) box.showModal();
  placeOverPills(box, line);
}
// Grown up out of the pill line: as wide as the preview's bar, its bottom on the line's, over it; never off the top.
function placeOverPills(box, line) {
  const bar = document.querySelector('#imageViewer .viewer-bar').getBoundingClientRect(), at = line.getBoundingClientRect();
  Object.assign(box.style, { margin: '0', inset: 'auto', height: 'auto', minHeight: '0', left: `${bar.left}px`, width: `${bar.width}px` });
  box.style.top = `${Math.max(8, at.bottom + 4 - box.getBoundingClientRect().height)}px`;
}
function closePillsMenu() {
  const box = $('pillsMenu');
  if (!box.open || box.classList.contains('closing')) return;
  box.classList.add('closing');
  setTimeout(() => { box.close(); box.classList.remove('closing'); }, 150);
}
// A tap anywhere on it or around it closes it; Esc too.
$('pillsMenu').addEventListener('click', closePillsMenu);
$('pillsMenu').addEventListener('cancel', e => { e.preventDefault(); closePillsMenu(); });
// How a film's clips connect, in shorthand: the long names are Generate's "How clips connect".
const CONNECTIONS = { chain: 'Continuous take', image: 'Separate moments', director: 'H3 Motion Director',
  multishot: 'H3 Multishot', infinite: 'H3 Infinite continuation' };
function connectionDescription(item) {
  return item.connection ? `Clips: ${CONNECTIONS[item.connection] || item.connection}` : '';
}
function connectionLine(item) {
  const text = connectionDescription(item);
  return text ? `<div class="meta">${esc(text)}</div>` : '';
}
function upscaledLine(item) {
  return item.upscaled ? `<div class="meta">Upscaled: ${esc(item.upscaled)}</div>` : '';
}
function h3Line(item) {
  const text = h3Description(item);
  return text ? `<div class="meta">${esc(text)}</div>` : '';
}
document.addEventListener('click', e => {
  const line = e.target.closest && e.target.closest('.meta.loras');
  if (line) line.classList.toggle('open');
});
const ICON_SVG = path => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
const ICONS = {
  download: ICON_SVG('<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>'),
  prompts: ICON_SVG('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>'),
  trash: PANEL_CONFIG.trash_icon,
  check: ICON_SVG('<path d="m5 12 5 5 9-10"/>'),
  copy: ICON_SVG('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>'),
  save: ICON_SVG('<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4"/><path d="M8 20v-6h8v6"/>'),
  seed: ICON_SVG('<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>'),
  enhanced: ICON_SVG('<path d="M12 3l1.8 4.6L18 9.4l-4.2 1.8L12 16l-1.8-4.8L6 9.4l4.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>'),
  upload: ICON_SVG('<path d="M12 20V9"/><path d="m7 14 5-5 5 5"/><path d="M5 4h14"/>'),
  again: ICON_SVG('<path d="M4 12a8 8 0 0 1 13.7-5.7L20 8.5"/><path d="M20 4v4.5h-4.5"/><path d="M20 12a8 8 0 0 1-13.7 5.7L4 15.5"/><path d="M4 20v-4.5h4.5"/>'),
  play: ICON_SVG('<path d="M7 4.5v15l12-7.5z" fill="currentColor"/>'),
  // Into the queue: a list with one more being added.
  queue: ICON_SVG('<path d="M4 6h12M4 12h12M4 18h7"/><path d="M17 15v6M14 18h6"/>'),
  // To the top of the queue: an arrow up to a bar.
  top: ICON_SVG('<path d="M5 4h14"/><path d="M12 20V9"/><path d="m7 13 5-5 5 5"/>'),
  // Waits in Pending until it is started: a clock.
  later: ICON_SVG('<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>'),
  config: ICON_SVG('<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>'),
  category: ICON_SVG('<circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/>'),
  // Clearing text, not deleting a thing: the bin stays for delete.
  eraser: ICON_SVG('<path d="M7 20h13"/><path d="M4.6 15.4 14.5 5.5a2 2 0 0 1 2.8 0l2.2 2.2a2 2 0 0 1 0 2.8L11 19H7.4z"/><path d="m9 11 5 5"/>'),
  brief: ICON_SVG('<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13h7M9 17h5"/>'),
  upscale: ICON_SVG('<path d="M4 10V4h6M20 14v6h-6"/><path d="M4 4l6 6M20 20l-6-6"/>'),
  move: ICON_SVG('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M10 13h6M13.5 10.5 16 13l-2.5 2.5"/>'),
  plus: ICON_SVG('<path d="M12 5v14M5 12h14"/>'),
  arrange: ICON_SVG('<path d="M12 3v18M3 12h18"/><path d="m9 6 3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/>'),
  up: ICON_SVG('<path d="m6 15 6-6 6 6"/>'),
  down: ICON_SVG('<path d="m6 9 6 6 6-6"/>'),
  grid: ICON_SVG('<rect x="4" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.2"/>'),
  clips: ICON_SVG('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/><path d="m10 9 4 3-4 3z"/>'),
};
$('writeVideoPrompt').innerHTML = $('writeImagePrompt').innerHTML = ICONS.enhanced;
for (const [id, icon] of Object.entries({ viewerDownload: 'download', viewerDelete: 'trash', promptDetailYours: 'brief', promptEditorCopy: 'copy', promptEditorClear: 'eraser', chatClear: 'eraser', promptEditorEnhance: 'enhanced', promptEditorReset: 'again', viewerVariations: 'config', viewerUpscale: 'upscale',
  viewerEdit: 'prompts', viewerPrompts: 'enhanced', viewerClips: 'clips' })) $(id).innerHTML = ICONS[icon];
function outputSize(bytes) {
  if (bytes == null) return '';
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
function outputCount(set) {
  if (set.total <= 1) return '';
  return set.generating ? `${set.images.length} of ${set.total} images` : `${set.images.length} images`;
}
function nsfwButton(kind, id, tagged) {
  const label = tagged ? 'Remove private tag' : 'Mark as private';
  return `<button type="button" class="icon-btn nsfw-button" data-nsfw-${kind}="${esc(id)}" aria-label="${label}" title="${label} (tap twice)">${ICONS.category}</button>`;
}
async function tagOutput(kind, id, nsfw, button, endpoint = '/api/output/nsfw') {
  if (button.disabled || !secondTap(button)) return;
  button.disabled = true;
  try {
    const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, id, nsfw }) });
    const data = await response.json();
    if (!response.ok || !data.ok) { alert(data.error || 'Could not change the private tag.'); return; }
    await poll();
  } catch (error) {
    alert('Could not change the private tag. Check the connection and try again.');
  } finally {
    button.disabled = false;
  }
}
function workPrivacy(item, kind, id) {
  if (!item || !['image', 'video'].includes(item.pipeline)) return '';
  if (item.nsfw || item.private) return privateMode ? `<div class="work-privacy private-only"><span class="work-private-pill" role="img" aria-label="Private run" title="Private run">${$('privateToggle').innerHTML}</span></div>` : '';
  return `<div class="work-privacy"><button type="button" class="icon-btn nsfw-button work-private-tag" data-work-private-kind="${kind}" data-work-private-id="${esc(String(id))}" aria-label="Mark as private" title="Mark as private (tap twice)">${ICONS.category}</button></div>`;
}
document.addEventListener('click', async e => {
  const button = e.target.closest && e.target.closest('[data-work-private-kind]');
  if (!button || !button.dataset.workPrivateKind) return;
  e.preventDefault();
  e.stopPropagation();
  await tagOutput(button.dataset.workPrivateKind, button.dataset.workPrivateId, true, button, '/api/work/nsfw');
}, true);
function upscaledBadge(method) {
  return `<span class="upscaled-badge" role="img" aria-label="${esc(`Upscaled: ${method}`)}">${ICONS.upscale}</span>`;
}
function imageSetHtml(set) {
  const id = encodeURIComponent(set.id);
  const picture = (p, extra = '') => `<a href="/image-runs/${id}/files/${p.position}?v=${p.version}" data-view-set="${esc(set.id)}" data-view-position="${p.position}" title="${esc(p.title)}"${extra}><img loading="lazy" alt="${esc(p.title)}" src="/image-runs/${id}/thumbnails/${p.position}?v=${p.version}">${p.upscaled ? upscaledBadge(p.upscaled) : ''}`;
  // No download here: an image is downloaded from the preview.
  const actions = `<div class="image-set-actions">`
    + `<button type="button" class="icon-btn" data-again-set="${esc(set.id)}" title="The same again: its settings in Generate, to change first" aria-label="The same again">${ICONS.config}</button>`
    + `<button type="button" class="icon-btn" data-shots="${esc(set.id)}" title="Prompts" aria-label="Prompts">${ICONS.enhanced}</button>`
    + `<button type="button" class="icon-btn del" data-delete-set="${esc(set.id)}" title="Delete" aria-label="Delete">${ICONS.trash}</button></div>`;
  // Every set alike: its cover (with how many), and beside it its pills, up to three lines, above its icons. The cover
  // opens the one picture, or all of them in the grid.
  const many = set.images.length > 1;
  const cover = many ? `<a href="#" class="album-cover" data-grid-set="${esc(set.id)}" title="All of them, small: tap one to open it"><img loading="lazy" alt="${esc(set.images[0].title)}" src="/image-runs/${id}/thumbnails/${set.images[0].position}?v=${set.images[0].version}">${set.images[0].upscaled ? upscaledBadge(set.images[0].upscaled) : ''}`
    : set.images.length ? picture(set.images[0], ' class="album-cover"') : '';
  const row = `
    <div class="image-set-row album">
      ${cover ? `${cover}${!set.images[0].upscaled && set.images.some(p => p.upscaled) ? `<span class="upscaled-badge" role="img" aria-label="Some of this set are upscaled">${ICONS.upscale}</span>` : ''}${many ? `<span class="album-count">${set.images.length}</span>` : ''}</a>` : ''}
      <div class="album-side">
        ${set.pills ? pillsLine(set.pills, 'image', 3) : ''}
        ${actions}
      </div>
    </div>`;
  return `
  <div class="image-set">
    <div class="image-set-heading"><h3${set.queued || set.generating ? ' class="wip" title="Still in the queue: more of it is being made, or waits to be"' : ''}>${esc(set.label)}</h3>${nsfwButton('image', set.id, !!set.nsfw)}</div>
    <div class="meta">${[madeOn(madeAt(set.id, set.mtime)), !set.pills && set.model && esc(set.model), set.resolutions?.length && esc(set.resolutions.join(', ')), outputSize(set.size_bytes), outputCount(set)].filter(Boolean).join(' · ')}</div>${set.pills ? '' : `${lorasLine(set.loras)}${h3Line(set)}${upscaledLine(set)}`}
    ${row}
  </div>`;
}
// When a set or film was made: its run's start, in its id (image_20261108_043935, run_20261108_035819). A file's own
// time moves when it is made again, as a film stitched anew, and would list it among the newest.
// An RTX upscale has its original's run, but is made when it is: among the newest, not back where the original is.
const UPSCALED_FILM = /_upscaled(?:_\d+)?\.mp4$/;  // As run_state.UPSCALED
const filmMadeAt = v => UPSCALED_FILM.test(v.name) ? v.mtime : madeAt(v.run || v.name, v.mtime);
function madeAt(id, mtime) {
  const m = /(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/.exec(id || '');
  return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime() / 1000 : mtime || 0;
}
// The time it was made, first on its details' line: "04:39"; from the next day on, with the day before it ("8 Nov 04:39",
// and the year when it isn't this one).
function madeOn(seconds) {
  if (!seconds) return '';
  const day = new Date(seconds * 1000), now = new Date(), months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const time = clock24(day);
  if (day.toDateString() === now.toDateString()) return time;
  return `${day.getDate()} ${months[day.getMonth()]}${day.getFullYear() !== now.getFullYear() ? ` ${day.getFullYear()}` : ''} ${time}`;
}
function renderImageSets() {
  if (gridDrag && gridDrag.grid === $('imageSets')) return;
  const sets = showsImages() ? filtered(imageSets) : [];
  const films = showsFilms() ? visibleFilms() : [];
  const key = pipeline + outputKind + nsfwView + JSON.stringify(SETTINGS.output_order || []) + JSON.stringify(sets.map(set => [set.id, set.label, set.total, set.images, set.model, set.loras, set.resolutions, set.size_bytes, set.generating, set.queued, set.llm, set.h3_mode, set.h3_creativity, set.nsfw, set.mtime, set.pills]))
    + JSON.stringify(films.map(v => [v.name, v.mtime, v.topic, v.title, v.model, v.resolution, v.duration, v.size_mb, v.loras, v.h3_mode, v.h3_creativity, v.run]));
  // Only when it changed, so a poll doesn't reload the pictures.
  if ($('imageSets').dataset.key === key) return;
  $('imageSets').dataset.key = key;
  const items = outputItems();
  $('outputArrange').hidden = items.length < 2;
  if (items.length < 2) { outputArranging = false; outputSelected = null; }
  if (!items.some(item => outputKey(item) === outputSelected)) outputSelected = null;
  const none = { both: 'Nothing yet. Press Generate to make something.', image: 'No images yet. Press Generate to make some.', video: 'No videos yet. Press Generate to make one.' };
  // One deleted: what came after it moves up into its place, rather than the list jumping.
  flipList($('imageSets'), '[data-output-key]', el => el.dataset.outputKey, () => {
    $('imageSets').innerHTML = items.length ? items.map((item, index) => `<div class="output-batch" data-output-key="${esc(outputKey(item))}" data-grid-index="${index}" tabindex="0" aria-label="${esc(item.set ? item.set.label : item.film.title || item.film.name)}">${item.set ? imageSetHtml(item.set) : filmHtml(item.film, 'video')}</div>`).join('')
      : pipeline === 'shorts' ? '' : `<div class="empty">${nsfwView ? 'Nothing here.' : none[outputKind]}</div>`;
  });
  requestAnimationFrame(() => markPillOverflow($('imageSets')));
  showOutputArranging();
  if (typeof glowViewedBatch === 'function') glowViewedBatch();
}
// A narrower or wider page fits more or fewer pills on a line.
window.addEventListener('resize', () => { for (const id of ['videos', 'imageSets', 'viewerMetaDetails']) markPillOverflow($(id)); });
