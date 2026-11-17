// --- Status polling ---
let stoppedCount = 0, wasRunning = false, uploadRunning = false, runsQueued = 0, queueHeld = false, uploadsQueued = 0, submitting = false;
let lastRunActionId = null;
// A paused queue with nothing running starts what is pressed straight away; otherwise it joins the queue.
const goLabel = running => running || (runsQueued && !queueHeld) ? 'Add to queue' : 'Generate';
// Longer than a status takes, shorter than anyone would wait for one.
const POLL_TIMEOUT = 8000;
let serverStarted = null;
function formInProgress() {
  if (Object.keys(presetPending).length) return true;
  const unsaved = state => Object.values(state.forms).some(fields => [...fields.values()].some(field =>
    field.files?.length || (field.type === 'textarea' && field.value)));
  return $('shotsDialog').open || $('promptEditor').open || !!$('narration').value
    || (emptyDraft && unsaved(captureDraft()))
    || [...draftWorkspaces.values()].some(unsaved);
}
// One part of the page's update: if it throws, the rest still updates, and the console says what went wrong.
// Before, one error anywhere left the queue and everything after it as it was until the page was reloaded.
const errorsSent = new Set();
function safely(part) {
  try { part(); } catch (e) {
    panelConnection.renderFailure(e);
    console.error('Part of the page could not update:', e);
    // Into the panel's log too, once each, so it can be found from the PC.
    const text = [e && e.message, ...String(e && e.stack || '').split('\n').slice(0, 4)].join(' | ');
    if (errorsSent.has(text)) return;
    errorsSent.add(text);
    try { fetch('/api/page-error', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ error: text }) }).catch(() => {}); } catch (_) {}
  }
}
// One status poll at a time, and every answer is used. Asked for while one is out (a tick, or a button just
// pressed), another follows as soon as it's back. Before, each tick sent one more and threw away all but the newest:
// with the panel slow to answer, no answer was ever the newest, and the page stood still until reloaded.
let polling = false, pollAgain = false, pollGeneration = 0, pollAbort = null;
async function poll() {
  if (polling) { pollAgain = true; return; }
  polling = true;
  const generation = pollGeneration;
  try { await pollOnce(generation); } finally {
    if (generation === pollGeneration) {
      polling = false;
      if (pollAgain) { pollAgain = false; poll(); }
    }
  }
}
// Output is held out of sight (output-pending) until it is drawn from a fresh answer: on loading, on coming back to
// the page (a phone's tab, the browser's cache), and on going to Output. What was drawn before, for another filter or
// before Private mode changed, never shows, even for a moment.
let outputHeldAt = 0;
function holdOutput() {
  outputHeldAt = performance.now();
  document.body.classList.add('output-pending');
  resumePolling();
}
function resumePolling() {
  pollGeneration++;
  if (pollAbort) pollAbort.abort();
  pollAbort = null;
  polling = false;
  pollAgain = false;
  poll();
}
$('connectionRetry').addEventListener('click', resumePolling);
// The panel sends the log from the last line the page has (log_delta), not all of it: the whole log every 2 seconds
// was too much for a phone away from home. Lines the panel has dropped off the top (before log_first) go here too.
function withNewLogLines(data) {
  if (!data.log_delta) return data.lines;
  const from = data.log_first ?? -Infinity, upTo = data.lines.length ? data.lines[0].n : Infinity;
  return logLines.filter(line => line.n >= from && line.n < upTo).concat(data.lines);
}
async function pollOnce(generation) {
  const askedAt = performance.now();
  const editAtRequest = queueEdit, upscaleAtRequest = queueUpscaleEdit;
  const abort = new AbortController();
  pollAbort = abort;
  const timer = setTimeout(() => abort.abort(), POLL_TIMEOUT);
  let data;
  try {
    const response = await fetch(statusUrl('/api/status'), { cache: 'no-store', signal: abort.signal });
    if (generation !== pollGeneration) return;
    // Signed out in the meantime: nothing here would ever update again.
    if (response.redirected) { location.reload(); return; }
    if (response.ok === false) throw new Error(`Status request failed (HTTP ${response.status}).`);
    data = await response.json();
    if (generation !== pollGeneration) return;
    if (!data || !data.queue || !data.upload) throw new Error('The panel returned an invalid status response.');
    data = statusCatalogue.hydrate(data);
    panelConnection.success();
  } catch (e) {
    if (generation === pollGeneration) panelConnection.failure(e);
    return;
  } finally {
    clearTimeout(timer);
    if (pollAbort === abort) pollAbort = null;
  }
  applyStatus(data, askedAt, editAtRequest, upscaleAtRequest);
}
// What the page has, so the panel sends only what is new: its Output catalogue's revision, and its last log line.
function statusUrl(path) {
  const lastLine = logLines.length ? logLines[logLines.length - 1].n : null;
  return statusCatalogue.url().replace('/api/status?', `${path}?`) + (lastLine === null ? '' : `&log_after=${lastLine}`);
}
// The panel pushes the status as it changes (Server-Sent Events), and at least every 2 s for the clock and the GPU.
// Before, the page asked every 2 s, so a change took up to 2 s to show. poll() stays for an answer straight after a
// button, and for when the stream goes quiet.
const STREAM_QUIET_MS = 8000;
let statusStream = null, streamQuiet = null, streamHeardAt = 0;
function openStatusStream() {
  if (typeof EventSource !== 'function') return false;
  if (statusStream) statusStream.close();
  const source = statusStream = new EventSource(statusUrl('/api/status/stream'));
  streamHeardAt = performance.now();
  source.onmessage = event => {
    if (source !== statusStream) return;
    // Each update is worked out after the one before arrived: as fresh as an answer asked for then.
    const askedAt = streamHeardAt;
    streamHeardAt = performance.now();
    watchStreamQuiet();
    let data;
    try {
      data = JSON.parse(event.data);
      if (!data || !data.queue || !data.upload) throw new Error('The panel returned an invalid status response.');
      data = statusCatalogue.hydrate(data);
    } catch (e) {
      panelConnection.failure(e);
      // Connected again from what the page has now: out of sync, that is the whole catalogue.
      openStatusStream();
      return;
    }
    panelConnection.success();
    applyStatus(data, askedAt, queueEdit, queueUpscaleEdit);
  };
  // The browser connects again by itself; the notice shows only if that takes a while.
  source.onerror = () => {
    if (source === statusStream) panelConnection.failure(new Error('Could not reach the panel.'));
  };
  watchStreamQuiet();
  return true;
}
// Nothing for a while (the phone's network changed, signed out, a proxy holding the stream back): ask the usual way,
// which says what is wrong or reloads after a sign-out, and connect again.
function watchStreamQuiet() {
  clearTimeout(streamQuiet);
  streamQuiet = setTimeout(() => { poll(); openStatusStream(); }, STREAM_QUIET_MS);
}
function applyStatus(data, askedAt, editAtRequest, upscaleAtRequest) {
  // A new server has new code: pick it up, unless that would lose what is being typed.
  if (serverStarted && serverStarted !== data.server_started) {
    if (!formInProgress()) {
      for (const side of Object.keys(PROMPT_FIELDS)) keepPrompt(side);
      location.reload();
      return;
    }
  } else {
    serverStarted = data.server_started;
  }

  const running = data.running;
  const actionId = running && data.queue.current ? data.queue.current.id : null;
  if (!running || actionId !== lastRunActionId) {
    disarm($('stop'));
    disarm($('skip'));
  }
  lastRunActionId = actionId;
  if (wasRunning && !running) {
    refreshPlan();  // That run just improved the timings
    // The prompts you asked to read before rendering are ready.
    const planned = data.pipeline !== 'shorts' && data.returncode === 0 && /--(plan|first)-only/.test(data.command || '') && data.progress.run_id;
    if (planned && !$('shotsDialog').open) openShots(data.progress.run_id);
  }
  wasRunning = running;
  const queue = data.queue, upq = data.upload.queue;
  reconcileQueueEdits(queue, editAtRequest, upscaleAtRequest);
  const ready = queue.items.filter(item => !item.later);
  runsQueued = ready.length;
  queueHeld = !!queue.held;
  uploadsQueued = upq.items.length;
  // Pending ones (Add to pending, Pause) aren't in the active queue: they don't start by themselves, so not next, and not part of when this all ends.
  const parked = queue.items.filter(item => item.later);
  // Between two jobs for a moment: the next is about to start, so this isn't "Finished".
  const nextUp = !running && ready.length > 0 && !queue.held;
  // On hold they won't start by themselves, so they aren't part of when this all ends.
  const queuedNext = queue.held ? [] : ready;
  const waitingWork = queuedNext.reduce((sum, item) => sum + (item.estimate || 0), 0);
  const runningLeft = running && data.progress.eta ? data.progress.eta.total_left : 0;
  queueAhead = queue.held ? null : runningLeft + waitingWork;
  $('estimate').hidden = false;
  safely(() => renderPlan());  // The clock has moved on
  uploadingNow = new Set(upq.current ? upq.current.videos : []);
  uploadQueued = new Set(upq.items.flatMap(item => item.videos));
  uploadRunning = data.upload.running;
  busy = uploadRunning || uploadsQueued > 0 || (running && (data.progress.stage || [])[2] === 'Upload');
  safely(() => renderUpload(data.upload));
  safely(() => renderRunSections(() => {
    // On hold: how much is waiting, as it has no time to end by until it's resumed.
    const heldFor = ready.reduce((sum, item) => sum + (item.estimate || 0), 0);
    safely(() => renderQueue($('runQueue'), { ...queue, items: ready, running, pipeline: data.pipeline, stopAfter: data.stop_after }, queue.held ? heldFor : queueAhead, nextUp, !running && !queue.current));
    safely(() => renderStopped(data.stopped_runs, parked, queue.results, queue.held && !running && !queue.current, data.checkpoint_errors || []));
  }));
  safely(() => renderFinished(data.finished_results || queue.results, upq.results, data.made_now || []));
  $('dot').className = 'dot' + (running || nextUp ? ' on' : '');
  // Status's bars in the colour of what is generating.
  document.documentElement.style.setProperty('--job', running && SIDE_COLOURS[data.pipeline] || '');
  $('dot').setAttribute('aria-label', running ? 'Running' : nextUp ? 'Starting' : 'Idle');
  safely(() => renderStrips(data));
  $('go').disabled = $('goStick').disabled = submitting;
  if (!submitting) $('go').textContent = $('goStick').textContent = queueSaves() ? 'Save' : goLabel(running);
  workItem = running ? queue.current : nextUp ? ready[0] : null;
  lastStatus = data;
  const facts = (workItem && workItem.facts) || {};
  showWork(running ? workHeading(queue.current, data.pipeline)
    : nextUp ? workHeading(ready[0], ready[0].pipeline) : '');
  syncNudge(!running && !nextUp);
  $('currentWorkSize').hidden = !workItem || !(facts.workflow || facts.resolution);
  $('currentWorkflow').textContent = facts.workflow || '';
  $('currentResolution').textContent = facts.resolution || '';
  // A job on the other side still has the GPU, so the switch says so.
  for (const [id, side] of [['switchShorts', 'shorts'], ['switchVideo', 'video'], ['switchImage', 'image']]) {
    $(id).querySelector('.dot').classList.toggle('hidden', !(running && data.pipeline === side && side !== pipeline));
  }
  if (data.stopped_runs.length !== stoppedCount) { stoppedCount = data.stopped_runs.length; refreshPlan(); }
  $('runActions').hidden = DESK.matches && !running;
  $('skip').hidden = $('stop').hidden = !running;
  // A Cancel waiting for the run to have something saved: it says so until it happens.
  if (!$('skip').classList.contains('queue-request')) {
    $('skip').textContent = data.cancelling ? 'Pausing…' : 'Pause run';
    $('skip').disabled = !!data.cancelling;
  }
  // A batch (Shorts' videos, Image's images) can end once the one being made is done; a film is one video.

  safely(() => renderNow(data));
  safely(() => renderEtaDetail(running ? (data.progress || {}).eta : null));

  $('statusText').textContent = running || nextUp ? '' : 'Idle';
  $('statusTimes').hidden = !running;
  $('statusStarted').textContent = data.started_at ? data.started_at.slice(0, 5) : '—';
  $('statusDuration').textContent = running ? fmt(data.elapsed) : '';

  data.lines = withNewLogLines(data);
  if (data.lines.length) safely(() => renderLog(data.lines));

  const c = data.comfyui;
  if (c.online !== workflowsFor) { workflowsFor = c.online; loadWorkflows(); loadVideoWorkflows(); loadImageWorkflows(); }
  syncComfyButton(c);
  lastComfy = { ...c, gpu: data.gpu };
  if ('afterburner' in data) safely(() => renderAfterburner(data.afterburner));
  safely(() => renderPoweroff(data.poweroff));
  safely(() => renderPrivate(data.private));
  $('comfyDot').className = 'dot ' + (c.online ? 'ok' : c.starting || c.listening ? 'warn' : 'fail');
  $('comfyStatus').title = `ComfyUI: ${comfyState(c)}`;
  $('comfyStatus').setAttribute('aria-label', $('comfyStatus').title);
  if ($('comfyDialog').open) safely(() => renderComfy(lastComfy));

  safely(() => renderQuota(data.quota));

  lastVideos = data.videos;
  // Every set, to open any image (one in a collection too); and as Output shows them, without what moved to a collection.
  allImageSets = data.image_sets || [];
  imageSets = allImageSets.map(set => ({ ...set, images: set.images.filter(p => !p.collection) })).filter(set => set.images.length || set.generating);
  collections = data.collections || [];
  if (!outputOrderSaving && !gridDrag) SETTINGS.output_order = data.output_order || [];
  if (viewing && viewing.film) {
    const film = (lastVideos[viewing.folder] || []).find(item => item.name === viewing.name);
    if (film) { $('viewerRes').textContent = sizeText(film.resolution); viewerMetadata(film); }
  } else if (viewing) {
    const set = findSet(viewing.id);
    const picture = set && set.images.find(p => p.position === viewing.position);
    if (picture) pictureMetadata(set, picture);
  }
  safely(() => renderVideos());
  safely(() => renderImageSets());
  safely(() => renderCollections());
  // Drawn from an answer asked for after Output was held: what it shows is what should show, NSFW or not.
  if (askedAt >= outputHeldAt) document.body.classList.remove('output-pending');
  document.body.classList.remove('page-loading');
}

// On a desktop the log is always open beside the run; on a phone it stays folded until asked for.
const WIDE = window.matchMedia('(min-width: 1000px)');
function syncLogBox() { $('logBox').open = WIDE.matches; }
WIDE.addEventListener('change', syncLogBox);
syncLogBox();
// A folded log has no height to scroll, so it catches up as it opens.
$('logBox').addEventListener('toggle', () => {
  if (autoScroll) $('log').scrollTop = $('log').scrollHeight;
  if (uploadFollow) $('uploadLog').scrollTop = $('uploadLog').scrollHeight;
});
$('log').addEventListener('scroll', () => {
  const el = $('log');
  autoScroll = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
});
$('uploadLog').addEventListener('scroll', () => {
  const el = $('uploadLog');
  // A folded log has no height: that isn't scrolling away from the end.
  if (el.clientHeight) uploadFollow = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
});
