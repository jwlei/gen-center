// --- Collections: your own batches, of images and films moved there one at a time (panel/collections.py) ---
let allImageSets = [], collections = [], viewerCollection = null;
// A set by its id, with all its images: those in a collection too.
function findSet(id) { return allImageSets.find(s => s.id === id) || imageSets.find(s => s.id === id); }
// A collection's two albums, in the order things came: its images (each as its set has it) and its films.
function collectionAlbums(id) {
  const collection = collections.find(c => c.id === id), images = [], films = [];
  for (const item of collection ? collection.items : []) {
    if (item.kind === 'image') {
      const set = allImageSets.find(s => s.id === item.set), picture = set && set.images.find(p => p.file === item.file);
      if (picture) images.push({ ...picture, set: set.id });
    } else {
      const film = (lastVideos.video || []).find(v => v.name === item.name);
      if (film) films.push(film);
    }
  }
  return { images, films };
}
// The one before or after this in its collection's album, as a function that opens it; null at either end.
// The one by steps from items[at] in the viewer, round in a loop: on from the last is the first, back from the first
// the last. null when there is no other (one alone, or the one shown not found).
function loopNeighbour(items, at, by) {
  if (at < 0 || items.length < 2) return null;
  return items[((at + by) % items.length + items.length) % items.length];
}
function collectionNeighbour(by) {
  const albums = collectionAlbums(viewerCollection);
  if (viewing.film) {
    const next = loopNeighbour(albums.films, albums.films.findIndex(v => v.name === viewing.name), by);
    return next ? () => openFilm(next.name, 'video') : null;
  }
  const next = loopNeighbour(albums.images, albums.images.findIndex(p => p.set === viewing.id && p.position === viewing.position), by);
  return next ? () => openViewer(next.set, next.position) : null;
}
// Always above the list, off Shorts: one with anything NSFW in it only in the NSFW view, which shows only those.
function shownCollections() {
  if (pipeline === 'shorts') return [];
  return collections.filter(c => c.items.length && nsfwView === !!c.nsfw);
}
const imageThumbSrc = p => `/image-runs/${encodeURIComponent(p.set)}/thumbnails/${p.position}?v=${p.version}`;
const filmPosterSrc = v => (v.run ? `/runs/${encodeURIComponent(v.run)}/image` : `/posters/video/${encodeURIComponent(v.name)}`);
// What a collection is shown by: the picture chosen for it if it is still among its items, else its first image,
// else its first film. { image } or { film }.
function collectionCover(c) {
  const albums = collectionAlbums(c.id), chosen = c.cover;
  if (chosen && chosen.kind === 'image') {
    const image = albums.images.find(p => p.set === chosen.set && p.file === chosen.file);
    if (image) return { image };
  } else if (chosen && chosen.kind === 'film') {
    const film = albums.films.find(v => v.name === chosen.name);
    if (film) return { film };
  }
  return albums.images[0] ? { image: albums.images[0] } : albums.films[0] ? { film: albums.films[0] } : {};
}
// A tile: its picture (with how many are in it), and its name small beneath. One item opens itself; more open the grid.
function collectionHtml(c, number = 0) {
  const albums = collectionAlbums(c.id), id = esc(c.id), total = albums.images.length + albums.films.length;
  const { image, film } = collectionCover(c), src = image ? imageThumbSrc(image) : film ? filmPosterSrc(film) : '';
  const only = albums.images[0], onlyFilm = albums.films[0];
  const opens = total > 1 ? `data-grid-collection="${id}" title="${esc(c.name)}: all of them, small"`
    : `data-open-collection="${id}" title="${esc(c.name)}"${only ? ` data-col-set="${esc(only.set)}" data-col-position="${only.position}"` : onlyFilm ? ` data-col-film="${esc(onlyFilm.name)}"` : ''}`;
  return `<div class="collection-tile" data-collection="${id}" data-grid-index="${number}">
    <button type="button" class="tile-cover" ${opens}>${src ? `<img loading="lazy" alt="" src="${esc(src)}">` : ''}${total > 1 ? `<span class="album-count">${total}</span>` : ''}</button>
    <button type="button" class="tile-edit" data-edit-collection="${id}" title="Edit" aria-label="Edit ${esc(c.name)}">${ICONS.prompts}</button>
    <span class="tile-name">${esc(c.name)}</span>
  </div>`;
}
let collectionsArranging = false, collectionSelected = null;
function renderCollections() {
  const shown = shownCollections(), box = $('collections');
  const key = JSON.stringify([nsfwView, pipeline === 'shorts', shown.map(c => [c.id, c.name, c.items, c.cover, collectionAlbums(c.id).images.map(p => p.version)])]);
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  if (shown.length < 2) { collectionsArranging = false; collectionSelected = null; }
  if (!shown.some(c => c.id === collectionSelected)) collectionSelected = null;
  // Arranging is for two or more, so its icon has a thin line of its own then.
  box.innerHTML = (shown.length > 1 ? `<div class="collections-head"><span>Collections</span><button type="button" class="collections-arrange" data-arrange-collections="1" aria-pressed="false" title="Arrange: tap one, then drag it where it goes" aria-label="Arrange">${ICONS.arrange}</button></div>` : '')
    + `<div class="collection-tiles">${shown.map(collectionHtml).join('')}</div>`;
  // Shown or hidden as you left them (shown to begin with); the icon only when there are some.
  $('collectionsToggle').hidden = !shown.length;
  showCollectionArranging();
  showCollections(shown.length > 0 && collectionsOpen(), false);
}
function showCollectionArranging() {
  const box = $('collections');
  box.classList.toggle('arranging', collectionsArranging);
  const button = box.querySelector && box.querySelector('[data-arrange-collections]');
  if (button) {
    button.classList.toggle('on', collectionsArranging);
    button.setAttribute('aria-pressed', String(collectionsArranging));
  }
  if (box.querySelectorAll) for (const tile of box.querySelectorAll('.collection-tile')) tile.classList.toggle('selected', collectionsArranging && tile.dataset.collection === collectionSelected);
}
const COLLECTIONS_OPEN_KEY = 'gen-center.collectionsShown';
function collectionsOpen() {
  try { return localStorage.getItem(COLLECTIONS_OPEN_KEY) !== '0'; } catch (e) { return true; }
}
// Shows or hides the box, its height easing as the headings' folds do (foldDetails).
function showCollections(open, animate = true) {
  const box = $('collections');
  $('collectionsToggle').classList.toggle('on', open);
  $('collectionsToggle').setAttribute('aria-expanded', String(open));
  if (box._fold) { box._fold.cancel(); box._fold = null; }
  if (!animate || box.hidden === !open || !box.animate || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    box.hidden = !open;
    return;
  }
  box.hidden = false;
  const full = box.getBoundingClientRect().height;
  box.style.overflow = 'hidden';
  const fold = box._fold = box.animate({ height: open ? ['0px', `${full}px`] : [`${full}px`, '0px'], opacity: open ? [0, 1] : [1, 0] },
    { duration: 250, easing: 'ease' });
  fold.onfinish = () => {
    if (box._fold !== fold) return;
    box._fold = null;
    box.style.overflow = '';
    box.hidden = !open;
  };
}
$('collectionsToggle').addEventListener('click', () => {
  const open = $('collections').hidden;
  try { localStorage.setItem(COLLECTIONS_OPEN_KEY, open ? '1' : '0'); } catch (e) {}
  showCollections(open);
});
$('collections').addEventListener('click', e => {
  const target = e.target.closest ? e.target.closest('[data-open-collection], [data-grid-collection], [data-edit-collection], [data-arrange-collections], .collection-tile') : null;
  if (!target) return;
  const d = target.dataset;
  e.preventDefault();
  if (d.arrangeCollections) {
    collectionsArranging = !collectionsArranging;
    collectionSelected = null;
    showCollectionArranging();
    return;
  }
  // Arranging: a tap picks the tile to drag (or lets it go); nothing opens.
  if (collectionsArranging) {
    const tile = target.closest('.collection-tile');
    if (tile && !gridDragged) collectionSelected = collectionSelected === tile.dataset.collection ? null : tile.dataset.collection;
    showCollectionArranging();
    return;
  }
  if (d.editCollection) openCollectionEdit(d.editCollection);
  else if (d.openCollection) {
    viewerCollection = d.openCollection;
    if (d.colFilm) openFilm(d.colFilm, 'video'); else openViewer(d.colSet, +d.colPosition);
  } else if (d.gridCollection) {
    openThumbGrid({ collection: d.gridCollection });
  }
});
// The shown collections in this order, taking their places among all (those not shown stay in their own): drawn at
// once, then kept on the server (panel/collections.py), whose order every device follows.
async function placeCollections(shown) {
  const byId = Object.fromEntries(collections.map(c => [c.id, c]));
  const slots = collections.map((c, number) => (shown.includes(c.id) ? number : -1)).filter(number => number >= 0);
  slots.forEach((slot, number) => { collections[slot] = byId[shown[number]]; });
  renderCollections();
  if (await collectionRequest('/api/collections/order', { ids: shown })) poll();
}
const saveCollectionOrder = grid => placeCollections([...grid.children].map(tile => tile.dataset.collection));
// Dragged as the thumbnail grid's are: the tile picked first (the selected one), then held and moved.
$('collections').addEventListener('pointerdown', e => {
  if (!collectionsArranging || e.button > 0) return;
  const cell = e.target.closest && e.target.closest('.collection-tile');
  if (!cell || cell.dataset.collection !== collectionSelected) return;
  e.preventDefault();
  startGridDrag(e, cell, { host: document.body, owner: $('collections'), save: saveCollectionOrder,
    scroller: document.scrollingElement || document.documentElement });
});
$('collections').addEventListener('pointermove', moveGridDrag);
$('collections').addEventListener('pointerup', dropGrid);
$('collections').addEventListener('pointercancel', dropGrid);
// --- Editing a collection: its name, the picture it is shown by (one of its own, or the first), or deleting it ---
let collectionEditing = null;
function collectionPickerItems(id) {
  const albums = collectionAlbums(id);
  return [...albums.images.map(p => ({ ref: { kind: 'image', run: p.set, file: p.file }, same: c => c.kind === 'image' && c.set === p.set && c.file === p.file, src: imageThumbSrc(p), label: p.title })),
    ...albums.films.map(v => ({ ref: { kind: 'film', name: v.name }, same: c => c.kind === 'film' && c.name === v.name, src: filmPosterSrc(v), label: v.title || v.name }))];
}
function showCollectionPick() {
  for (const button of $('collectionEditPicker').querySelectorAll('button')) button.classList.toggle('current', button.dataset.pick === String(collectionEditing.pick));
}
function openCollectionEdit(id) {
  const collection = collections.find(c => c.id === id);
  if (!collection) return;
  const items = collectionPickerItems(id), chosen = collection.cover ? items.findIndex(item => item.same(collection.cover)) : -1;
  collectionEditing = { id, items, pick: chosen < 0 ? 'auto' : chosen, was: chosen < 0 ? 'auto' : chosen };
  $('collectionEditName').value = collection.name;
  $('collectionEditPicker').innerHTML = `<button type="button" class="auto" data-pick="auto" title="The first image">Auto</button>`
    + items.map((item, i) => `<button type="button" data-pick="${i}" title="${esc(item.label || '')}" aria-label="${esc(item.label || 'Use as the picture')}"><img loading="lazy" decoding="async" alt="" src="${esc(item.src)}"></button>`).join('');
  showCollectionPick();
  const del = $('collectionEditDelete');
  if (del.classList.contains('armed')) disarm(del);
  $('collectionEdit').showModal();
}
$('collectionEditPicker').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('[data-pick]');
  if (!button || !collectionEditing) return;
  collectionEditing.pick = button.dataset.pick === 'auto' ? 'auto' : +button.dataset.pick;
  showCollectionPick();
});
$('collectionEditSave').addEventListener('click', async () => {
  const edit = collectionEditing, collection = edit && collections.find(c => c.id === edit.id);
  if (!collection) { $('collectionEdit').close(); return; }
  const name = $('collectionEditName').value.trim(), id = encodeURIComponent(collection.id);
  if (name && name !== collection.name && !await collectionRequest(`/api/collections/${id}/rename`, { name })) return;
  if (edit.pick !== edit.was && !await collectionRequest(`/api/collections/${id}/cover`, { item: edit.pick === 'auto' ? null : edit.items[edit.pick].ref })) return;
  $('collectionEdit').close();
  poll();
});
$('collectionEditDelete').addEventListener('click', async e => {
  const button = e.currentTarget, edit = collectionEditing;
  if (!edit || !secondTap(button)) return;
  button.disabled = true;
  const body = await collectionRequest(`/api/collections/${encodeURIComponent(edit.id)}/delete`, {});
  button.disabled = false;
  if (!body) return;
  $('collectionEdit').close();
  poll();
});
$('collectionEditCancel').addEventListener('click', () => $('collectionEdit').close());
$('collectionEdit').addEventListener('click', e => { if (e.target === $('collectionEdit')) $('collectionEdit').close(); });
async function collectionRequest(url, payload) {
  try {
    const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const body = await response.json();
    if (!response.ok || !body.ok) { alert(body.error || 'That could not be done.'); return null; }
    return body;
  } catch (error) {
    alert('Could not reach the panel. Try again.');
    return null;
  }
}
// --- Move: the item open in the preview, to a collection (one already there, or a new one) ---
function viewedItem() {
  if (!viewing) return null;
  if (viewing.film) return viewing.folder === 'video' ? { kind: 'film', name: viewing.name } : null;
  const set = findSet(viewing.id), picture = set && set.images.find(p => p.position === viewing.position);
  return picture ? { kind: 'image', run: set.id, file: picture.file } : null;
}
function openMoveSheet() {
  const item = viewedItem();
  if (!item) return;
  const here = viewerCollection;
  // Those with NSFW in them only under the NSFW filter. In Private mode only those: what is made then is NSFW, so it
  // goes with its kind.
  const others = collections.filter(c => c.id !== here
    && (!c.nsfw || nsfwView) && (!privateMode || c.nsfw));
  $('moveList').innerHTML = `<button type="button" class="move-new-pick" data-move-new="1">${ICONS.plus}New</button>`
    + others.map(c => `<button type="button" data-move-to="${esc(c.id)}"${c.nsfw ? ' class="nsfw" title="Contains private items"' : ''}>${esc(c.name)}</button>`).join('');
  $('moveNewName').value = '';
  $('moveNewRow').hidden = true;
  $('moveError').hidden = true;
  const box = $('moveSheet');
  box.classList.remove('closing');
  box.showModal();
  placeOverViewerButtons(box);
}
// Closes as Upscale's menu does: a short fade down before it goes.
function closeMoveMenu(then) {
  const box = $('moveSheet');
  if (!box.open || box.classList.contains('closing')) return;
  box.classList.add('closing');
  setTimeout(() => { box.close(); box.classList.remove('closing'); if (then) then(); }, 150);
}
async function moveViewed(target, button = null) {
  const item = viewedItem();
  if (!item || $('moveSheet').classList.contains('moving')) return;
  // The one tapped lights up, the others dim, while it moves; a check on it once it has, then the menu goes.
  $('moveSheet').classList.add('moving');
  if (button) button.classList.add('picked');
  // Where the preview goes once it has moved: the next there, or the one before, or closed if it was the last.
  const next = viewerCollection ? collectionNeighbour(1) || collectionNeighbour(-1) : viewerNeighbour(1) || viewerNeighbour(-1);
  $('moveError').hidden = true;
  let body;
  try {
    const response = await fetch('/api/collections/move', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...item, ...target }) });
    body = await response.json();
    if (!response.ok || !body.ok) throw new Error(body.error || 'It could not be moved.');
  } catch (error) {
    $('moveError').textContent = error.message === 'Failed to fetch' ? 'Could not reach the panel. Try again.' : error.message;
    $('moveError').hidden = false;
    $('moveSheet').classList.remove('moving');
    if (button) button.classList.remove('picked');
    return;
  }
  // Moved: its border flashes once, then the menu goes.
  if (button) button.classList.add('moved');
  await new Promise(resolve => setTimeout(resolve, 380));
  $('moveSheet').classList.remove('moving');
  closeMoveMenu();
  await poll();
  if (next) next(); else closeViewer();
}
$('moveList').addEventListener('click', e => {
  if (e.target.closest && e.target.closest('[data-move-new]')) {
    // + New: its name, right there in the menu.
    $('moveNewRow').hidden = false;
    $('moveNewName').focus();
    placeOverViewerButtons($('moveSheet'));
    return;
  }
  const pick = e.target.closest && e.target.closest('[data-move-to]');
  if (pick) moveViewed({ to: pick.dataset.moveTo }, pick);
});
$('moveNewGo').addEventListener('click', () => {
  const name = $('moveNewName').value.trim();
  if (!name) { $('moveNewName').focus(); return; }
  moveViewed({ new: name });
});
$('moveNewName').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); $('moveNewGo').click(); } });
// A tap outside it, on the preview, closes it.
$('moveSheet').addEventListener('click', e => {
  const r = e.currentTarget.getBoundingClientRect();
  if (e.target === e.currentTarget && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) closeMoveMenu();
});
$('moveSheet').addEventListener('cancel', e => { e.preventDefault(); closeMoveMenu(); });
$('viewerMove').innerHTML = ICONS.move;
$('viewerMove').addEventListener('click', openMoveSheet);
// The one before or after this outside a collection (its set's images, or the films), as a function that opens it.
function viewerNeighbour(by) {
  if (viewing.film) {
    const films = visibleFilms(), next = films[films.findIndex(v => v.name === viewing.name) + by];
    return next ? () => openFilm(next.name, viewing.folder) : null;
  }
  const set = imageSets.find(s => s.id === viewing.id), images = set ? set.images : [];
  const next = images[images.findIndex(p => p.position === viewing.position) + by];
  return next ? () => openViewer(viewing.id, next.position) : null;
}
// --- The thumbnail grid: all of a set, or the films, small; a tap opens the preview at that one ---
let thumbGridItems = [];
// what: { set: id } for a set's images, or { films: folder } for the films the preview swipes through.
let thumbGridWhat = null, thumbGridArranging = false, thumbGridSelected = null;
function openThumbGrid(what, keepArranging = false) {
  thumbGridWhat = what;
  if (!keepArranging) thumbGridArranging = false;
  thumbGridSelected = null;
  let title = '', sections = null;
  if (what.collection) {
    const collection = collections.find(c => c.id === what.collection);
    if (!collection) return;
    const albums = collectionAlbums(collection.id);
    title = collection.name;
    const images = albums.images.map(p => ({ ref: { kind: 'image', run: p.set, file: p.file }, src: `/image-runs/${encodeURIComponent(p.set)}/thumbnails/${p.position}?v=${p.version}`, label: p.title, upscaled: p.upscaled,
      current: !!viewing && !viewing.film && viewing.id === p.set && viewing.position === p.position,
      open: () => { viewerCollection = collection.id; openViewer(p.set, p.position); } }));
    const films = albums.films.map(v => ({ ref: { kind: 'film', name: v.name }, src: v.run ? `/runs/${encodeURIComponent(v.run)}/image` : `/posters/video/${encodeURIComponent(v.name)}`, label: v.title || v.name,
      upscaled: v.upscaled, current: !!viewing && viewing.film && viewing.name === v.name,
      open: () => { viewerCollection = collection.id; openFilm(v.name, 'video'); } }));
    thumbGridItems = [...images, ...films];
    sections = [['Images', 0, images.length], ['Video', images.length, thumbGridItems.length]].filter(([, from, to]) => to > from);
  } else if (what.set) {
    const set = imageSets.find(s => s.id === what.set);
    if (!set) return;
    title = set.label;
    const id = encodeURIComponent(set.id);
    thumbGridItems = set.images.map(p => ({ ref: p.file, src: `/image-runs/${id}/thumbnails/${p.position}?v=${p.version}`, label: p.title, upscaled: p.upscaled,
      current: !!viewing && !viewing.film && viewing.id === set.id && viewing.position === p.position, open: () => openViewer(set.id, p.position) }));
  } else {
    const folder = what.films;
    title = 'Video';
    thumbGridItems = visibleFilms().map(v => {
      const url = encodeURIComponent(v.name);
      return { src: v.run && folder === 'video' ? `/runs/${encodeURIComponent(v.run)}/image` : `/posters/${folder}/${url}`, label: v.title || v.topic || v.name,
        upscaled: v.upscaled, current: !!viewing && viewing.film && viewing.name === v.name, open: () => openFilm(v.name, folder) };
    });
  }
  $('thumbGridTitle').textContent = `${title} (${thumbGridItems.length})`;
  const thumb = (item, i) => `<button type="button" data-grid-index="${i}" class="${item.current ? 'current' : ''}" title="${esc(item.label || '')}" aria-label="${esc(item.label || 'Open')}">`
    + `<img loading="lazy" decoding="async" alt="" src="${esc(item.src)}">${item.upscaled ? upscaledBadge(item.upscaled) : ''}</button>`;
  // A collection's two albums each under their heading; else one grid.
  $('thumbGridBody').innerHTML = (sections || [[null, 0, thumbGridItems.length]]).map(([heading, from, to]) =>
    `${heading ? `<div class="thumb-grid-section">${heading} (${to - from})</div>` : ''}<div class="thumb-grid">${thumbGridItems.slice(from, to).map((item, k) => thumb(item, from + k)).join('')}</div>`).join('');
  // Films in Video are in the order they were made: only a set's or a collection's own order is kept.
  $('thumbGridArrange').hidden = !!what.films;
  showArranging();
  if (!$('thumbGrid').open) $('thumbGrid').showModal();
}
function showArranging() {
  $('thumbGrid').classList.toggle('arranging', thumbGridArranging);
  $('thumbGridArrange').classList.toggle('on', thumbGridArranging);
  $('thumbGridArrange').setAttribute('aria-pressed', String(thumbGridArranging));
  for (const button of $('thumbGridBody').querySelectorAll('[data-grid-index]')) button.classList.toggle('selected', thumbGridArranging && button.dataset.gridIndex === thumbGridSelected);
}
$('thumbGridArrange').innerHTML = ICONS.arrange;
$('thumbGridArrange').addEventListener('click', () => {
  thumbGridArranging = !thumbGridArranging;
  thumbGridSelected = null;
  showArranging();
});
// Thumbnails that change place glide there (FLIP), across as well as down.
function glideGrid(grid, move) {
  const cells = [...grid.querySelectorAll('[data-grid-index]')];
  const before = new Map(cells.map(cell => [cell, cell.getBoundingClientRect()]));
  for (const cell of cells) for (const animation of cell.getAnimations ? cell.getAnimations() : []) animation.cancel();
  move();
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  for (const cell of cells) {
    const was = before.get(cell), now = cell.getBoundingClientRect(), dx = was.left - now.left, dy = was.top - now.top;
    if (dx || dy) cell.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: 200, easing: 'cubic-bezier(.2,.8,.2,1)' });
  }
}
// The order now shown, saved: a set's images by their files, a collection's album by its items.
async function saveGridOrder(grid) {
  const order = [...grid.querySelectorAll('[data-grid-index]')].map(cell => thumbGridItems[+cell.dataset.gridIndex].ref);
  const what = thumbGridWhat;
  const url = what.set ? `/image-runs/${encodeURIComponent(what.set)}/order` : `/api/collections/${encodeURIComponent(what.collection)}/order`;
  const body = await collectionRequest(url, what.set ? { files: order } : { items: order });
  await poll();
  // Drawn again from what was saved (or, refused, as it was), still arranging.
  if ($('thumbGrid').open) openThumbGrid(what, true);
  return body;
}
// Dragging one: a copy of it floats under the finger, exactly where it is held; where it will land shows as a gap.
// It takes another's place only once the finger is well inside that one (its middle), so the two never swap back and
// forth as they glide. Held near the top or bottom of the grid, the grid scrolls.
let gridDrag = null, gridDragged = false;
function gridDragTo(x, y) {
  const drag = gridDrag;
  drag.x = x;
  drag.y = y;
  drag.ghost.style.transform = `translate(${x - drag.dx}px, ${y - drag.dy}px)`;
  const under = document.elementFromPoint ? document.elementFromPoint(x, y) : null;
  const target = under && under.closest ? under.closest('[data-grid-index]') : null;
  if (!target || target === drag.cell || target.parentElement !== drag.grid) return;
  const box = target.getBoundingClientRect(), insetX = box.width * 0.25, insetY = box.height * 0.25;
  if (x < box.left + insetX || x > box.right - insetX || y < box.top + insetY || y > box.bottom - insetY) return;
  const cells = [...drag.grid.children];
  glideGrid(drag.grid, () => (cells.indexOf(drag.cell) < cells.indexOf(target) ? target.after(drag.cell) : target.before(drag.cell)));
}
function gridAutoScroll(now) {
  const drag = gridDrag;
  if (!drag) return;
  drag.frame = 0;
  if (!scrollReorderEdge(drag.scroller, drag.y, drag, now)) return;
  gridDragTo(drag.x, drag.y);
  drag.frame = requestAnimationFrame(gridAutoScroll);
}
// Picks one up: a copy floats in host, and the grid it is in (where the pointer is captured, owner) saves the order on
// the drop. A scroller, if it has one, scrolls when the copy is held near its top or bottom.
function startGridDrag(e, cell, { host, owner, save, scroller = null }) {
  const box = cell.getBoundingClientRect();
  const ghost = cell.cloneNode(true);
  ghost.classList.add('grid-ghost');
  Object.assign(ghost.style, { position: 'fixed', left: '0px', top: '0px', width: `${box.width}px`, height: `${box.height}px`,
    transform: `translate(${box.left}px, ${box.top}px)`, pointerEvents: 'none', zIndex: 10 });
  host.appendChild(ghost);
  gridDrag = { cell, grid: cell.parentElement, ghost, pointer: e.pointerId, dx: e.clientX - box.left, dy: e.clientY - box.top, save, scroller,
    x: e.clientX, y: e.clientY, frame: 0, lastFrame: null, edgeSince: null, carry: 0,
    before: [...cell.parentElement.children].map(c => c.dataset.gridIndex).join() };
  cell.classList.add('dragging');
  try { owner.setPointerCapture(e.pointerId); } catch (err) {}
}
$('thumbGridBody').addEventListener('pointerdown', e => {
  if (!thumbGridArranging || e.button > 0) return;
  const cell = e.target.closest && e.target.closest('[data-grid-index]');
  if (!cell || cell.dataset.gridIndex !== thumbGridSelected) return;
  e.preventDefault();
  startGridDrag(e, cell, { host: $('thumbGrid'), owner: $('thumbGridBody'), save: saveGridOrder, scroller: $('thumbGridBody') });
});
function moveGridDrag(e) {
  if (!gridDrag || e.pointerId !== gridDrag.pointer) return;
  e.preventDefault();
  gridDragTo(e.clientX, e.clientY);
  if (!gridDrag.frame) gridDrag.frame = requestAnimationFrame(gridAutoScroll);
}
$('thumbGridBody').addEventListener('pointermove', moveGridDrag);
async function dropGrid(e) {
  if (!gridDrag || e.pointerId !== gridDrag.pointer) return;
  const { cell, grid, ghost, before, frame, save } = gridDrag;
  gridDrag = null;
  if (frame) cancelAnimationFrame(frame);
  ghost.remove();
  cell.classList.remove('dragging');
  gridDragged = true;
  setTimeout(() => { gridDragged = false; }, 0);
  if ([...grid.children].map(c => c.dataset.gridIndex).join() !== before) await save(grid);
}
$('thumbGridBody').addEventListener('pointerup', dropGrid);
$('thumbGridBody').addEventListener('pointercancel', dropGrid);
// A tap, not a scroll: the finger stayed put, and the grid wasn't moving (a tap that stops a fling only stops it).
let gridTap = null, gridScrolledAt = 0;
$('thumbGridBody').addEventListener('scroll', () => { gridScrolledAt = performance.now(); }, { passive: true });
$('thumbGridBody').addEventListener('pointerdown', e => {
  gridTap = { x: e.clientX, y: e.clientY, at: performance.now(), moving: performance.now() - gridScrolledAt < 120 };
}, true);
// Pinch: two fingers apart, bigger pictures (fewer to a row); together, smaller. On a laptop a trackpad pinch, which
// comes as Ctrl and the wheel. The size is kept (per browser), and what's under the fingers stays under them.
const THUMB_SIZE_KEY = 'gen-center.thumbSize', THUMB_LEAST = 48, THUMB_MOST = 260, THUMB_USUAL = 78;
let thumbSize = (() => { try { return Number(localStorage.getItem(THUMB_SIZE_KEY)) || THUMB_USUAL; } catch (e) { return THUMB_USUAL; } })();
let gridPinch = null, gridPinchedAt = -Infinity;
function setThumbSize(size, aroundY = null) {
  const body = $('thumbGridBody'), next = Math.round(Math.min(THUMB_MOST, Math.max(THUMB_LEAST, size)));
  const before = body.scrollHeight || 0, y = aroundY ?? (body.clientHeight || 0) / 2;
  thumbSize = next;
  const style = $('thumbGrid').style;
  if (style && style.setProperty) style.setProperty('--thumb-size', `${next}px`);
  // The grid grows or shrinks around the fingers: the same picture stays under them.
  if (before && body.scrollHeight) body.scrollTop = (body.scrollTop + y) * (body.scrollHeight / before) - y;
  try { localStorage.setItem(THUMB_SIZE_KEY, String(next)); } catch (e) {}
}
setThumbSize(thumbSize);
const pinchSpan = touches => Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY);
$('thumbGridBody').addEventListener('touchstart', e => {
  if (e.touches.length !== 2 || thumbGridArranging) return;
  gridPinch = { span: pinchSpan(e.touches) || 1, size: thumbSize };
  gridTap = null;
}, { passive: true });
// Not passive: two fingers on the grid zoom it, not the page, and don't scroll it.
$('thumbGridBody').addEventListener('touchmove', e => {
  if (!gridPinch || e.touches.length !== 2) return;
  e.preventDefault();
  const box = $('thumbGridBody').getBoundingClientRect();
  setThumbSize(gridPinch.size * pinchSpan(e.touches) / gridPinch.span, (e.touches[0].clientY + e.touches[1].clientY) / 2 - box.top);
  gridPinchedAt = performance.now();
}, { passive: false });
$('thumbGridBody').addEventListener('touchend', e => {
  if (gridPinch && e.touches.length < 2) { gridPinch = null; gridPinchedAt = performance.now(); }
}, { passive: true });
$('thumbGridBody').addEventListener('wheel', e => {
  if (!e.ctrlKey) return;
  e.preventDefault();
  setThumbSize(thumbSize * Math.exp(-e.deltaY * 0.01), e.clientY - $('thumbGridBody').getBoundingClientRect().top);
}, { passive: false });
function gridTapped(e) {
  const tap = gridTap;
  gridTap = null;
  // Fingers lifted off a pinch: that was the pinch, not a tap on a picture.
  if (performance.now() - gridPinchedAt < 400) return false;
  if (!tap || e.clientX == null || !e.pointerType) return true;  // A key press, or no pointer seen: as it is
  if (tap.moving || gridScrolledAt > tap.at) return false;
  return Math.hypot(e.clientX - tap.x, e.clientY - tap.y) < 10;
}
$('thumbGridBody').addEventListener('click', e => {
  const pick = e.target.closest && e.target.closest('[data-grid-index]');
  const item = pick && thumbGridItems[+pick.dataset.gridIndex];
  if (!item || !gridTapped(e)) return;
  if (thumbGridArranging) {
    if (!gridDragged) thumbGridSelected = thumbGridSelected === pick.dataset.gridIndex ? null : pick.dataset.gridIndex;
    showArranging();
    return;
  }
  $('thumbGrid').close();
  item.open();
});
$('thumbGridClose').addEventListener('click', () => $('thumbGrid').close());
// A tap on the dimmed page around it closes it too.
$('thumbGrid').addEventListener('click', e => { if (e.target === $('thumbGrid')) $('thumbGrid').close(); });
$('viewerGrid').innerHTML = ICONS.grid;
$('viewerGrid').addEventListener('click', () => {
  if (!viewing) return;
  openThumbGrid(viewerCollection ? { collection: viewerCollection } : viewing.film ? { films: viewing.folder } : { set: viewing.id });
});
// --- Edit: the Image side with Qwen-Image 2.1's edit workflow, for changing painted parts, expanding, or editing an image ---
const EDIT_WORKFLOW = 'image_Qwen21_edit_turbo.json';
// That one, or else another saved with the same model.
function editWorkflowName() {
  const names = Object.keys(imageWorkflows);
  return names.includes(EDIT_WORKFLOW) ? EDIT_WORKFLOW : names.find(name => imageWorkflows[name].model === 'qwen_image_21_edit') || '';
}
async function openEditor() {
  const epoch = workspaceEpoch;
  reopening('image');
  if (pipeline !== 'image') setPipeline('image');
  await loadImageWorkflows();
  if (epoch !== workspaceEpoch) return;
  // The preset chosen in Settings, as it was saved; else the Qwen-Image 2.1 edit workflow at the image's own size.
  const preset = SETTINGS.edit_preset && (presets.image || []).find(p => p.name === SETTINGS.edit_preset);
  if (preset) {
    applyPreset('image', preset.name);
    syncImageForm();
    saveImageForm();
    backToGenerate();
    return;
  }
  const name = editWorkflowName();
  if (!name) { showFormError(`Save Qwen-Image 2.1's edit workflow in ComfyUI as ${EDIT_WORKFLOW.replace('.json', '')} to edit images here.`); }
  else $('imageWorkflow').value = name;
  // Starts at the image's own shape and size, held to what the edit model makes.
  $('imageAspect').value = 'image';
  $('imageMegapixels').value = 'image';
  syncImageForm();
  saveImageForm();
  reopened('image');
  backToGenerate();
}
// A video from this image: Video with the preset chosen in Settings (else its own workflow), the image as image 1.
async function videoFromImage(id, position) {
  const epoch = workspaceEpoch;
  reopening('video');
  if (pipeline !== 'video') setPipeline('video');
  const preset = SETTINGS.edit_video_preset && (presets.video || []).find(p => p.name === SETTINGS.edit_video_preset);
  if (preset) applyPreset('video', preset.name);
  imageBoxes().forEach(box => clearImage(box));
  imagesShown = 1;
  syncVideoForm();
  const box = imageBoxes()[0];
  if (box) await useOutput(box, id, position, 'video');
  if (epoch !== workspaceEpoch) return;
  syncVideoForm();
  saveVideoForm();
  reopened('video');
  // Video's Generate: without saying so, it would go to Image's.
  backToGenerate('video');
}
// This image in Generate as image 1, with the edit workflow chosen.
async function editInGenerate(id, position) {
  const epoch = workspaceEpoch;
  await openEditor();
  if (epoch !== workspaceEpoch) return;
  sourceBoxes().forEach((box, i) => clearSource(box, i === 0));
  sourcesShown = 1;
  syncImageForm();
  const box = sourceBoxes()[0];
  if (box) await useOutput(box, id, position);
}
$('viewerPrompts').addEventListener('click', async () => {
  if (!viewing) return;
  const epoch = workspaceEpoch;
  const id = viewing.film ? viewing.run : viewing.id;
  if (!id) return;
  let data;
  try { data = await (await fetch(runUrl(id))).json(); } catch (e) { data = { error: 'Could not reach the panel. Try again.' }; }
  if (epoch !== workspaceEpoch) return;
  if (!data.ok) { alert(data.error || 'Could not open its prompt.'); return; }
  // An image: its own prompt. A film: each shot's, in order.
  const shot = viewing.film ? null : data.shots[viewing.position - 1];
  const detailed = shot ? shot.enhanced_prompt || shot.prompt
    : data.shots.map((s, i) => `${i + 1}. ${s.title}\n${s.comfy_prompt || s.enhanced_prompt || s.prompt}`).join('\n\n');
  // Made from your exact prompt: that is what it was made from, so it opens on yours, the detailed one a tap away.
  openPromptDetail(detailed, data.brief, data.direct ? 'yours' : 'detailed');
});
$('viewerClips').addEventListener('click', () => {
  if (!viewing || !viewing.film || !viewing.run) return;
  $('viewerVideo').pause();
  openShots(viewing.run);
});
$('viewerUse').addEventListener('click', () => {
  if (!viewing || !choosingFor) return;
  if (viewing.film) {
    if (choosingFor.kind !== 'media') return;
    const { name, folder: from } = viewing;
    closeViewer();
    chooseFilm(name, from);
    return;
  }
  if (choosingFor.kind === 'media') return;
  const { id, position } = viewing;
  closeViewer();
  chooseThis(id, position);
});
// A film for a reference box: the file itself, as if chosen from the disk.
async function chooseFilm(name, from = 'video') {
  const epoch = workspaceEpoch;
  const choice = choosingFor;
  if (!choice) return;
  backToGenerate(choice.side);
  stopChoosing();
  const input = choice.box.querySelector('input[type="file"]');
  try {
    const file = await runFile(`/videos/${from}/${encodeURIComponent(name)}`, name);
    if (epoch !== workspaceEpoch) return;
    if (!mediaBoxes().includes(choice.box) || choice.box.hidden || input.disabled) {
      showFormError('The reference box changed before the film was loaded. Choose it again.');
      return;
    }
    putFile(input, new File([file], name, { type: file.type && file.type !== 'application/octet-stream' ? file.type : 'video/mp4' }));
    showMedia(choice.box);
    syncMediaInput();
  } catch (e) {
    if (epoch !== workspaceEpoch) return;
    showFormError(e.message || 'Could not load that film.');
  }
}
$('viewerEdit').addEventListener('click', () => {
  if (!viewing || viewing.film) return;
  const box = $('editMenu');
  box.classList.remove('closing');
  box.showModal();
  placeOverViewerButtons(box);
});
function closeEditMenu(then) {
  const box = $('editMenu');
  if (!box.open || box.classList.contains('closing')) return;
  box.classList.add('closing');
  setTimeout(() => { box.close(); box.classList.remove('closing'); if (then) then(); }, 150);
}
$('editMenu').addEventListener('click', e => {
  const pick = e.target.closest && e.target.closest('[data-edit-to]');
  if (!pick) {
    const r = e.currentTarget.getBoundingClientRect();
    if (e.target === e.currentTarget && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) closeEditMenu();
    return;
  }
  if (!viewing || viewing.film) return;
  const { id, position } = viewing, to = pick.dataset.editTo;
  closeEditMenu(() => {
    closeViewer();
    if (to === 'video') videoFromImage(id, position); else editInGenerate(id, position);
  });
});
$('editMenu').addEventListener('cancel', e => { e.preventDefault(); closeEditMenu(); });
// Every option as a set had it: what it chose, else the workflow's own default.
function applyOptions(box, options, chosen) {
  if (box === $('imageOptionsBox')) {
    if (chosen.image_upscale) $('imageUpscale').value = chosen.image_upscale;
    setImageUpscaleDenoise(chosen.image_upscale_denoise || 0);
    if (chosen.image_upscale_mp) $('imageUpscaleMp').value = chosen.image_upscale_mp;
    showImageUpscale();
    syncImageSize();
  }
  if (box === $('videoOptionsBox')) {
    if (chosen.latent_upscale) $('videoLatentUpscale').value = chosen.latent_upscale;
    if (chosen.latent_upscale_mp) $('videoLatentMp').value = chosen.latent_upscale_mp;
    if (chosen.latent_upscale_denoise) $('videoLatentDenoise').value = chosen.latent_upscale_denoise;
    if (chosen.latent_upscale_steps) $('videoLatentSteps').value = chosen.latent_upscale_steps;
    if (chosen.latent_upscale_sampler) $('videoLatentSampler').value = chosen.latent_upscale_sampler;
    if (chosen.latent_upscale_chunking) $('videoLatentChunking').checked = chosen.latent_upscale_chunking === '1';
    showVideoLatent();
  }
  // What the run chose that this form can't show now, said rather than swapped for another without a word.
  box.unavailable = [];
  for (const option of options.filter(o => !o.role)) {
    const value = chosen[option.id] ?? option.default;
    // The image side's Mode and its Denoise sit at the top of Setup, not in the box.
    const field = name => optionField(box, `[name="${name}"]:not([type="hidden"])`)
      || (box === $('imageOptionsBox') ? $('formImage').querySelector(`#imageWorkflowModeBox [name="${name}"]`) : null);
    if (option.kind === 'lora_stack') box.querySelector('[name=opt_additional_loras]').value = value;
    else if (option.kind === 'switch') { const el = field(`opt_${option.id}`); if (el) el.checked = value === '1'; }
    else if (option.kind === 'strength') {
      const on = field(`opt_${option.id}_on`), strength = field(`opt_${option.id}_strength`);
      if (on) on.checked = value !== '0';
      if (strength && value !== '0') strength.value = value;
    } else {
      const el = field(`opt_${option.id}`);
      if (el && el.options && ![...el.options].some(o => o.value === String(value))) {
        // A LoRA with NSFW in its name is only offered in Private mode.
        const name = String(value).replace(/\.safetensors$/, '');
        const used = (chosen[option.parent] ?? (options.find(o => o.id === option.parent) || {}).default) === '1';
        if (option.id === 'lora_name' && used) box.unavailable.push(/nsfw|uncensor/i.test(name) && !privateMode
          ? `This set used the LoRA ${name}, which is only offered in Private mode: switch it on and open the set again.`
          : `This set used the LoRA ${name}, which isn't installed now.`);
      } else if (el) el.value = value;
    }
  }
  renderLoraStack(box);
  if (box.dataset.workflow) rememberOptions(box);
}
// Each image as a file of its own: no zip to open afterwards.
function downloadImages(id, positions) {
  positions.forEach((position, i) => setTimeout(() => {
    const link = document.createElement('a');
    link.href = `/image-runs/${encodeURIComponent(id)}/files/${position}?download=1`;
    link.download = '';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, i * 400));  // One at a time, or a browser drops all but the first
}
// --- The image viewer: one picture over a dimmed page, with Download, Delete and Close ---
let viewing = null;
const UPSCALE_MOST_SIDE = 1440, TILED_MOST_SIDE = 4096;
// As the server's (panel/image.py upscale_problem): SeedVR2 takes the whole image at once.
function upscaleProblem(method, width, height) {
  if (method === 'seedvr2' && Math.min(width, height) > UPSCALE_MOST_SIDE)
    return `Too big for this one: ${Math.min(width, height)}px on its shorter side, past ${UPSCALE_MOST_SIDE}px.`;
  if (method !== 'seedvr2' && Math.max(width, height) > TILED_MOST_SIDE)
    return `Too big: ${Math.max(width, height)}px on its longer side, past ${TILED_MOST_SIDE}px.`;
  return '';
}
// A picture in the viewer: its own upscale, not the set's, and in a LoRA comparison its own LoRA, not all those the
// set tests; its other pills are the set's.
function pictureMetadata(set, picture) {
  const ownWriter = Object.prototype.hasOwnProperty.call(picture, 'prompt_llm');
  const ownLora = Object.prototype.hasOwnProperty.call(picture, 'lora');
  // In a workflow comparison, the one it ran through, still marked as a comparison's.
  const pills = set.pills && [...set.pills.map(p => p.kind === 'workflow' && picture.workflow ? { ...p, text: picture.workflow } : p)
    .filter(p => p.kind !== 'upscale' && (!ownWriter || p.kind !== 'llm') && (!ownLora || p.kind !== 'lora')),
    ...(ownWriter && picture.prompt_llm ? [{ text: picture.prompt_llm, kind: 'llm',
      diff: set.pills.some(p => p.kind === 'llm' && p.text === picture.prompt_llm && p.diff) }] : []),
    ...(ownLora && picture.lora ? [{ text: `LoRA: ${picture.lora}`, kind: 'lora', diff: true }] : []),
    ...(picture.upscaled ? [{ text: `Upscaled: ${picture.upscaled}`, kind: 'upscale', diff: false }] : [])];
  viewerMetadata({ ...set, upscaled: picture.upscaled || null, pills }, 'image');
}
function viewerMetadata(item, side = 'video') {
  // Its pills, all of them, when it has them; else the lines it had before pills.
  const pills = item.pills && item.pills.length ? item.pills : null;
  const lines = pills ? [] : [connectionDescription(item), ...(item.loras || []).map(lora => `LoRA: ${lora}`), h3Description(item), item.upscaled && `Upscaled: ${item.upscaled}`].filter(Boolean);
  const button = $('viewerMeta'), details = $('viewerMetaDetails');
  const has = !!pills || lines.length > 0;
  button.textContent = [item.model, item.llm].filter(Boolean).join(' · ') || (has ? 'Details' : '');
  button.hidden = !button.textContent;
  button.disabled = !has;
  if (pills) {
    // The pills themselves, in place of the line that opened them: one line, the rest a tap away.
    button.hidden = true;
    details.hidden = false;
    const html = `<div class="pills ${side}" data-lines="1" role="button" tabindex="0">${pillsHtml(pills)}</div>`;
    // Each poll asks again: the same pills stay as they are, opened or not.
    if (details.dataset.pills === html) return;
    details.dataset.pills = html;
    details.innerHTML = html;
    requestAnimationFrame(() => markPillOverflow(details));
    return;
  }
  details.dataset.pills = '';
  details.textContent = lines.join('\n');
  if (!has) details.hidden = true;
  button.setAttribute('aria-expanded', String(!details.hidden));
}
$('viewerMeta').addEventListener('click', () => {
  if ($('viewerMeta').disabled) return;
  $('viewerMetaDetails').hidden = !$('viewerMetaDetails').hidden;
  $('viewerMeta').setAttribute('aria-expanded', String(!$('viewerMetaDetails').hidden));
});
// Choosing for a box: Use shows for what it takes (an image, or a film for a reference box), before Close.
function showChoosing(video) {
  const choosing = !!choosingFor && (choosingFor.kind === 'media' ? video : !video);
  $('viewerUse').hidden = !choosing;
  const row = $('viewerClose').parentElement;
  if (row) row.classList.toggle('choosing', choosing);
}
function showViewerMedia(video) {
  $('viewerClips').hidden = true;
  showChoosing(video);
  $('viewerTools').hidden = false;
  for (const id of ['viewerVariations', 'viewerEdit', 'viewerPrompts', 'viewerUpscale']) $(id).hidden = false;
  $('viewerImage').hidden = video;
  $('viewerVideo').hidden = !video;
  if (video) $('viewerUpscaled').hidden = true;
  if (!video) { $('viewerVideo').pause(); $('viewerVideo').removeAttribute('src'); }
}
let viewerTransition = null;
function clearViewerTransition() {
  if (!viewerTransition) return;
  const { media, ghost, ready, failed, event, timer } = viewerTransition;
  media.removeEventListener(event, ready);
  media.removeEventListener('error', failed);
  clearTimeout(timer);
  ghost.remove();
  viewerTransition = null;
}
// media: what shows now, left as a picture of itself that slides away. target: what shows next, whose loading lets it
// go: the same element, or the other one when a swipe goes between a film and a set (it never loads in the old one,
// so waiting on that left the screen black).
function transitionViewer(media, direction, open, target = media) {
  clearViewerTransition();
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches ||
      (media === $('viewerVideo') ? !(media.readyState >= 2 && media.videoWidth && media.videoHeight) : !media.complete || !media.naturalWidth)) {
    open();
    return;
  }
  const box = media.getBoundingClientRect();
  let ghost;
  if (media === $('viewerVideo')) {
    ghost = document.createElement('canvas');
    ghost.width = media.videoWidth;
    ghost.height = media.videoHeight;
    ghost.getContext('2d').drawImage(media, 0, 0);
  } else {
    ghost = media.cloneNode();
    ghost.removeAttribute('id');
    ghost.removeAttribute('alt');
  }
  ghost.className = 'viewer-out';
  Object.assign(ghost.style, { left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, height: `${box.height}px`, transform: 'none' });
  ghost.setAttribute('aria-hidden', 'true');
  $('imageViewer').appendChild(ghost);
  const event = target === $('viewerVideo') ? 'loadeddata' : 'load';
  const failed = () => clearViewerTransition();
  const ready = () => {
    clearTimeout(viewerTransition.timer);
    ghost.addEventListener('animationend', clearViewerTransition, { once: true });
    ghost.classList.add(direction);
    viewerTransition.timer = setTimeout(clearViewerTransition, 500);
  };
  target.addEventListener(event, ready, { once: true });
  target.addEventListener('error', failed, { once: true });
  viewerTransition = { media: target, ghost, ready, failed, event, timer: setTimeout(clearViewerTransition, 10000) };
  open();
}
// A film in the viewer, playing; a swipe goes to the one beside it in Output.
function openFilm(name, filmFolder = folder) {
  const films = viewerCollection ? collectionAlbums(viewerCollection).films : visibleFilms(), at = films.findIndex(v => v.name === name);
  if (at < 0) return;
  const film = films[at], url = `/videos/${filmFolder}/${encodeURIComponent(name)}`;
  viewing = { film: true, name, run: film.run || null, folder: filmFolder, latent: !!film.latent };
  document.body.dataset.viewing = filmFolder === 'video' ? 'video' : 'shorts';
  showViewerMedia(true);
  // A film has Upscale (Video's only) and Prompts (its run's, if still saved), not the image editing.
  const canUpscale = filmFolder === 'video', canPrompt = !!film.run;
  // Its settings back in Generate, from the same place as an image's "More like this".
  $('viewerEdit').hidden = true;
  $('viewerVariations').hidden = !canPrompt || filmFolder !== 'video';
  $('viewerVariations').title = 'Open the settings it was made with in Generate';
  $('viewerVariations').setAttribute('aria-label', 'Open its settings');
  $('viewerUpscale').hidden = !canUpscale;
  $('viewerUpscale').classList.remove('dim');
  $('viewerPrompts').hidden = !canPrompt;
  $('viewerClips').hidden = filmFolder !== 'video' || !canPrompt;
  $('viewerRes').textContent = sizeText(film.resolution);
  $('viewerCount').textContent = films.length > 1 ? `${at + 1} of ${films.length}` : '';
  viewerMetadata(film);
  $('viewerVideo').src = url;
  setViewerTitle(film.title || film.topic || film.name);
  $('viewerDownload').href = `/download/${filmFolder}/${encodeURIComponent(name)}`;
  if (!$('imageViewer').open) $('imageViewer').showModal();
  $('viewerVideo').play().catch(() => {});  // A browser may want a tap first
  // Its run, for Prompts and its settings: asked for now, so either opens at once.
  if (film.run) prefetch(runUrl(film.run));
}
function downloadFile(url) {
  const link = document.createElement('a');
  link.href = url;
  link.download = '';
  document.body.appendChild(link);
  link.click();
  link.remove();
}
function openViewer(id, position) {
  const set = findSet(id), picture = set && set.images.find(p => p.position === position);
  if (!picture) return;
  viewing = { id, position };
  document.body.dataset.viewing = 'image';
  showViewerMedia(false);
  $('viewerVariations').title = 'More like this: the generation it came from, back in Generate with its Variety and chips';
  $('viewerVariations').setAttribute('aria-label', 'More like this');
  resetZoom();
  const url = `/image-runs/${encodeURIComponent(id)}/files/${position}?v=${picture.version}`;
  // The small picture the set already shows comes at once; the full one replaces it as soon as it has arrived.
  // The full file can be many megabytes, which is why a preview used to take so much longer than the album.
  const img = $('viewerImage');
  img.dataset.full = url;
  img.src = `/image-runs/${encodeURIComponent(id)}/thumbnails/${position}?v=${picture.version}`;
  const full = new Image();
  full.onload = () => { if (img.dataset.full === url) img.src = url; };
  full.src = url;
  $('viewerImage').alt = picture.title;
  const at = set.images.indexOf(picture);
  setViewerTitle(picture.title);
  // In a collection: where it is in the collection's images, not in the set it was made in.
  const album = viewerCollection ? collectionAlbums(viewerCollection).images : set.images.filter(p => !p.collection);
  const place = album.findIndex(p => (p.set || set.id) === id && p.position === position);
  $('viewerCount').textContent = album.length > 1 && place >= 0 ? `${place + 1} of ${album.length}` : '';
  // This picture's own upscale, not another of the set's.
  pictureMetadata(set, picture);
  $('viewerUpscaled').hidden = !picture.upscaled;
  if (picture.upscaled) {
    $('viewerUpscaled').innerHTML = ICONS.upscale;
    $('viewerUpscaled').setAttribute('aria-label', `Upscaled: ${picture.upscaled}`);
  }
  $('viewerDownload').href = `${url}&download=1`;
  $('viewerRes').textContent = sizeText(picture.resolution);
  if (!$('imageViewer').open) $('imageViewer').showModal();
  // Its set, for Prompts, More like this and its settings: asked for now, so each opens at once.
  prefetch(runUrl(id));
}
// The viewer's size, one way whichever told it (the saved "880x1920", or the picture once loaded): "880 × 1920".
function sizeText(size) { return String(size || '').replace(/^(\d+)\s*[x×]\s*(\d+)$/i, '$1 × $2'); }
$('viewerImage').addEventListener('load', () => {
  const img = $('viewerImage');
  if (img.dataset.full && !String(img.src).endsWith(img.dataset.full)) return;  // The small picture, while the full one comes
  $('viewerRes').textContent = viewing && !viewing.film && img.naturalWidth ? sizeText(`${img.naturalWidth}x${img.naturalHeight}`) : '';
  // Past 1440p on its shorter side, SeedVR2 can't take it: greyed, but the other ways still can.
  $('viewerUpscale').classList.toggle('dim', !!viewing && !viewing.film && Math.min(img.naturalWidth, img.naturalHeight) > UPSCALE_MOST_SIDE);
});
// The image before or after this one in its set: a swipe, or the arrow keys. Round in a loop: from the last on to
// the first, and from the first back to the last.
function stepViewer(by) {
  if (!viewing) return false;
  if (viewerCollection) {
    const next = collectionNeighbour(by);
    if (!next) return false;
    disarm($('viewerDelete'));
    transitionViewer($(viewing.film ? 'viewerVideo' : 'viewerImage'), by > 0 ? 'to-right' : 'to-left', next);
    return true;
  }
  if (viewing.film) {
    const films = visibleFilms(), next = loopNeighbour(films, films.findIndex(v => v.name === viewing.name), by);
    if (!next) return false;
    disarm($('viewerDelete'));
    transitionViewer($('viewerVideo'), by > 0 ? 'to-right' : 'to-left', () => openFilm(next.name, viewing.folder));
    return true;
  }
  const set = imageSets.find(s => s.id === viewing.id);
  const images = set ? set.images : [];
  const next = loopNeighbour(images, images.findIndex(p => p.position === viewing.position), by);
  if (!next) return false;
  disarm($('viewerDelete'));
  transitionViewer($('viewerImage'), by > 0 ? 'to-right' : 'to-left', () => openViewer(viewing.id, next.position));
  return true;
}
let swipeFrom = null;
// --- Zooming into an image: the page itself doesn't zoom, so the footer stays put; the picture does ---
// Pinch around your fingers, double-tap for 2.5x where you tapped, and drag about while zoomed. A swipe turns
// to the next image only at its own size.
const MOST_ZOOM = 5, TAP_ZOOM = 2.5;
const zoom = { scale: 1, x: 0, y: 0 };
let pinch = null, drag = null, lastTap = null;
// Zoomed in, the picture still fills its frame: an edge stops at the frame's edge rather than going off the page.
// The frame's black bars (object-fit: contain) don't count; a side still narrower than the frame stays centred.
function clampZoom(image) {
  const boxW = image.offsetWidth, boxH = image.offsetHeight;
  if (!boxW || !boxH) return;
  const ratio = image.naturalWidth && image.naturalHeight ? image.naturalWidth / image.naturalHeight : boxW / boxH;
  const shownW = Math.min(boxW, boxH * ratio), shownH = Math.min(boxH, boxW / ratio);
  const roomX = Math.max(0, (shownW * zoom.scale - boxW) / 2), roomY = Math.max(0, (shownH * zoom.scale - boxH) / 2);
  zoom.x = Math.min(roomX, Math.max(-roomX, zoom.x));
  zoom.y = Math.min(roomY, Math.max(-roomY, zoom.y));
}
function applyZoom(ease = false) {
  const image = $('viewerImage');
  if (zoom.scale > 1) clampZoom(image);
  image.classList.toggle('easing', ease);
  image.style.transform = zoom.scale > 1 ? `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.scale})` : '';
}
function resetZoom() {
  zoom.scale = 1;
  zoom.x = zoom.y = 0;
  pinch = drag = null;
  applyZoom();
}
// To scale to s around the screen point m, from where it was (s0, t0) with the image's centre at c.
function zoomAround(s, m, s0, t0, c) {
  zoom.scale = Math.min(MOST_ZOOM, Math.max(1, s));
  if (zoom.scale === 1) { zoom.x = zoom.y = 0; return; }
  zoom.x = m.x - c.x - (zoom.scale / s0) * (m.x - c.x - t0.x);
  zoom.y = m.y - c.y - (zoom.scale / s0) * (m.y - c.y - t0.y);
}
function imageCentre() {
  const box = $('viewerImage').getBoundingClientRect();
  return { x: box.left + box.width / 2 - zoom.x, y: box.top + box.height / 2 - zoom.y };
}
const between = (a, b) => ({ x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 });
const apart = (a, b) => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
$('viewerImage').addEventListener('touchstart', e => {
  if (e.touches.length === 2) {
    e.preventDefault();
    pinch = { dist: apart(e.touches[0], e.touches[1]), mid: between(e.touches[0], e.touches[1]), scale: zoom.scale,
              at: { x: zoom.x, y: zoom.y }, centre: imageCentre() };
    drag = null;
  } else if (e.touches.length === 1 && zoom.scale > 1) {
    drag = { x: e.touches[0].clientX - zoom.x, y: e.touches[0].clientY - zoom.y };
  }
}, { passive: false });
$('viewerImage').addEventListener('touchmove', e => {
  if (pinch && e.touches.length === 2) {
    e.preventDefault();
    zoom.scale = Math.min(MOST_ZOOM, Math.max(1, pinch.scale * apart(e.touches[0], e.touches[1]) / pinch.dist));
    // Keeps the point between your fingers under them, wherever they move.
    const m = between(e.touches[0], e.touches[1]), s = zoom.scale;
    zoom.x = m.x - pinch.centre.x - (s / pinch.scale) * (pinch.mid.x - pinch.centre.x - pinch.at.x);
    zoom.y = m.y - pinch.centre.y - (s / pinch.scale) * (pinch.mid.y - pinch.centre.y - pinch.at.y);
    if (s === 1) zoom.x = zoom.y = 0;
    applyZoom();
  } else if (drag && e.touches.length === 1) {
    e.preventDefault();
    zoom.x = e.touches[0].clientX - drag.x;
    zoom.y = e.touches[0].clientY - drag.y;
    applyZoom();
  }
}, { passive: false });
$('viewerImage').addEventListener('touchend', e => {
  if (e.touches.length < 2) pinch = null;
  if (!e.touches.length) drag = null;
  if (e.touches.length || e.changedTouches.length !== 1) return;
  // Two taps close together: in to 2.5x where you tapped, or back out.
  const touch = e.changedTouches[0], now = Date.now();
  if (lastTap && now - lastTap.at < 300 && Math.hypot(touch.clientX - lastTap.x, touch.clientY - lastTap.y) < 30) {
    lastTap = null;
    if (zoom.scale > 1) resetZoom();
    else zoomAround(TAP_ZOOM, { x: touch.clientX, y: touch.clientY }, 1, { x: 0, y: 0 }, imageCentre());
    applyZoom(true);
    e.preventDefault();
  } else {
    lastTap = { at: now, x: touch.clientX, y: touch.clientY };
  }
});
// Swipes: on the picture or film, sideways to the next or previous one and up or down to the next or previous set;
// down on the buttons under it, the preview closes. Anywhere else a finger is only a tap or a scroll.
$('imageViewer').addEventListener('touchstart', e => {
  const target = e.target, onMedia = target === $('viewerImage') || target === $('viewerVideo');
  const onBar = !onMedia && !!(target && target.closest && target.closest('.viewer-bar'));
  // Zoomed in, a finger moves the picture rather than turning to the next one.
  const media = onMedia && (viewing && viewing.film || zoom.scale === 1);
  swipeFrom = e.touches.length === 1 && (media || onBar) ? { x: e.touches[0].clientX, y: e.touches[0].clientY, onBar } : null;
}, { passive: true });
$('imageViewer').addEventListener('touchend', e => {
  if (!swipeFrom || !e.changedTouches.length) return;
  const from = swipeFrom;
  swipeFrom = null;
  const dx = e.changedTouches[0].clientX - from.x, dy = e.changedTouches[0].clientY - from.y;
  if (from.onBar) {
    if (dy > 60 && dy > Math.abs(dx) * 1.5) closeViewer();
    return;
  }
  if (viewing && !viewing.film && zoom.scale > 1) return;
  // Sideways, and far enough to mean it: a tap or a scroll isn't a swipe. Up and down: the next or the previous set.
  if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) stepViewer(dx < 0 ? 1 : -1);
  else if (Math.abs(dy) > 60 && Math.abs(dy) > Math.abs(dx) * 1.5) stepSet(dy < 0 ? 1 : -1);
});
let outputArranging = false, outputSelected = null, outputOrderSaving = false;
const outputKey = item => item.set ? `image:${item.set.id}` : `film:${item.film.name}`;
// Known batches trade timestamp slots; an unseen generation keeps its own, newest-first slot.
function outputItems() {
  const sets = showsImages() ? filtered(imageSets).filter(set => set.images.length).map(set => ({ set, t: madeAt(set.id, set.mtime) })) : [];
  const films = showsFilms() ? visibleFilms().map(film => ({ film, t: filmMadeAt(film) })) : [];
  const items = [...sets, ...films].sort((a, b) => b.t - a.t);
  const byKey = new Map(items.map(item => [outputKey(item), item]));
  const ordered = (SETTINGS.output_order || []).filter(key => byKey.has(key));
  const placed = new Set(ordered), slots = ordered.map(key => byKey.get(key))[Symbol.iterator]();
  return items.map(item => placed.has(outputKey(item)) ? slots.next().value : item);
}
function showOutputArranging() {
  $('imageSets').classList.toggle('arranging', outputArranging);
  $('outputArrange').classList.toggle('on', outputArranging);
  $('outputArrange').setAttribute('aria-pressed', String(outputArranging));
  for (const cell of $('imageSets').querySelectorAll('[data-output-key]')) {
    const selected = outputArranging && cell.dataset.outputKey === outputSelected;
    cell.classList.toggle('selected', selected);
    if (outputArranging) cell.setAttribute('aria-pressed', String(selected));
    else cell.removeAttribute('aria-pressed');
  }
}
$('outputArrange').innerHTML = ICONS.arrange;
$('outputArrange').addEventListener('click', () => {
  outputArranging = !outputArranging;
  outputSelected = null;
  showOutputArranging();
});
async function placeOutput(ids) {
  if (outputOrderSaving) return;
  outputOrderSaving = true;
  $('outputArrange').disabled = true;
  try {
    await saveSettings({ output_order: ids }, text => { if (text) alert(text); });
    $('imageSets').dataset.key = '';
    renderImageSets();
  } finally {
    outputOrderSaving = false;
    $('outputArrange').disabled = false;
  }
}
$('imageSets').addEventListener('pointerdown', e => {
  if (!outputArranging || outputOrderSaving || e.button > 0) return;
  const cell = e.target.closest && e.target.closest('[data-output-key]');
  if (!cell || cell.dataset.outputKey !== outputSelected) return;
  e.preventDefault();
  startGridDrag(e, cell, { host: document.body, owner: $('imageSets'),
    save: grid => placeOutput([...grid.children].map(c => c.dataset.outputKey)),
    scroller: DESK.matches ? $('imageSets') : document.scrollingElement });
});
$('imageSets').addEventListener('pointermove', moveGridDrag);
$('imageSets').addEventListener('pointerup', dropGrid);
$('imageSets').addEventListener('pointercancel', dropGrid);
$('imageSets').addEventListener('keydown', e => {
  if (!outputArranging || outputOrderSaving) return;
  const cell = e.target.closest && e.target.closest('[data-output-key]');
  if (!cell) return;
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    outputSelected = cell.dataset.outputKey === outputSelected ? null : cell.dataset.outputKey;
    showOutputArranging();
    return;
  }
  if (cell.dataset.outputKey !== outputSelected || !['ArrowUp', 'ArrowDown'].includes(e.key)) return;
  e.preventDefault();
  const ids = outputItems().map(outputKey), at = ids.indexOf(outputSelected), to = at + (e.key === 'ArrowUp' ? -1 : 1);
  if (at < 0 || to < 0 || to >= ids.length) return;
  [ids[at], ids[to]] = [ids[to], ids[at]];
  placeOutput(ids).then(() => {
    [...$('imageSets').querySelectorAll('[data-output-key]')].find(item => item.dataset.outputKey === outputSelected)?.focus();
  });
});
// The film or set after or before this one in Output, as it lists them (a set from its first picture).
function stepSet(by) {
  if (!viewing) return false;
  // In a collection: up and down go between its images and its films, and no further.
  if (viewerCollection) {
    const albums = collectionAlbums(viewerCollection), toFilms = !viewing.film;
    if ((by > 0) !== toFilms) return false;
    const first = toFilms ? albums.films[0] : albums.images[0];
    if (!first) return false;
    disarm($('viewerDelete'));
    if (viewing.film) $('viewerVideo').pause();
    transitionViewer($(viewing.film ? 'viewerVideo' : 'viewerImage'), by > 0 ? 'to-down' : 'to-up',
      () => toFilms ? openFilm(first.name, 'video') : openViewer(first.set, first.position), $(toFilms ? 'viewerVideo' : 'viewerImage'));
    return true;
  }
  const items = pipeline === 'shorts' ? [] : outputItems();
  const at = items.findIndex(item => viewing.film ? item.film && item.film.name === viewing.name : item.set && item.set.id === viewing.id);
  if (at >= 0) {
    const next = items[at + by];
    if (!next) return false;
    disarm($('viewerDelete'));
    if (viewing.film && next.set) $('viewerVideo').pause();
    transitionViewer($(viewing.film ? 'viewerVideo' : 'viewerImage'), by > 0 ? 'to-down' : 'to-up',
      () => next.film ? openFilm(next.film.name, 'video') : openViewer(next.set.id, next.set.images[0].position),
      $(next.film ? 'viewerVideo' : 'viewerImage'));
    return true;
  }
  if (viewing.film) {
    const films = visibleFilms(), next = films[films.findIndex(v => v.name === viewing.name) + by];
    if (!next) return false;
    disarm($('viewerDelete'));
    transitionViewer($('viewerVideo'), by > 0 ? 'to-down' : 'to-up', () => openFilm(next.name, viewing.folder));
    return true;
  }
  const sets = filtered(imageSets).filter(set => set.images.length);
  const next = sets[sets.findIndex(set => set.id === viewing.id) + by];
  if (!next) return false;
  disarm($('viewerDelete'));
  transitionViewer($('viewerImage'), by > 0 ? 'to-down' : 'to-up', () => openViewer(next.id, next.images[0].position));
  return true;
}
$('imageViewer').addEventListener('keydown', e => {
  if (e.key === 'ArrowRight' && stepViewer(1)) e.preventDefault();
  else if (e.key === 'ArrowLeft' && stepViewer(-1)) e.preventDefault();
  else if (e.key === 'ArrowDown' && stepSet(1)) e.preventDefault();
  else if (e.key === 'ArrowUp' && stepSet(-1)) e.preventDefault();
  // Del on a keyboard is the Delete button: once to arm it, again to delete, as two taps are. Held down, it doesn't
  // repeat into the second; typed in a box of the viewer's, it is the box's.
  else if (e.key === 'Delete' && !e.repeat && !/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName || '')
           && !$('viewerDelete').hidden && !$('viewerDelete').disabled) {
    e.preventDefault();
    $('viewerDelete').click();
  }
});
function closeViewer() {
  if ($('imageViewer').open) $('imageViewer').close();
}
// Closed, Output shows the batch it was on in the middle of the screen (at the top if it's taller than the screen):
// swiped through to another set, that one. Only from Output itself (not a collection, Finished or the queue), and only
// when it's on screen.
function revealViewedBatch(was, collection) {
  if (!was || collection) return;
  const key = was.film ? `film:${was.name}` : `image:${was.id}`;
  const batch = [...$('imageSets').querySelectorAll('.output-batch[data-output-key]')].find(cell => cell.dataset.outputKey === key);
  if (!batch || !batch.getClientRects().length) return;
  const tall = batch.getBoundingClientRect && batch.getBoundingClientRect().height > window.innerHeight * 0.8;
  batch.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: tall ? 'start' : 'center' });
}
$('imageViewer').addEventListener('close', () => {
  clearViewerTransition();
  for (const id of ['viewerUpscaleBar', 'upscaleSettings', 'moveSheet', 'pillsMenu', 'editMenu']) if ($(id).open) $(id).close();
  revealViewedBatch(viewing, viewerCollection);
  viewing = null;
  viewerCollection = null;
  $('viewerMetaDetails').hidden = true;
  $('viewerMeta').setAttribute('aria-expanded', 'false');
  $('viewerImage').removeAttribute('src');
  $('viewerVideo').pause();
  $('viewerVideo').removeAttribute('src');
  disarm($('viewerDelete'));
});
// A tap on the dimmed page around it closes it too.
$('imageViewer').addEventListener('click', e => { if (e.target === $('imageViewer')) closeViewer(); });
$('viewerClose').addEventListener('click', closeViewer);
$('viewerDelete').addEventListener('click', async () => {
  if (!viewing || $('viewerDelete').disabled || !secondTap($('viewerDelete'))) return;
  const original = viewing;
  const { id, position, film, name } = viewing;
  const set = !film && imageSets.find(s => s.id === id);
  const pictures = set ? set.images : [];
  const index = pictures.findIndex(p => p.position === position);
  const next = index < 0 ? null : pictures[index + 1] || pictures[index - 1];
  const url = film ? `/delete/${viewing.folder}/${encodeURIComponent(name)}` : `/image-runs/${encodeURIComponent(id)}/delete/${position}`;
  // In a collection: the one after it in the collection's album (or the one before), found again by its file once the
  // set's places have shifted.
  let after = null;
  if (viewerCollection) {
    const albums = collectionAlbums(viewerCollection), album = film ? albums.films : albums.images;
    const at = film ? album.findIndex(v => v.name === name) : album.findIndex(p => p.set === id && p.position === position);
    const other = at < 0 ? null : album[at + 1] || album[at - 1];
    after = other && (film ? { film: other.name } : { set: other.set, file: other.file });
  } else if (film && pipeline === 'shorts') {
    const films = visibleFilms(), at = films.findIndex(v => v.name === name);
    const other = at < 0 ? null : films[at + 1] || films[at - 1];
    after = other && { film: other.name };
  } else if (film || !next) {
    const items = outputItems(), at = items.findIndex(item => film ? item.film && item.film.name === name : item.set && item.set.id === id);
    const other = at < 0 ? null : items[at + 1] || items[at - 1];
    if (other) after = other.film ? { film: other.film.name } : { set: other.set.id, file: other.set.images[0]?.file };
  }
  let body;
  $('viewerDelete').disabled = true;
  $('viewerDelete').classList.add('deleting');
  $('viewerDelete').setAttribute('aria-busy', 'true');
  try {
    body = await (await fetch(url, { method: 'POST' })).json();
  } catch (e) {
    body = { error: 'Could not reach the panel. Try again.' };
  }
  try {
    if (!body.ok) { alert(body.error || 'Could not delete it.'); return; }
    if (viewerCollection) {
      await poll();
      if (viewing !== original) return;  // Moved on in the meantime
      if (after && after.film && (lastVideos.video || []).some(v => v.name === after.film)) { openFilm(after.film, 'video'); return; }
      const set = after && after.set && findSet(after.set), picture = set && set.images.find(p => p.file === after.file);
      if (picture) openViewer(set.id, picture.position); else closeViewer();
      return;
    }
    if (!film && Array.isArray(body.images)) {
      const updated = imageSets.find(s => s.id === id), fullSet = allImageSets.find(s => s.id === id);
      const membership = new Map((fullSet ? fullSet.images : pictures).map(p => [p.file, p.collection]));
      const images = body.images.map(p => ({ ...p, collection: membership.get(p.file) }));
      if (fullSet) fullSet.images = images;
      if (updated) updated.images = images.filter(p => !p.collection);
      if (viewing && !viewing.film && viewing.id === id) {
        const current = viewing === original || viewing.position === position ? next && next.position : viewing.position;
        const nextPosition = current && current - (current > position ? 1 : 0);
        if (updated && updated.images.some(p => p.position === nextPosition)) openViewer(id, nextPosition);
        else if (after && after.film) openFilm(after.film, 'video');
        else if (after && after.set) {
          const nextSet = findSet(after.set), picture = nextSet && nextSet.images.find(p => p.file === after.file);
          if (picture) openViewer(nextSet.id, picture.position); else closeViewer();
        } else closeViewer();
      }
      renderImageSets();
    } else {
      lastVideos[original.folder] = (lastVideos[original.folder] || []).filter(v => v.name !== name);
      if (viewing === original) {
        if (after && after.film) openFilm(after.film, original.folder);
        else if (after && after.set) {
          const nextSet = findSet(after.set), picture = nextSet && nextSet.images.find(p => p.file === after.file);
          if (picture) openViewer(nextSet.id, picture.position); else closeViewer();
        } else closeViewer();
      }
    }
    poll();
  } finally {
    $('viewerDelete').disabled = false;
    $('viewerDelete').classList.remove('deleting');
    $('viewerDelete').setAttribute('aria-busy', 'false');
  }
});
$('imageSets').addEventListener('click', async e => {
  if (outputArranging) {
    e.preventDefault();
    const cell = e.target.closest && e.target.closest('[data-output-key]');
    if (cell && !gridDragged && !outputOrderSaving) outputSelected = outputSelected === cell.dataset.outputKey ? null : cell.dataset.outputKey;
    showOutputArranging();
    return;
  }
  if (e.target.closest && e.target.closest('.film')) return onFilmClick(e);
  const view = e.target.closest && e.target.closest('[data-view-set]');
  if (view) {
    e.preventDefault();
    // Choosing one of your images for a box: this one goes in it, and Generate shows again.
    openViewer(view.dataset.viewSet, +view.dataset.viewPosition);
    return;
  }
  // A set of more than one: its cover opens them all, small.
  const grid = e.target.closest && e.target.closest('[data-grid-set]');
  if (grid) {
    e.preventDefault();
    openThumbGrid({ set: grid.dataset.gridSet });
    return;
  }
  const d = e.target.dataset || {};
  if (d.againSet) {
    await sameAgain(d.againSet);
  } else if (d.downloadSet) {
    const set = imageSets.find(s => s.id === d.downloadSet);
    if (set) downloadImages(set.id, set.images.map(p => p.position));
  } else if (d.nsfwImage) await tagOutput('image', d.nsfwImage, !nsfwView, e.target);
  else if (d.shots) openShots(d.shots);
  else if (d.deleteSet) {
    if (e.target.classList.contains('deleting') || !secondTap(e.target)) return;
    await confirmedDelete(e.target, `/image-runs/${encodeURIComponent(d.deleteSet)}/delete`);
  }
});


