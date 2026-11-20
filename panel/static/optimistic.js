// --- Changes shown at once: a delete, a move in the queue ---
// The page shows what was asked for straight away, from the status it has (localChanges), and sends it. The status
// keeps showing it so until the panel's own says the same, so an update that was on its way can't bring it back for a
// moment. Refused or unanswered, it goes back as it was, and a banner at the top says so; nothing moves you back to it.

const reducedMotion = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

// The banner at the top that says an action failed. It goes by itself, or with a tap.
const ACTION_NOTICE_MS = 6000;
let actionNoticeTimer = null;
function actionFailed(message) {
  const notice = $('actionNotice');
  $('actionMessage').textContent = message || 'That could not be done.';
  notice.hidden = false;
  clearTimeout(actionNoticeTimer);
  actionNoticeTimer = setTimeout(() => { notice.hidden = true; }, ACTION_NOTICE_MS);
}
$('actionDismiss').addEventListener('click', () => { clearTimeout(actionNoticeTimer); $('actionNotice').hidden = true; });

const localChanges = (() => {
  // A status that doesn't show a change yet, though asked for after the panel took it, is kept from undoing it this
  // long (some other change in between, say); and none is kept longer than SETTLE_MS after the panel took it.
  const LANDED_GRACE_MS = 3000, SETTLE_MS = 15000;
  const changes = new Set();
  let raw = null;
  // The status the page has, drawn again with the changes as they are now. No edit is ended by it: a job taken out here
  // that the panel then keeps is still being edited (removeQueued ends it once the panel has taken it).
  function redraw() {
    if (raw) applyStatus({ ...raw, local: true }, -Infinity, null, null);
  }
  return {
    // The status as the page shows it: the panel's, with what it hasn't caught up with yet.
    view(data, askedAt) {
      if (!data.local) raw = data;
      const now = performance.now();
      for (const change of changes) {
        if (change.settled === null || data.local) continue;  // Not answered yet: shown, whatever the status says
        const after = askedAt >= change.settled;
        if ((after && (!change.landed || change.landed(data))) || askedAt >= change.settled + LANDED_GRACE_MS
            || now - change.settled > SETTLE_MS) changes.delete(change);
      }
      for (const change of changes) data = change.apply(data);
      return data;
    },
    // apply(status) → the status with the change (a copy: the status itself is drawn again later). landed(status):
    // whether the panel's own status shows it. request() → the panel's answer ({ ok, error }). failed: what the
    // banner says when it doesn't happen. fade: what is going, faded out first. Resolves to the answer; one with
    // `queued` (a set still in the queue) goes back without a banner, for the caller to ask about.
    async make({ apply, landed = null, request, failed = 'That could not be done', fade = null }) {
      // With nothing to fade it is shown at once, before this returns: the viewer goes on from the set without it.
      const faded = fade ? await fadeOut(fade) : () => {};
      const change = { apply, landed, settled: null };
      changes.add(change);
      redraw();
      let body;
      try { body = await request(); } catch (e) { body = { ok: false, error: 'Could not reach the panel.' }; }
      if (!body || !body.ok) {
        changes.delete(change);
        faded();  // Not drawn again in the meantime (a list held while dragging, say), it shows again as it was
        redraw();
        if (!(body && body.queued)) actionFailed(`${failed}. ${(body && body.error) || 'Try again.'}`);
        return body || null;
      }
      change.settled = performance.now();
      if (body.warning) actionFailed(body.warning);
      poll();
      return body;
    },
    redraw,
    get size() { return changes.size; },
  };
})();

// A POST answered with JSON; an answer that isn't JSON says only whether it went through.
async function postJson(url, send = null) {
  const response = await fetch(url, send ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(send) }
    : { method: 'POST' });
  const body = await response.json().catch(() => ({ ok: response.ok !== false }));
  return response.ok === false ? { ...body, ok: false } : body;
}

// What is going fades out first; the rest then closes up behind it (flipList). Resolves to what shows it again.
async function fadeOut(el) {
  if (!el || !el.animate || reducedMotion() || !(el.getClientRects && el.getClientRects().length)) return () => {};
  const animation = el.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'scale(.96)' }],
    { duration: 180, easing: 'ease-in', fill: 'forwards' });
  el.style.pointerEvents = 'none';
  try { await animation.finished; } catch (e) {}
  return () => { animation.cancel(); el.style.pointerEvents = ''; };
}

// Draws a list again (render) and lets what is still in it glide from where it was to where it is now (FLIP): one
// gone, the rest move up into its place; one back, it fades in. keyOf: what an item is, through the redraw.
function flipList(container, selector, keyOf, render) {
  const moving = container && container.getClientRects && container.getClientRects().length && !reducedMotion();
  if (!moving) { render(); return; }
  const before = new Map();
  for (const el of container.querySelectorAll(selector)) {
    const key = keyOf(el);
    if (key) before.set(key, el.getBoundingClientRect());
  }
  render();
  if (!before.size) return;
  const height = window.innerHeight || 800, appeared = [];
  for (const el of container.querySelectorAll(selector)) {
    if (!el.animate) continue;
    const key = keyOf(el), was = before.get(key), now = el.getBoundingClientRect();
    if (now.bottom < -height || now.top > 2 * height) continue;  // Out of sight: nothing to see move
    if (!was) { appeared.push(el); continue; }
    const dx = was.left - now.left, dy = was.top - now.top;
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue;
    el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: 280, easing: 'cubic-bezier(.2,.8,.2,1)' });
  }
  // A few new ones fade in (one back after a failed delete, one just made); a whole new list (another filter) doesn't.
  if (appeared.length <= 3) {
    for (const el of appeared) el.animate([{ opacity: 0, transform: 'scale(.97)' }, { opacity: 1, transform: 'none' }], { duration: 220, easing: 'ease-out' });
  }
}

