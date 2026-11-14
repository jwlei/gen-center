// --- Queues ---
const RESULT_MARKS = { done: '✔', failed: '✖ failed', stopped: '■ stopped', skipped: '– skipped' };
const LEAVE_MS = 380;
// A title in the queues, cut to two lines. position: its place in the queue, said quietly before the title.
function queueTitle(key, text, position = null) {
  return `<span class="queue-title" data-title-key="${esc(key)}">`
    + `${position != null ? `<span class="queue-pos">${position}.</span> ` : ''}${esc(text)}</span>`;
}
function renderQueue(el, q, doneIn, moving = false, idle = false) {
  // What has finished is under Finished: this is what's waiting. The one moving to start has left it already.
  el._last = [q, doneIn, moving, idle];
  if (el._leaving || el._dragging || el._ordering) return;
  if (el.querySelectorAll('.queue-request, .queue-request-done').length) return;
  const waiting = moving ? q.items.slice(1) : q.items;
  if (waiting.length < 2 || !waiting.some(item => String(item.id) === el._selected)) el._selected = null;
  // What left since: it slides up out of the queue, towards Status, and the rest close up behind it.
  const gone = [...el.querySelectorAll('.queue-item[data-id]:not(.leaving)')].filter(node => !waiting.some(item => String(item.id) === node.dataset.id));
  if (el.dataset.lane !== 'run' && gone.length && !el.hidden) {
    el._leaving = true;
    for (const node of gone) {
      node.style.height = `${node.offsetHeight}px`;
      node.classList.add('leaving');
    }
    setTimeout(() => { el._leaving = false; renderQueue(el, ...el._last); }, LEAVE_MS);
    return;
  }
  const runControls = el.dataset.lane === 'run' && q.running && q.pipeline !== 'video';
  el.hidden = !waiting.length && !runControls;
  if (el.hidden) {
    // Not what left, which would otherwise stay in it, hidden, and keep its head and Resume.
    el.innerHTML = '';
    el.dataset.html = '';
    return;
  }
  const heading = `<b>${el.dataset.title} (${waiting.length})</b>`;
  const expanded = el._open !== false;
  const head = (el.dataset.lane === 'run' ? `<button type="button" class="queue-fold-toggle queue-fold-title" data-fold-queue="1" aria-expanded="${expanded}">${heading}</button>` : heading) + (q.held
    ? `<span class="when">On hold</span>`
    : doneIn ? `<span class="when">All done around ${clockIn(doneIn)}</span>` : '')
    + (el.dataset.lane === 'run' ? `<button type="button" class="icon-btn" data-queue-toggle="1" aria-label="${q.held || q.stopAfter ? 'Resume queue' : 'Pause after current'}" title="${q.held || q.stopAfter ? 'Resume queue' : 'Stop after the current image or video'}">${q.held || q.stopAfter ? ICONS.play : '❚❚'}</button>`
      + `<button type="button" class="icon-btn" data-sort-queue aria-label="Sort by shortest ETA" title="Sort by shortest ETA"${waiting.length < 2 ? ' disabled' : ''}><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 5h14M4 10h10M4 15h6M19 10v10m-3-3 3 3 3-3"/></svg></button>`
      + `<button type="button" class="queue-fold-toggle queue-fold-arrow" data-fold-queue="1" aria-expanded="${expanded}" aria-label="${expanded ? 'Collapse queue' : 'Expand queue'}"><span class="chev" aria-hidden="true"></span></button>` : '');
  const canRunNow = el.dataset.lane === 'run' && idle;
  const items = waiting.map((item, i) => `
    <div class="queue-item${el.dataset.lane === 'run' ? ' run-card' : ''}${String(item.id) === el._selected ? ' selected' : ''}" data-id="${esc(String(item.id))}" data-motion-key="queue-${esc(String(item.id))}">
      ${el.dataset.lane === 'run' ? workPrivacy(item, 'job', item.id) : ''}
      ${el.dataset.lane === 'run' ? '<div class="queue-item-top">' : ''}<div class="what"${waiting.length > 1 ? ` role="button" tabindex="0" aria-pressed="${String(item.id) === el._selected}" aria-label="Select ${esc(hideTitle(item) ? PLAIN_TITLE : item.label)} to drag or use arrow keys to reorder"` : ''}>${queueTitle(`queue-${item.id}`, el.dataset.lane === 'run' ? workHeading(item, item.pipeline) : item.label, i + 1)}<div class="hint">${el.dataset.lane === 'run' ? `${SIDE_NAMES[item.pipeline] || 'Shorts'} · ` : ''}${esc(queueDetail(item))}</div></div>${el.dataset.lane === 'run' ? '</div><div class="queue-item-actions">' : ''}
      ${el.dataset.lane === 'run' ? `<span class="acts-side"><button type="button" class="icon-btn" data-pause="${item.id}" aria-label="Pause: move to Pending" title="Pause: take it out of the queue and make it pending">${ICONS.later}</button>`
        // Nothing running: any of them can start first. Running: the first is next already, and the others can go ahead of the rest.
        + (canRunNow ? `<button type="button" class="run-item${item.continuation ? ' continue-item' : ''}" data-run="${item.id}" aria-label="Run this generation now" title="Run this now">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.8a.8.8 0 0 1 1.2-.7l8 5a1 1 0 0 1 0 1.7l-8 5A.8.8 0 0 1 4 13.1z" fill="currentColor"/></svg></button>`
          : i > 0 ? `<button type="button" class="icon-btn${item.continuation ? ' continue-item' : ''}" data-top="${item.id}" aria-label="Move to the top of the queue" title="Next: put it first in the queue">${ICONS.top}</button>` : '')
        + `</span><span class="when">${item.estimate ? fmtEta(item.estimate) : ''}</span><span class="acts-side acts-end">`
        + (item.resume && item.pipeline !== 'shorts' ? `<button type="button" class="icon-btn" data-shots="${esc(item.resume)}" aria-label="Prompts" title="View prompts">${ICONS.enhanced}</button>` : '')
        + `<button type="button" class="icon-btn" data-edit="${item.id}" aria-label="Go to setup" title="Edit this queued job">${ICONS.config}</button>`
        + `<button type="button" class="icon-btn" data-remove="${item.id}" aria-label="Remove from the queue" title="Remove from the queue (tap twice)">${ICONS.trash}</button></span>`
        : `${item.estimate ? `<span class="when">${fmtEta(item.estimate)}</span>` : ''}<button type="button" data-remove="${item.id}" aria-label="Remove from the queue" title="Remove from the queue (tap twice)">✕</button>`}
      ${el.dataset.lane === 'run' ? '</div>' : ''}
    </div>`).join('');
  // Resume under what it lets go, where a thumb ends up after reading the list.
  const foot = q.held && el.dataset.lane !== 'run' ? `<div class="queue-foot"><button type="button" data-resume="1">Resume</button></div>` : '';
  const html = `<div class="queue-head${el.dataset.lane === 'run' ? ' run-queue-head' : ''}">${head}</div>` + (el.dataset.lane === 'run'
    ? `<div class="queue-list" tabindex="0"${el._open === false ? ' hidden' : ''}>${items}</div>` : items) + foot;
  // Only when it changed, so a poll can't swallow a click on a button it just replaced; nor one waiting for its second tap.
  if (el.dataset.html !== html && !el.querySelectorAll('.armed, .queue-request, .queue-request-done').length) {
    const scroll = el.dataset.lane === 'run' && el.querySelector('.queue-list');
    const top = scroll ? scroll.scrollTop : 0;
    el.innerHTML = html;
    el.dataset.html = html;
    if (el.dataset.lane === 'run') setupQueueScroll(el, '.queue-list', '.queue-item', top);
  }
}
function setupQueueScroll(section, selector, rowSelector, top = 0) {
  if (section._scrollObserver) section._scrollObserver.disconnect();
  if (section._scrollFrame != null) cancelAnimationFrame(section._scrollFrame);
  section._scrollFrame = null;
  const list = section.querySelector(selector);
  if (!list) return;
  list.scrollTop = top;
  const rows = [...list.querySelectorAll(rowSelector)];
  let measured = null;
  const measure = () => {
    const first = rows.slice(0, 3);
    if (!first.length || !first[0].getClientRects().length) return;
    const end = first[first.length - 1];
    const height = `${end.offsetTop + end.offsetHeight}px`;
    if (height !== measured) {
      measured = height;
      list.style.setProperty('--three-rows', height);
    }
  };
  measure();
  if (window.ResizeObserver) {
    section._scrollObserver = new window.ResizeObserver(() => {
      if (section._scrollFrame != null) return;
      section._scrollFrame = requestAnimationFrame(() => { section._scrollFrame = null; measure(); });
    });
    for (const row of rows.slice(0, 3)) section._scrollObserver.observe(row);
  }
}
// Every run and upload that has ended, in one list, newest first.
const FINISHED_SHOWN = 20;  // The last twenty, kept over a restart until Clear
function queueDetail(item) {
  const detail = (item.detail || '').split(' · ').filter(part => part !== 'renders straight away' && part !== 'renders at once');
  const size = item.facts && item.facts.resolution;
  if (size && !detail.includes(size)) detail.push(size);
  return detail.join(' · ');
}
// Kept over a restart, so one from another day says which.
function finishedWhen(r) {
  if (!r.t) return r.at || '';
  const date = new Date(r.t * 1000);
  return date.toDateString() === new Date().toDateString() ? r.at || ''
    : `${date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${r.at || ''}`;
}
// Results swiped away, until the server's list no longer has them: a poll in between must not bring one back.
const forgottenResults = new Set();
function resultKey(r) {
  return r.job_id != null ? `${r.lane}:${r.job_id}` : `made:${r.run_id}:${r.position}`;
}
// What a result made, as a small picture: an image (or its set's first), a film's start image or poster.
function finishedThumb(r) {
  let src = '';
  if (r.lane === 'run' && r.side === 'image' && r.run_id) {
    const set = imageSets.find(s => s.id === r.run_id);
    const picture = set && (set.images.find(p => p.position === r.position) || set.images[0]);
    const position = picture ? picture.position : r.position;
    if (position) src = `/image-runs/${encodeURIComponent(r.run_id)}/thumbnails/${position}${picture ? `?v=${picture.version}` : ''}`;
  } else if (r.lane === 'run' && r.side === 'video' && (r.run_id || r.film)) {
    src = r.run_id ? `/runs/${encodeURIComponent(r.run_id)}/image` : `/posters/video/${encodeURIComponent(r.film)}`;
  } else if (r.lane === 'run' && r.side === 'shorts' && r.film) {
    src = `/posters/output/${encodeURIComponent(r.film)}`;
  }
  return `<span class="result-thumb">${src ? `<img loading="lazy" alt="" src="${esc(src)}" data-remove-on-error>` : ''}</span>`;
}
let finishedSwiping = false;
let lastFinished = null;
// Batches opened in Finished, kept open through the polls until folded.
const openBatches = new Set();
// One row per batch: the whole job once it has ended (or the newest thing it made while it runs), and as its items,
// each picture of its set once it is done (what was made one by one is no longer listed then), else what it has made
// so far. Anything else is a row of its own.
function finishedBatches(all) {
  const batches = [], byRun = new Map();
  for (const r of all) {
    const key = r.lane === 'run' && r.run_id && (r.side === 'image' || r.side === 'video') ? `${r.side}:${r.run_id}` : null;
    if (!key) { batches.push({ main: r, kids: [] }); continue; }
    let batch = byRun.get(key);
    if (!batch) { batch = { key, main: null, made: [] }; byRun.set(key, batch); batches.push(batch); }
    if (r.job_id != null && !batch.main) batch.main = r; else batch.made.push(r);
  }
  for (const batch of byRun.values()) {
    if (batch.main) {
      const set = batch.main.side === 'image' && imageSets.find(s => s.id === batch.main.run_id);
      batch.kids = set && set.images.length > 1
        ? set.images.map(p => ({ ...batch.main, job_id: undefined, outcome: 'done', position: p.position, label: p.title || `Image ${p.position}`, note: '' }))
        : batch.made;
    } else {
      // Still going: the newest it made heads the batch, and all of them, that one too, are its items.
      batch.main = batch.made[0];
      batch.kids = batch.made;
    }
    // One thing alone is no batch: its row opens it.
    if (batch.kids.length < 2) batch.kids = [];
  }
  return batches;
}
function renderFinished(runs, uploads, madeNow = []) {
  lastFinished = [runs, uploads, madeNow];
  if (finishedSwiping) return;  // Redrawn mid-swipe, the row under the finger would vanish
  // Whole jobs, and what the one going now has made so far, such as each image of a set. NSFW only under its filter.
  const all = [...runs, ...madeNow].filter(r => !r.nsfw || nsfwView).map(r => ({ ...r, type: SIDE_NAMES[r.pipeline] || 'Shorts', side: r.pipeline || 'shorts', lane: 'run' }))
    .concat(uploads.map(r => ({ ...r, type: 'Upload', side: 'shorts', lane: 'upload', tab: r.outcome === 'done' ? 'uploaded' : 'output' })))
    .filter(r => !forgottenResults.has(resultKey(r)))
    .sort((a, b) => (b.t || 0) - (a.t || 0) || (b.at || '').localeCompare(a.at || ''));
  const batches = finishedBatches(all).slice(0, FINISHED_SHOWN);
  $('finishedToggle').disabled = !all.length;
  $('finishedToggle').classList.toggle('empty', !all.length);
  const failed = all.filter(r => r.outcome === 'failed').length;
  $('finishedToggle').classList.toggle('failed', failed > 0);
  const title = all.length ? `Finished (${all.length})${failed ? ` · ${failed} failed` : ''}` : 'Finished';
  $('finishedToggle').setAttribute('aria-label', title);
  $('finishedToggle').title = title;
  $('finishedLabel').innerHTML = all.length ? `Finished (${all.length})${failed ? ` · <span class="failed">${failed} failed</span>` : ''}` : 'Finished';
  $('finishedCount').textContent = all.length ? String(all.length) : '';
  $('finishedCount').classList.toggle('failed', failed > 0);
  $('finishedFoot').hidden = !all.length;
  if (!all.length) {
    $('finishedList').innerHTML = '';
    $('finishedList').dataset.html = '';
    return;
  }
  const row = (r, kind = '', count = 0) => `<button type="button" class="result ${esc(r.outcome)}${kind}" style="--side:${SIDE_COLOURS[r.side] || SIDE_COLOURS.shorts}" data-goto="${esc(r.side)}"${r.tab ? ` data-tab="${r.tab}"` : ''}${r.run_id ? ` data-run-id="${esc(r.run_id)}"` : ''}${r.job_id != null ? ` data-job-id="${esc(String(r.job_id))}"` : ''}${r.position ? ` data-position="${r.position}"` : ''}${r.film ? ` data-film="${esc(r.film)}"` : ''}${r.outcome === 'failed' && r.type !== 'Upload' ? ' data-failed="1"' : ''} data-lane="${r.lane}" data-key="${esc(resultKey(r))}">`
    + finishedThumb(r) + `<span class="result-mark">${RESULT_MARKS[r.outcome]}</span>${kind === ' batch-kid' ? '' : `<span class="result-type">${r.type}</span>`}`
    + `<span class="result-label">${esc(r.label)}${r.note ? ` (${esc(r.note)})` : ''}</span>${count ? `<span class="batch-count">${count}</span><span class="batch-chevron" aria-hidden="true">›</span>` : ''}<span class="when">${finishedWhen(r)}</span></button>`;
  // A batch: its main row, and under it, a tap away, each thing it made, set in a little.
  const list = batches.map(b => !b.kids.length ? row(b.main)
    : `<div class="result-batch${openBatches.has(b.key) ? ' open' : ''}" data-batch="${esc(b.key)}">${row(b.main, ' batch-main', b.kids.length)}`
      + `<div class="batch-kids"><div class="batch-kids-in">${b.kids.map(k => row(k, ' batch-kid')).join('')}</div></div></div>`).join('');
  if ($('finishedList').dataset.html !== list) { $('finishedList').innerHTML = list; $('finishedList').dataset.html = list; }
}
// --- Finished, Log and Quota: each opens in a box over the page ---
// The box borrows what it shows from the page and gives it back on Close, so it keeps updating as it is.
const PANELS = { finished: ['Finished', 'finishedList'], log: ['Log', 'logPanes'], quota: ['Quota today', 'quotaCard'] };
let panelShown = null;
function openPanel(which) {
  if (DESK.matches) { setRunTab(which); return; }
  closePanel();
  const [title, id] = PANELS[which], el = $(id);
  panelShown = { which, el, parent: el.parentNode, next: el.nextSibling };
  $('panelDialogTitle').textContent = title;
  $('panelDialog').classList.toggle('log-open', which === 'log');
  $('panelDialogBody').appendChild(el);
  // Finished's Clear: outside the scrolling list, just above Close.
  if (which === 'finished') {
    const foot = $('finishedFoot');
    panelShown.foot = { parent: foot.parentNode, next: foot.nextSibling };
    $('panelDialog').insertBefore(foot, $('panelDialogClose'));
  }
  if (!$('panelDialog').open) $('panelDialog').showModal();
  if (which === 'log') for (const log of ['log', 'uploadLog']) $(log).scrollTop = $(log).scrollHeight;
}
function closePanel() {
  if (!panelShown) return;
  const { el, parent, next, foot } = panelShown;
  // The foot first: it is what the list goes back in front of.
  if (foot) foot.parent.insertBefore($('finishedFoot'), foot.next);
  parent.insertBefore(el, next);
  panelShown = null;
  if ($('panelDialog').open) $('panelDialog').close();
}
$('finishedToggle').addEventListener('click', () => openPanel('finished'));
const DESK = window.matchMedia('(min-width: 1280px)');
let lastStatus = null;
function placePanelControls() {
  if (DESK.matches) {
    for (const id of ['logToggle', 'finishedToggle', 'quotaToggle']) $('statusToggles').appendChild($(id));
  } else {
    // The header: Finished, privacy, the log, then the gear.
    $('topIcons').insertBefore($('finishedToggle'), $('privateToggle'));
    $('topIcons').insertBefore($('logToggle'), $('settingsBtn'));
    $('settingsHead').appendChild($('quotaToggle'));
  }
  const running = !!(lastStatus && lastStatus.running);
  $('runActions').hidden = DESK.matches && !running;
  $('skip').hidden = $('stop').hidden = !running;
}
DESK.addEventListener('change', placePanelControls);
function setRunTab(which) {
  document.body.dataset.runtab = which;
  for (const [id, tab] of [['queueToggle', 'queue'], ['logToggle', 'log'], ['finishedToggle', 'finished'], ['quotaToggle', 'quota']]) {
    $(id).classList.toggle('on', tab === which);
    $(id).setAttribute('aria-pressed', String(tab === which));
  }
  if (which === 'log') for (const log of ['log', 'uploadLog']) $(log).scrollTop = $(log).scrollHeight;
}
function placeQuota() {
  if (panelShown && panelShown.which === 'quota') return;
  const home = document.querySelector ? document.querySelector('.side') : null, to = DESK.matches ? $('runQuota') : home;
  if (!to) return;
  if ($('quotaCard').parentNode !== to) to.appendChild($('quotaCard'));
  if (DESK.matches && !document.body.dataset.runtab) setRunTab('queue');
}
DESK.addEventListener('change', placeQuota);
$('queueToggle').addEventListener('click', () => setRunTab('queue'));
placePanelControls();
placeQuota();
$('logToggle').addEventListener('click', () => openPanel('log'));
$('quotaToggle').addEventListener('click', () => openPanel('quota'));
$('panelDialogClose').addEventListener('click', closePanel);
$('panelDialog').addEventListener('close', closePanel);
// A tap on the blurred page around it closes it too.
$('panelDialog').addEventListener('click', e => { if (e.target === $('panelDialog')) closePanel(); });
// A result takes you to what it made: its side's output.
function goToOutput(side, tab) {
  closePanel();
  // Shorts' own, or the kind it is (Both already has it). The view stays: Finished lists NSFW only in the NSFW view.
  const view = nsfwView;
  if (side === 'shorts' || pipeline === 'shorts') { if (side !== pipeline) setPipeline(side); }
  if (tab && side === 'shorts') setTab(tab);
  if (['image', 'video'].includes(side) && outputKind !== 'both') outputKind = side;
  if (WIDE.matches) $('videosCard').scrollIntoView({ behavior: 'smooth' }); else showPage('output');
  nsfwView = view && pipeline !== 'shorts';
  redrawFiltered();
}
// Swiping a result to the right takes it off Finished; a short or mostly vertical drag is a tap or a scroll.
let finishedSwipe = null, finishedSwiped = false;
$('finishedList').addEventListener('pointerdown', e => {
  const row = e.target.closest && e.target.closest('.result');
  if (!row || (e.pointerType === 'mouse' && e.button !== 0)) return;
  finishedSwipe = { row, id: e.pointerId, x: e.clientX, y: e.clientY, dx: 0, dragging: false };
});
$('finishedList').addEventListener('pointermove', e => {
  const s = finishedSwipe;
  if (!s || e.pointerId !== s.id) return;
  const dx = e.clientX - s.x, dy = e.clientY - s.y;
  if (!s.dragging) {
    if (Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) { finishedSwipe = null; return; }  // A scroll
    if (dx < 10 || dx < Math.abs(dy)) return;
    s.dragging = finishedSwiping = true;
    s.row.classList.remove('swipe-back');
    try { s.row.setPointerCapture(e.pointerId); } catch (error) {}
  }
  s.dx = Math.max(0, dx);
  s.row.style.transform = `translateX(${s.dx}px)`;
  s.row.style.opacity = String(Math.max(0.2, 1 - s.dx / (s.row.offsetWidth || 300)));
});
function endFinishedSwipe(e, cancelled = false) {
  const s = finishedSwipe;
  if (!s || e.pointerId !== s.id) return;
  finishedSwipe = null;
  if (!s.dragging) return;
  finishedSwiped = true;  // The click that follows the drag isn't a tap
  setTimeout(() => { finishedSwiped = false; }, 0);
  if (!cancelled && s.dx > (s.row.offsetWidth || 300) * 0.35) forgetResult(s.row);
  else {
    s.row.classList.add('swipe-back');
    s.row.style.transform = s.row.style.opacity = '';
    finishedSwiping = false;
  }
}
$('finishedList').addEventListener('pointerup', e => endFinishedSwipe(e));
$('finishedList').addEventListener('pointercancel', e => endFinishedSwipe(e, true));
// Clear: tapped once it asks; tapped again each result swipes out from the top, faster and faster, then the list empties.
const CLEAR_FIRST_GAP = 140, CLEAR_SPEEDUP = 0.75, CLEAR_LEAST_GAP = 20, CLEAR_SLIDE = 220;
function clearDelays(count) {
  const delays = [];
  for (let i = 0, at = 0, gap = CLEAR_FIRST_GAP; i < count; i++, at += gap, gap = Math.max(CLEAR_LEAST_GAP, gap * CLEAR_SPEEDUP)) delays.push(Math.round(at));
  return delays;
}
$('finishedClear').addEventListener('click', async () => {
  const button = $('finishedClear');
  if (button.disabled || !secondTap(button)) return;
  button.disabled = true;
  finishedSwiping = true;
  let cleared = false;
  const rows = [...$('finishedList').querySelectorAll('.result')];
  const selected = { run: [], upload: [] };
  for (const row of rows) {
    if (row.dataset.jobId != null) selected[row.dataset.lane].push(Number(row.dataset.jobId));
  }
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const delays = reduced ? rows.map(() => 0) : clearDelays(rows.length);
  rows.forEach((row, i) => setTimeout(() => {
    row.style.transitionTimingFunction = 'ease-in';
    row.classList.add('swiped');
  }, delays[i]));
  await new Promise(resolve => setTimeout(resolve, reduced ? 0 : (delays[delays.length - 1] || 0) + CLEAR_SLIDE));
  try {
    const response = await fetch('/queue/finished/clear', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selected) });
    const body = await response.json();
    if (!response.ok || !body.ok) throw new Error(body.error || 'Could not clear Finished.');
    for (const row of rows) forgottenResults.add(row.dataset.key);
    $('finishedList').innerHTML = '';
    cleared = true;
  } catch (error) {
    alert('Could not clear Finished. Check the connection and try again.');
  }
  $('finishedList').dataset.html = '';  // Drawn again from what the server has: nothing, or all of it back
  finishedSwiping = false;
  button.disabled = false;
  // Emptied, there is nothing left to look at: the box closes (on a desk, back to the queue).
  if (cleared) {
    if (panelShown && panelShown.which === 'finished') closePanel();
    else if (DESK.matches && document.body.dataset.runtab === 'finished') setRunTab('queue');
  }
  poll();
});
function forgetResult(row) {
  const d = row.dataset, reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let removed = false, accepted = d.jobId == null;
  const closeIfEmpty = () => {
    if (!removed || !accepted || $('finishedList').querySelector('.result')) return;
    if (panelShown && panelShown.which === 'finished') closePanel();
    else if (DESK.matches && document.body.dataset.runtab === 'finished') setRunTab('queue');
  };
  forgottenResults.add(d.key);
  // Slides out from where the finger left it, then its space closes up.
  row.style.height = `${row.offsetHeight}px`;
  row.classList.add('swiped');
  setTimeout(() => {
    row.classList.add('collapsing');
    setTimeout(() => {
      row.remove();
      removed = true;
      closeIfEmpty();
      finishedSwiping = false;
      $('finishedList').dataset.html = '';  // Drawn again from what is left at the next poll
      poll();
    }, reduced ? 0 : 200);
  }, reduced ? 0 : 220);
  // What the job going now made has no job yet: it is only hidden here, until that job ends.
  if (d.jobId == null) return;
  fetch(`/queue/${encodeURIComponent(d.lane)}/finished/${encodeURIComponent(d.jobId)}/forget`, { method: 'POST' })
    .then(response => { if (!response.ok) throw new Error(); accepted = true; closeIfEmpty(); })
    .catch(() => { forgottenResults.delete(d.key); alert('Could not remove it from Finished. Check the connection and try again.'); poll(); });
}
$('finishedList').addEventListener('click', async e => {
  if (finishedSwiped) { e.preventDefault(); e.stopPropagation(); return; }
  // A batch's main row opens and folds what it made; each of those opens itself.
  const main = e.target.closest && e.target.closest('.batch-main');
  if (main) {
    const batch = main.parentElement, open = !batch.classList.contains('open');
    batch.classList.toggle('open', open);
    if (open) openBatches.add(batch.dataset.batch); else openBatches.delete(batch.dataset.batch);
    $('finishedList').dataset.html = '';  // Drawn again, open or not, at the next poll
    return;
  }
  const result = e.target.closest && e.target.closest('[data-goto]');
  if (!result) return;
  const d = result.dataset;
  if (d.failed) {
    closePanel();
    if (DESK.matches) setRunTab('queue');
    if (!WIDE.matches) showPage('status');
    const section = $('failedRuns'), fold = section.querySelector('.stopped-fold');
    const row = [...section.querySelectorAll('.stopped-run')].find(item => d.runId ? item.dataset.runId === d.runId : item.dataset.jobId === d.jobId);
    if (!row || !fold) { alert('This failed run no longer has a saved entry under Failed.'); return; }
    fold.open = true;
    section._open = true;
    row.classList.add('highlight');
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => row.classList.remove('highlight'), 3000);
    return;
  }
  if (d.goto === 'image' && d.runId) {
    const set = imageSets.find(item => item.id === d.runId);
    const picture = set && (d.position ? set.images.find(item => item.position === +d.position) : set.images[0]);
    if (picture) { closePanel(); openViewer(d.runId, picture.position); return; }
  }
  if (d.film || (d.goto === 'video' && d.runId)) {
    const targetFolder = d.goto === 'video' ? 'video' : d.tab || 'output';
    const film = (lastVideos[targetFolder] || []).find(item => d.film ? item.name === d.film : item.run === d.runId);
    if (film) {
      goToOutput(d.goto, d.tab);
      openFilm(film.name, targetFolder);
      return;
    }
  }
  goToOutput(d.goto, d.tab);
});
function whyHtml(outcome) {
  return `<details class="why"><summary>Why</summary><div class="why-text">${esc(outcome.why)}</div></details>`;
}
// Draw all three sections together, so their height changes move the rest of the page gradually.
let runSectionsDrawn = false;
function renderRunSections(draw) {
  const sections = ['warningRuns', 'runQueue', 'stoppedRuns', 'failedRuns'].map(id => $(id));
  const motion = runSectionsDrawn && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    && $('queueBox').getClientRects().length;
  runSectionsDrawn = true;
  if (!motion) {
    for (const el of sections) {
      if (el._sectionAnimation) el._sectionAnimation.cancel();
    }
    draw();
    return;
  }

  const positions = new Map();
  const before = sections.map(el => {
    const ghost = el._exitGhost;
    const visible = ghost || (!el.hidden && el.getClientRects().length ? el : null);
    if (visible && !ghost) {
      for (const row of el.querySelectorAll('[data-motion-key]')) {
        if (row.getClientRects().length) positions.set(row.dataset.motionKey, { section: el, top: row.getBoundingClientRect().top });
      }
    }
    return { html: el.dataset.html, hidden: el.hidden, height: visible ? visible.getBoundingClientRect().height : 0,
             copy: visible ? visible.cloneNode(true) : null };
  });
  draw();

  sections.forEach((el, i) => {
    const old = before[i];
    if (old.html === el.dataset.html && old.hidden === el.hidden) return;
    if (el._sectionAnimation) el._sectionAnimation.cancel();
    if (el._exitGhost) { el._exitGhost.remove(); el._exitGhost = null; }
    const visible = !el.hidden && el.getClientRects().length;
    const height = visible ? el.getBoundingClientRect().height : 0;
    let target = visible ? el : null;
    if (!target && old.copy && old.height) {
      target = old.copy;
      target.removeAttribute('id');
      target.setAttribute('aria-hidden', 'true');
      target.inert = true;
      target.style.pointerEvents = 'none';
      el.parentNode.insertBefore(target, el);
      el._exitGhost = target;
    }
    if (target && Math.abs(old.height - height) > 0.5) {
      const animation = target.animate([
        { height: `${old.height}px`, marginTop: old.height ? '12px' : '0px', overflow: 'hidden', boxSizing: 'border-box' },
        { height: `${height}px`, marginTop: height ? '12px' : '0px', overflow: 'hidden', boxSizing: 'border-box' },
      ], { duration: 300, easing: 'cubic-bezier(.2,.8,.2,1)' });
      el._sectionAnimation = animation;
      const finish = () => {
        if (el._sectionAnimation === animation) el._sectionAnimation = null;
        if (el._exitGhost === target) { target.remove(); el._exitGhost = null; }
      };
      animation.onfinish = finish;
      animation.oncancel = finish;
    }
    if (!visible) return;
    for (const row of el.querySelectorAll('[data-motion-key]')) {
      if (!row.getClientRects().length) continue;
      const previous = positions.get(row.dataset.motionKey);
      const shift = previous ? previous.top - row.getBoundingClientRect().top : 0;
      if (!previous || previous.section !== el) {
        row.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, easing: 'ease-out' });
      } else if (Math.abs(shift) > 0.5) {
        row.animate([{ transform: `translateY(${shift}px)` }, { transform: 'none' }],
          { duration: 300, easing: 'cubic-bezier(.2,.8,.2,1)' });
      }
    }
  });
}
// canRunNow: the queue is on hold and nothing is running, so a pending job can be started on its own, at once.
function renderStopped(runs, parked = [], results = [], canRunNow = false, checkpointErrors = []) {
  const warned = runs.filter(run => run.prompt_warnings && run.prompt_warnings.length);
  const warnedParked = parked.filter(item => item.prompt_warnings && item.prompt_warnings.length);
  const failed = runs.filter(run => !warned.includes(run) && run.outcome && run.outcome.outcome === 'failed');
  const idle = runs.filter(run => !failed.includes(run) && !warned.includes(run));
  const warningText = item => item.prompt_warnings && item.prompt_warnings.length
    ? `<div class="hint prompt-warning">Check prompts (${item.prompt_warnings.map(w => `Items ${esc(String(w.items[0]))} and ${esc(String(w.items[1]))}`).join('; ')}). Starting approves this warning.</div>` : '';
  const tag = run => run.outcome ? `<span class="run-tag${run.outcome.outcome === 'stopped' ? ' stopped' : ''}">${esc(run.outcome.outcome === 'failed' ? 'Failed' : run.outcome.outcome === 'stopped' ? 'Stopped' : run.outcome.outcome)}</span>` : '';
  const runRow = (run, isFailed = false) => `
    <div class="stopped-run" data-run-id="${esc(run.id)}" data-motion-key="run-${esc(run.id)}">
      ${workPrivacy(run, run.pipeline, run.id)}
      <div class="run-head"><div class="what">${queueTitle(`run-${run.id}`, hideTitle(run) ? PLAIN_TITLE : run.label)}</div>${tag(run)}</div>
      <div class="hint">${SIDE_NAMES[run.pipeline] || 'Shorts'} · ${esc(run.detail)}${run.size && !String(run.detail).includes(run.size) ? ` · ${esc(run.size)}` : ''}</div>
      ${warningText(run)}
      ${run.when ? `<div class="hint">${esc(run.when)}</div>` : ''}
      ${run.outcome && run.outcome.why ? whyHtml(run.outcome) : ''}
      <div class="stopped-actions">
        <span class="acts-side">${isFailed ? `<button type="button" class="icon-btn" data-continue="${esc(run.id)}" aria-label="Retry" title="Retry from where it got to">${ICONS.again}</button>`
            + `<button type="button" class="icon-btn" data-continue-later="${esc(run.id)}" aria-label="Back to Pending" title="Back to Pending: it waits there until you start it">${ICONS.later}</button>`
          : `<button type="button" class="icon-btn start-item continue-item" data-continue-later="${esc(run.id)}" aria-label="Add to Pending" title="Add to Pending: it waits until you start it">${ICONS.queue}</button>`
            + `<button type="button" class="icon-btn start-item continue-item" data-continue-top="${esc(run.id)}" aria-label="Add to the top of the queue" title="Add to the top of the queue: ahead of everything waiting">${ICONS.top}</button>`}</span>
        <span class="when">${fmtEta(run.estimate)}</span>
        <span class="acts-side acts-end">${run.pipeline !== 'shorts' ? `<button type="button" class="icon-btn${run.prompt_warnings && run.prompt_warnings.length ? ' prompt-warning' : ''}" data-shots="${esc(run.id)}" aria-label="Prompts" title="View prompts">${ICONS.enhanced}</button>` : ''}<button type="button" class="icon-btn" data-config="${esc(run.id)}" data-pipeline="${esc(run.pipeline)}" aria-label="Change settings" title="Back to Generate with its settings, to change them">${ICONS.config}</button><button type="button" class="icon-btn" data-discard="${esc(run.id)}" data-pipeline="${esc(run.pipeline)}" data-clips="${run.clips}" aria-label="Discard this run" title="Discard what it has still to do: anything it made stays (tap twice)">${ICONS.trash}</button></span>
      </div>
    </div>`;
  // Waiting to be started: put there by Add to pending or Pause, and not in the queue until you start it.
  const parkedRow = item => `
    <div class="stopped-run" data-motion-key="queue-${esc(String(item.id))}">
      ${workPrivacy(item, 'job', item.id)}
      <div class="run-head"><div class="what">${queueTitle(`queue-${item.id}`, workHeading(item, item.pipeline))}</div></div>
      <div class="hint">${SIDE_NAMES[item.pipeline] || 'Shorts'} · ${esc(queueDetail(item))}</div>
      ${warningText(item)}
      <div class="stopped-actions">
        <span class="acts-side">${item.editing ? '<span class="when">Editing</span>' : `<button type="button" class="icon-btn start-item${item.continuation ? ' continue-item' : ''}" data-start="${item.id}" aria-label="Add to the queue" title="Add to the queue: it starts when the queue gets to it">${ICONS.queue}</button>`
          + `<button type="button" class="icon-btn start-item${item.continuation ? ' continue-item' : ''}" data-start="${item.id}" data-top="1" aria-label="Add to the top of the queue" title="Add to the top of the queue: ahead of everything waiting">${ICONS.top}</button>`
          + (canRunNow ? `<button type="button" class="icon-btn start-item${item.continuation ? ' continue-item' : ''}" data-run-now="${item.id}" aria-label="Run this now" title="Run this now: the rest of the queue stays on hold">${ICONS.play}</button>` : '')}</span>
        <span class="when">${item.estimate ? fmtEta(item.estimate) : ''}</span>
        <span class="acts-side acts-end">${item.resume && item.pipeline !== 'shorts' ? `<button type="button" class="icon-btn${item.prompt_warnings && item.prompt_warnings.length ? ' prompt-warning' : ''}" data-shots="${esc(item.resume)}" aria-label="Prompts" title="View prompts">${ICONS.enhanced}</button>` : ''}<button type="button" class="icon-btn" data-edit="${item.id}" aria-label="Go to setup" title="Edit this pending job">${ICONS.config}</button><button type="button" class="icon-btn" data-remove="${item.id}" aria-label="Remove it" title="Remove it (tap twice)">${ICONS.trash}</button></span>
      </div>
    </div>`;
  const unsavedFailures = results.filter(result => result.outcome === 'failed' && !result.run_id && result.job_id != null);
  const unsavedRow = result => `
    <div class="stopped-run" data-job-id="${esc(String(result.job_id))}">
      ${workPrivacy(result, 'failed', result.job_id)}
      <div class="run-head"><div class="what">${queueTitle(`failed-${result.job_id}`, hideTitle(result) ? PLAIN_TITLE : result.label)}</div><span class="run-tag">Failed</span></div>
      <div class="hint">${SIDE_NAMES[result.pipeline] || 'Shorts'} · ${result.recoverable ? 'Failed before a run was saved; its settings are kept' : 'No saved run to retry'}</div>
      ${result.note ? whyHtml({ why: result.note }) : ''}
      ${result.recoverable ? `<div class="stopped-actions">
        <span class="acts-side"><button type="button" class="icon-btn" data-requeue-job="${esc(String(result.job_id))}" aria-label="Back to Pending" title="Back to Pending with its settings, to start it again">${ICONS.again}</button></span>
        <span class="when"></span>
        <span class="acts-side acts-end"><button type="button" class="icon-btn" data-requeue-job="${esc(String(result.job_id))}" data-requeue-edit="1" aria-label="Change settings" title="Back to Generate with its settings, to change them (it waits in Pending)">${ICONS.config}</button><button type="button" class="icon-btn" data-dismiss-job="${esc(String(result.job_id))}" aria-label="Delete this failure" title="Delete it (tap twice)">${ICONS.trash}</button></span>
      </div>` : `<div class="stopped-actions unsaved-actions">
        <button type="button" class="icon-btn" data-dismiss-job="${esc(String(result.job_id))}" aria-label="Delete this failure" title="Delete it (tap twice)">${ICONS.trash}</button>
      </div>`}
    </div>`;
  const checkpointRow = error => `
    <div class="stopped-run" data-motion-key="checkpoint-${esc(error.path)}">
      <div class="run-head"><div class="what">Saved run could not be read</div><span class="run-tag">Failed</span></div>
      <div class="hint">Restore or repair the checkpoint before continuing this run. Other runs remain available.</div>
      ${whyHtml({ why: `${error.path}\n${error.error}` })}
      ${error.run_id ? `<div class="stopped-actions unsaved-actions"><button type="button" class="icon-btn" data-discard-unreadable="${esc(error.run_id)}" aria-label="Delete this unreadable run" title="Delete its run folder and files (tap twice). Output files outside the folder stay.">${ICONS.trash}</button></div>` : ''}
    </div>`;
  const fold = (id, title, rows) => {
    const el = $(id);
    if (el.querySelectorAll('.queue-request, .queue-request-done').length) return;
    el.hidden = !rows.length;
    const html = !rows.length ? '' : `<details class="stopped-fold"${el._open ? ' open' : ''}><summary><b>${title} (${rows.length})</b><span class="chev" aria-hidden="true"></span></summary><div class="stopped-body">${rows.join('')}</div></details>`;
    // Only when it changed, so a poll can't swallow a click on a button it just replaced; nor one waiting for its second tap.
    if (el.dataset.html !== html && !el.querySelectorAll('.armed, .queue-request, .queue-request-done').length) {
      const old = el.querySelector('.stopped-body');
      const top = old ? old.scrollTop : 0;
      el.innerHTML = html;
      el.dataset.html = html;
      setupQueueScroll(el, '.stopped-body', '.stopped-run', top);
    }
  };
  fold('warningRuns', 'Warning', [...warnedParked.map(parkedRow), ...warned.map(run => runRow(run))]);
  fold('stoppedRuns', 'Pending', [...parked.filter(item => !warnedParked.includes(item)).map(parkedRow), ...idle.map(run => runRow(run))]);
  fold('failedRuns', 'Failed', [...failed.map(run => runRow(run, true)), ...unsavedFailures.map(unsavedRow), ...checkpointErrors.map(checkpointRow)]);
}
// Open or shut stays as it was left, through the redraws.
for (const id of ['warningRuns', 'stoppedRuns', 'failedRuns']) {
  $(id).addEventListener('toggle', e => {
    if (!e.target.matches('.stopped-fold')) return;
    const wasOpen = !!$(id)._open;
    $(id)._open = e.target.open;
    if (e.target.open && !wasOpen) {
      closeOtherQueues($(id));
      revealQueueSection(e.target);
    }
  }, true);
  $(id).addEventListener('click', async e => {
    const summary = e.target.closest && e.target.closest('.stopped-fold > summary');
    if (summary) {
      e.preventDefault();
      setQueueAccordionSection($(id), !summary.parentElement.open);
      return;
    }
    const button = e.target.closest && e.target.closest('button');
    const d = button ? button.dataset : {};
    let url;
    if (d.shots) {
      openShots(d.shots);
      return;
    } else if (d.config) {
      if (d.pipeline === 'image') await sameAgain(d.config);
      else if (d.pipeline === 'video') await sameAgainFilm(d.config);
      else await sameAgainShorts(d.config);
      return;
    } else if (d.continue || d.continueTop || d.continueLater) {
      const run = d.continue || d.continueTop || d.continueLater;
      const query = d.continueTop ? '?top=1' : d.continueLater ? '?later=1' : '';
      const data = await queueRequest(button, async () => (await fetch(`/runs/${encodeURIComponent(run)}/continue${query}`, { method: 'POST' })).json(), d.continueLater ? 'Pending' : undefined, d.continueLater ? 'Moving…' : undefined);
      if (data) poll();
      return;
    } else if (d.discardUnreadable) {
      if (!secondTap(button)) return;
      url = `/runs/${encodeURIComponent(d.discardUnreadable)}/discard-unreadable`;
    } else if (d.discard) {
      // Two taps, as a delete: what it already made stays in Output.
      if (!secondTap(button)) return;
      url = `/runs/${d.discard}/discard`;
    } else if (d.requeueJob) {
      // Back to Pending with its settings; the sliders then open it for editing there, as any pending job.
      if (d.requeueEdit && (queueEdit || queueUpscaleEdit)) {
        alert('Finish or cancel the current queued edit first.');
        return;
      }
      const data = await queueRequest(button, async () => (await fetch(`/queue/run/failed/${encodeURIComponent(d.requeueJob)}/requeue`, { method: 'POST' })).json(), 'Pending', 'Moving…');
      if (!data) return;
      if (d.requeueEdit) {
        const opener = document.createElement('button');
        opener.className = 'icon-btn';
        await editQueued(data.id, opener);
      }
      poll();
      return;
    } else if (d.dismissJob) {
      if (!secondTap(button)) return;
      url = `/queue/run/failed/${encodeURIComponent(d.dismissJob)}/dismiss`;
    } else if (d.edit) {
      await editQueued(d.edit, button);
      return;
    } else if (d.runNow) {
      const data = await queueRequest(button, async () => (await fetch(`/queue/run/run-now/${d.runNow}`, { method: 'POST' })).json(), 'Started', 'Starting…');
      if (data) poll();
      return;
    } else if (d.start || d.remove) {
      if (d.remove && !secondTap(button)) return;
      if (d.start) {
        const data = await queueRequest(button, async () => (await fetch(`/queue/run/start/${d.start}${d.top ? '?top=1' : ''}`, { method: 'POST' })).json());
        if (data) poll();
      } else {
        await removeQueued('run', d.remove);
        poll();
      }
      return;
    } else {
      return;
    }
    await stopJob(url);
  });
}
// Reordering the queue: select a job, then drag it or move it with the arrow keys. The page moves it at once,
// then sends the new order; the next poll draws what the server has.
function queueOrder(el) { return [...el.querySelectorAll('.queue-item[data-id]')].map(node => Number(node.dataset.id)); }
// Rows that change place glide there instead of jumping (FLIP: note where they were, move, play from the old spot).
// A row still gliding when the order changes again starts from where it shows, not where it was headed: one glide
// stacked on another made rows jump while dragging.
function glide(el, move) {
  const rows = [...el.querySelectorAll('.queue-item[data-id]')];
  const before = new Map(rows.map(row => [row, row.getBoundingClientRect().top]));
  for (const row of rows) for (const animation of row.getAnimations ? row.getAnimations() : []) animation.cancel();
  move();
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  for (const row of rows) {
    const shift = before.get(row) - row.getBoundingClientRect().top;
    if (!shift) continue;
    row.animate([{ transform: `translateY(${shift}px)` }, { transform: 'none' }], { duration: 220, easing: 'cubic-bezier(.2,.8,.2,1)' });
  }
}
async function sendOrder(el) {
  el._ordering = true;
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), POLL_TIMEOUT);
  try {
    const response = await fetch(`/queue/${el.dataset.lane}/order`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: queueOrder(el) }), signal: abort.signal });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not reorder the queue.');
  } catch (error) {
    alert(`Could not reorder the queue: ${error.message}`);
  } finally {
    clearTimeout(timer);
    el._ordering = false;
    el.dataset.html = '';
    poll();
  }
}
async function sortQueueByEta(el) {
  if (el._ordering || el._dragging || el._leaving || !el._last) return;
  const estimates = new Map(el._last[0].items.map(item => [String(item.id),
    Number.isFinite(item.estimate) && item.estimate >= 0 ? item.estimate : Infinity]));
  const rows = [...el.querySelectorAll('.queue-item[data-id]')];
  const ordered = rows.slice().sort((a, b) => (estimates.get(a.dataset.id) ?? Infinity) - (estimates.get(b.dataset.id) ?? Infinity));
  if (ordered.every((row, index) => row === rows[index])) return;
  glide(el, () => { for (const row of ordered) row.parentElement.appendChild(row); });
  await sendOrder(el);
}
function dragQueue(el) {
  let drag = null;
  const moveRow = y => {
    const rows = [...el.querySelectorAll('.queue-item[data-id]')].filter(row => row !== drag.row);
    const after = rows.find(row => { const box = row.getBoundingClientRect(); return y < box.top + box.height / 2; });
    if (after) { if (drag.row.nextElementSibling !== after) glide(el, () => after.before(drag.row)); }
    else if (rows.length && rows[rows.length - 1].nextElementSibling !== drag.row) glide(el, () => rows[rows.length - 1].after(drag.row));
  };
  // Held against the top or bottom of the queue's list, the list scrolls: the deeper into the edge the faster, and
  // the longer it is held there the faster still. At the list's end it stops: the page stays where it is.
  const scrollDrag = now => {
    if (!drag) return;
    drag.frame = 0;
    const list = drag.row.parentElement && drag.row.parentElement.classList.contains('queue-list') ? drag.row.parentElement : null;
    if (!scrollReorderEdge(list, drag.y, drag, now)) return;
    moveRow(drag.y);
    drag.frame = requestAnimationFrame(scrollDrag);
  };
  const select = target => {
    if (el._dragging || el._ordering) return false;
    if (!target.closest || target.closest('button')) return false;
    const row = target.closest('.queue-item');
    if (!row || !row.querySelector('.what[role="button"]')) return false;
    el._selected = el._selected === row.dataset.id ? null : row.dataset.id;
    renderQueue(el, ...el._last);
    return true;
  };
  el.addEventListener('click', e => {
    if (el._dragClick) { el._dragClick = false; e.preventDefault(); e.stopImmediatePropagation(); return; }
    select(e.target);
  });
  // Once a job is selected, the whole box is its handle: pressed, it is held at once, and as it is dragged up or down
  // it takes the place under the pointer, the others gliding aside. Its buttons stay buttons. Let go, it is let go.
  el.addEventListener('pointerdown', e => {
    if (!e.target.closest || e.target.closest('button') || e.button > 0 || el._ordering) return;
    const row = e.target.closest('.queue-item');
    if (!row || row.dataset.id !== el._selected) return;
    e.preventDefault();
    drag = { row, pointer: e.pointerId, before: queueOrder(el).join(), nodes: [...el.querySelectorAll('.queue-item[data-id]')],
      y: e.clientY, frame: 0, lastFrame: null, edgeSince: null, carry: 0 };
    // From the press on, a poll leaves the queue as it is, so the row held stays the row on the page.
    el._dragging = true;
    row.classList.add('dragging');
    try { el.setPointerCapture(e.pointerId); } catch (err) {}
  });
  el.addEventListener('pointermove', e => {
    if (!drag || e.pointerId !== drag.pointer) return;
    drag.y = e.clientY;
    moveRow(drag.y);
    if (!drag.frame) drag.frame = requestAnimationFrame(scrollDrag);
  });
  const drop = e => {
    if (!drag || e.pointerId !== drag.pointer) return;
    if (drag.frame) cancelAnimationFrame(drag.frame);
    drag.row.classList.remove('dragging');
    const cancelled = e.type === 'pointercancel';
    if (cancelled) {
      const parent = drag.row.parentElement;
      glide(el, () => { for (const row of drag.nodes) parent.appendChild(row); });
    }
    const moved = !cancelled && queueOrder(el).join() !== drag.before;
    // Let go, the job is let go too, dragged or only tapped. Held, the click after it lands on the queue, not the
    // job, so the drop does it, and that click does nothing more.
    if (!cancelled) el._selected = null;
    if (!cancelled) {
      el._dragClick = true;
      setTimeout(() => { el._dragClick = false; }, 0);
    }
    drag = null;
    el._dragging = false;
    if (moved) sendOrder(el); else renderQueue(el, ...el._last);
  };
  el.addEventListener('pointerup', drop);
  el.addEventListener('pointercancel', drop);
  // However the drag ends, even if the browser takes the pointer away, the queue is drawn again after it.
  el.addEventListener('lostpointercapture', drop);
  el.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && select(e.target)) {
      e.preventDefault();
      const row = [...el.querySelectorAll('.queue-item[data-id]')].find(item => item.dataset.id === e.target.closest('.queue-item').dataset.id);
      if (row) row.querySelector('.what').focus();
      return;
    }
    const title = e.target.closest && e.target.closest('.what[role="button"]');
    const row = title && title.closest('.queue-item');
    if (!row || row.dataset.id !== el._selected || el._ordering || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
    e.preventDefault();
    const other = e.key === 'ArrowUp' ? row.previousElementSibling : row.nextElementSibling;
    if (!other || !other.classList.contains('queue-item')) return;
    if (e.key === 'ArrowUp') glide(el, () => other.before(row)); else glide(el, () => other.after(row));
    title.focus();
    sendOrder(el);
  });
}
function revealQueueSection(section) {
  if (section.closest('#optionsCard')) return;
  const header = section.querySelector('.queue-head, summary') || section;
  header.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
}
function setQueueSectionOpen(section, open) {
  section._open = open;
  const details = section.querySelector('.stopped-fold');
  if (details) details.open = open;
  const list = section.querySelector('.queue-list');
  if (list) list.hidden = !open;
  for (const control of section.querySelectorAll('button[data-fold-queue]')) {
    control.setAttribute('aria-expanded', String(open));
    if (control.classList.contains('queue-fold-arrow')) control.setAttribute('aria-label', open ? 'Collapse queue' : 'Expand queue');
  }
  if (list && section.dataset.html) {
    section.dataset.html = section.dataset.html
      .replace(/aria-expanded="(?:true|false)"/g, `aria-expanded="${open}"`)
      .replace(/aria-label="(?:Collapse|Expand) queue"/, `aria-label="${open ? 'Collapse' : 'Expand'} queue"`)
      .replace(/class="queue-list" tabindex="0"(?: hidden)?/, `class="queue-list" tabindex="0"${open ? '' : ' hidden'}`);
  } else delete section.dataset.html;
  section.classList.toggle('queue-open', open && !section.hidden);
}
function closeOtherQueues(current) {
  for (const section of $('queueBox').querySelectorAll(':scope > .queue')) {
    if (section !== current) setQueueSectionOpen(section, false);
  }
}
for (const id of ['runQueue', 'uploadQueue']) {
  dragQueue($(id));
  $(id).addEventListener('click', async e => {
    const sort = e.target.closest && e.target.closest('button[data-sort-queue]');
    if (sort) { await sortQueueByEta($(id)); return; }
    const fold = e.target.closest && e.target.closest('button[data-fold-queue]');
    if (fold) {
      const el = $(id), list = el.querySelector('.queue-list');
      const open = el._open === false;
      setQueueAccordionSection(el, open);
      if (el._open) {
        setupQueueScroll(el, '.queue-list', '.queue-item', list ? list.scrollTop : 0);
      }
      return;
    }
    const button = e.target.closest && e.target.closest('button[data-run], button[data-pause], button[data-top], button[data-remove], button[data-resume], button[data-queue-toggle], button[data-edit], button[data-shots]');
    const d = button ? button.dataset : {}, lane = $(id).dataset.lane;
    if (d.edit) {
      await editQueued(d.edit, button);
      return;
    }
    if (d.shots) {
      await openShots(d.shots);
      return;
    }
    if (d.queueToggle) {
      const state = $(id)._last[0];
      const data = await queueRequest(button, async () => {
        if (state.stopAfter) {
          const result = await (await fetch('/stop-after', { method: 'POST' })).json();
          if (!result.ok) return result;
          if (!state.held) return result;
        }
        const action = state.held || state.stopAfter ? 'resume' : state.running && state.pipeline !== 'video' ? null : 'hold';
        return (await fetch(action ? `/queue/run/${action}` : '/stop-after', { method: 'POST' })).json();
      }, state.held || state.stopAfter ? 'Resumed' : 'Paused', 'Updating…');
      if (!data) return;
    }
    else if (d.run || d.pause) {
      const action = d.run ? 'run-now' : 'pause';
      const data = await queueRequest(button, async () => (await fetch(`/queue/${lane}/${action}/${d.run || d.pause}`, { method: 'POST' })).json(), d.pause ? 'Pending' : 'Started', d.pause ? 'Pausing…' : 'Starting…');
      if (!data) return;
    }
    else if (d.top) {
      // First in line: the queue's order with this one moved to the front.
      const ids = [Number(d.top), ...queueOrder($(id)).filter(n => n !== Number(d.top))];
      const data = await queueRequest(button, async () => (await fetch(`/queue/${lane}/order`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) })).json(), 'Next', 'Moving…');
      if (!data) return;
    }
    else if (d.remove) {
      if (!secondTap(button)) return;
      await removeQueued(lane, d.remove);
    }
    else if (d.resume) {
      // Shown at once; the next status confirms it.
      if ($(id)._last) { $(id)._last[0] = { ...$(id)._last[0], held: false }; renderQueue($(id), ...$(id)._last); }
      await fetch(`/queue/${lane}/resume`, { method: 'POST' });
    }
    else return;
    poll();
  });
}