// preload="none": a browser allows about 6 connections per site, and films loading
// their metadata can hold them all, which freezes the status poll.
// A film or a Short: a row as an image set's, its poster opening the player. A Short ready to go has Upload first.
function filmHtml(v, filmFolder = folder) {
  const name = esc(v.name), url = encodeURIComponent(v.name);
  const icon = (data, label, svg, extra = '') => `<button type="button" class="icon-btn${extra}" ${data} data-film-folder="${filmFolder}" title="${label}" aria-label="${label}">${svg}</button>`;
  const actions = '<div class="image-set-actions">'
    + (filmFolder === 'output' ? icon(`data-up="${name}" data-topic="${esc(v.topic || '')}"`, 'Upload to YouTube', ICONS.upload) : '')
    + (v.run ? icon(`data-again-film="${esc(v.run)}"`, 'The same again: its settings in Generate, to change first', ICONS.config) : '')
    + (v.run ? icon(`data-shots="${esc(v.run)}"`, 'Shots', ICONS.enhanced) : '')
    + icon(`data-del="${name}"`, 'Delete', ICONS.trash, ' del') + '</div>';
  return `
  <div class="image-set film" data-name="${name}">
    <div class="image-set-heading"><h3>${v.title || v.topic ? esc(v.title || v.topic) : filmFolder === 'video' ? name : '<span style="color:var(--muted)">No topic recorded</span>'}</h3>${filmFolder === 'video' ? nsfwButton('video', v.name, !!v.nsfw) : ''}</div>
    <div class="meta" title="${name}">${[madeOn(filmMadeAt(v)), !v.pills && v.model && esc(v.model), v.resolution && esc(v.resolution), v.duration != null && fmt(Math.round(v.duration)), v.size_mb != null && `${v.size_mb} MB`].filter(Boolean).join(' · ')}</div>${v.pills ? '' : `${connectionLine(v)}${lorasLine(v.loras)}${h3Line(v)}${upscaledLine(v)}`}
    <div class="image-set-row album">
      <a href="/videos/${filmFolder}/${url}" class="album-cover film-cover" data-play-film="${name}" data-film-folder="${filmFolder}" title="Play"><img loading="lazy" alt="" src="${v.run && filmFolder === 'video' ? `/runs/${encodeURIComponent(v.run)}/image` : `/posters/${filmFolder}/${url}`}" data-fallback-src="/posters/${filmFolder}/${url}"><span class="play">▶</span></a>
      <div class="album-side">${v.pills ? pillsLine(v.pills, 'video', 3) : ''}${actions}</div>
    </div>
  </div>`;
}