// --- The changes themselves: each makes a copy of the status with it ---
const withoutImageSet = (data, id) => ({ ...data, image_sets: (data.image_sets || []).filter(set => set.id !== id) });
// An image goes from its set (found by its file: the set isn't renumbered until the panel has it); a set left empty goes.
function withoutImageFiles(data, gone) {
  const files = new Map();
  for (const { set, file } of gone) (files.get(set) || files.set(set, new Set()).get(set)).add(file);
  return { ...data, image_sets: (data.image_sets || []).flatMap(set => {
    if (!files.has(set.id)) return [set];
    const images = set.images.filter(p => !files.get(set.id).has(p.file));
    return images.length || set.generating ? [{ ...set, images }] : [];
  }) };
}
const withoutFilm = (data, filmFolder, name) => ({ ...data,
  videos: { ...data.videos, [filmFolder]: ((data.videos || {})[filmFolder] || []).filter(v => v.name !== name) } });
const hasImage = (data, id, file) => (data.image_sets || []).some(set => set.id === id && set.images.some(p => p.file === file));
const hasFilm = (data, filmFolder, name) => ((data.videos || {})[filmFolder] || []).some(v => v.name === name);
// An image ({ kind: 'image', run, file }) or film ({ kind: 'film', name }) as a collection lists it, and finding it there.
const collectionEntry = item => item.kind === 'image' ? { kind: 'image', set: item.run, file: item.file } : { kind: 'film', name: item.name };
const isEntry = item => entry => item.kind === 'image'
  ? entry.kind === 'image' && entry.set === item.run && entry.file === item.file
  : entry.kind === 'film' && entry.name === item.name;
// Moved into a collection: out of where it was (its set's list or Videos, or another collection), in at the end of that
// one. target: { id, name }; a new one shows under its name until the panel has made it. NSFW if what went in is.
function withMovedToCollection(data, item, target) {
  let nsfw = false;
  const image_sets = (data.image_sets || []).map(set => {
    if (item.kind !== 'image' || set.id !== item.run) return set;
    nsfw = !!set.nsfw;
    return { ...set, images: set.images.map(p => p.file === item.file ? { ...p, collection: target.id } : p) };
  });
  const video = ((data.videos || {}).video || []).map(v => {
    if (item.kind !== 'film' || v.name !== item.name) return v;
    nsfw = !!v.nsfw;
    return { ...v, collection: target.id };
  });
  const there = isEntry(item);
  const collections = (data.collections || []).map(c => ({ ...c, items: c.items.filter(entry => !there(entry)) }));
  const home = collections.find(c => c.id === target.id);
  if (home) Object.assign(home, { items: [...home.items, collectionEntry(item)], nsfw: home.nsfw || nsfw });
  else collections.push({ id: target.id, name: target.name, nsfw, items: [collectionEntry(item)], folded: false, cover: null });
  return { ...data, image_sets, videos: { ...data.videos, video }, collections };
}
// The run queue's jobs (waiting and pending), or the upload queue's.
const laneQueue = (data, lane) => lane === 'run' ? data.queue : data.upload.queue;
function withLane(data, lane, items) {
  if (lane === 'run') return { ...data, queue: { ...data.queue, items } };
  return { ...data, upload: { ...data.upload, queue: { ...data.upload.queue, items } } };
}
const inLane = (data, lane, id) => laneQueue(data, lane).items.some(item => String(item.id) === String(id));
const withoutJob = (data, lane, id) => withLane(data, lane, laneQueue(data, lane).items.filter(item => String(item.id) !== String(id)));
// A job pending (later) or back in the queue; to the queue's front (top) or its end.
function withJobMoved(data, id, { later, top = false }) {
  const items = data.queue.items, job = items.find(item => String(item.id) === String(id));
  if (!job) return data;
  const moved = { ...job, later }, rest = items.filter(item => item !== job);
  if (later) return withLane(data, 'run', items.map(item => item === job ? moved : item));
  return withLane(data, 'run', top ? [moved, ...rest] : [...rest, moved]);
}
// The waiting jobs in this order (ids), the pending ones where they were.
function withQueueOrder(data, lane, ids) {
  const rank = new Map(ids.map((id, i) => [String(id), i]));
  const items = laneQueue(data, lane).items, ordered = (item => !item.later && rank.has(String(item.id)));
  const sorted = items.filter(ordered).sort((a, b) => rank.get(String(a.id)) - rank.get(String(b.id)));
  let next = 0;
  return withLane(data, lane, items.map(item => ordered(item) ? sorted[next++] : item));
}
function queueOrderIs(data, lane, ids) {
  const present = laneQueue(data, lane).items.filter(item => !item.later).map(item => String(item.id));
  const wanted = ids.map(String).filter(id => present.includes(id));
  return present.filter(id => wanted.includes(id)).join() === wanted.join();
}
