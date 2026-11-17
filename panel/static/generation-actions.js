function showFormError(text) {
  $('formError').textContent = $('goError').textContent = text || '';
  $('formError').hidden = $('goError').hidden = !text;
}
let queueEdit = null;
let queueUpscaleEdit = null;
function endQueueEdit(edit) {
  if (queueEdit === edit) {
    queueEdit = null;
    queueEditLabel();
    showFormError('');
  }
  if (queueUpscaleEdit === edit) {
    queueUpscaleEdit = null;
    if ($('upscaleSettings').open) $('upscaleSettings').close();
  }
}
function reconcileQueueEdits(queue, editAtRequest, upscaleAtRequest) {
  for (const edit of [editAtRequest, upscaleAtRequest]) {
    if (edit && !queue.items.some(item => String(item.id) === String(edit.id) && item.editing)) endQueueEdit(edit);
  }
}
async function removeQueued(lane, id) {
  try {
    const body = await (await fetch(`/queue/${lane}/remove/${id}`, { method: 'POST' })).json();
    if (!body.ok) { alert(body.error || 'That queued job could not be removed.'); return; }
    if (lane === 'run') {
      for (const edit of [queueEdit, queueUpscaleEdit]) if (edit && String(edit.id) === String(id)) endQueueEdit(edit);
    }
  } catch (error) { alert('Could not reach the panel. Try again.'); }
}
async function cancelQueueUpscale() {
  if (!queueUpscaleEdit || $('upscaleGo').disabled) return;
  const edit = queueUpscaleEdit;
  try {
    const body = await (await fetch(`/queue/run/edit/${edit.id}/cancel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: edit.token }),
    })).json();
    if (queueUpscaleEdit !== edit) return;
    if (!body.ok) { alert(body.error || 'Could not cancel editing.'); return; }
    queueUpscaleEdit = null;
    $('upscaleSettings').close();
    poll();
  } catch (error) { alert('Could not reach the panel. Try again.'); }
}
// Esc while a queued one is open: as Cancel, so it goes back as it was.
$('upscaleSettings').addEventListener('cancel', e => { if (queueUpscaleEdit) { e.preventDefault(); cancelQueueUpscale(); } });
// What the upscale box now says, saved to the queued job: as the viewer would queue it.
async function saveQueueUpscale(button) {
  const edit = queueUpscaleEdit;
  const size = $('viewerUpscaleSize').value, times = /^x(\d)$/.exec(size);
  const values = edit.kind === 'image_upscale'
    ? { token: edit.token, method: upscaleMethod, strength: $('viewerUpscaleStrength').value,
        ...(times ? { times: times[1] } : { resolution: size }), denoise: upscaleMethod === 'seedvr2' ? $('viewerUpscaleDenoise').value : '' }
    : { token: edit.token, scale: $('filmUpscaleScale').value, quality: $('filmUpscaleQuality').value };
  $('upscaleCancel').disabled = true;
  const body = await queueRequest(button, async () => (await fetch(`/queue/run/edit/${edit.id}/upscale`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
  })).json(), 'Saved', 'Saving…');
  if (queueUpscaleEdit !== edit) return;
  $('upscaleCancel').disabled = false;
  if (body) { queueUpscaleEdit = null; $('upscaleSettings').close(); poll(); }
}
// A continued run being edited: its prompt made the generated ones, so it stays; they open from under it.
function syncContinued() {
  const run = queueEdit && queueEdit.continued;
  for (const button of document.querySelectorAll('[data-generated-prompts]')) {
    const side = button.closest('#formImage') ? 'image' : 'video';
    button.hidden = !run || queueEdit.pipeline !== side;
    if (run) button.textContent = `Generated prompts · ${run.prompts.length}`;
  }
  for (const side of ['video', 'image']) {
    const field = $(PROMPT_FIELDS[side]);
    if (run && queueEdit.pipeline === side) { field.dataset.continued = '1'; field.readOnly = true; }
    else if (field.dataset.continued) { delete field.dataset.continued; field.readOnly = false; }
  }
}
// A queued job being changed in place saves back to the queue; a continued run reopened as a new run is added like any other.
function queueSaves() { return !!queueEdit && !queueEdit.fresh; }
function queueEditLabel() {
  syncContinued();
  $('cancelQueueEdit').hidden = !queueEdit;
  $('goLater').hidden = $('goTop').hidden = $('goStickLater').hidden = $('goStickTop').hidden = queueSaves();
  if (!submitting) $('go').textContent = $('goStick').textContent = queueSaves() ? 'Save to queue' : goLabel(wasRunning);
}
async function editQueued(id, button) {
  const epoch = workspaceEpoch;
  if (queueUpscaleEdit) {
    alert('Finish or cancel the current queued edit first.');
    return;
  }
  if (queueEdit && String(queueEdit.id) !== String(id)) {
    alert('Finish or cancel the current queued edit first.');
    return;
  }
  const data = await queueRequest(button, async () => (await fetch(`/queue/run/edit/${id}`, { method: 'POST' })).json(), 'Pending', 'Opening…');
  if (epoch !== workspaceEpoch || !data) return;
  if (data.upscale) {
    // The viewer's own upscale box, filled in as it was queued.
    queueUpscaleEdit = { id: data.id, token: data.token, ...data.upscale };
    const image = data.upscale.kind === 'image_upscale';
    openUpscaleSettings(image ? (UPSCALE_METHODS_OFFERED.includes(data.upscale.method) ? data.upscale.method : 'seedvr2') : 'vsr', queueUpscaleEdit);
    poll();
    return;
  }
  if (data.continued) {
    // Its setup opens in full, as a new run: whatever is changed makes a fresh run, and the paused one is left as it was.
    queueEdit = { id: data.id, token: data.token, pipeline: data.pipeline, ready: false, fresh: true, continued: null };
    const fresh = queueEdit;
    queueEditLabel();
    poll();
    const opened = data.continued.image ? await sameAgain(data.continued.id) : await sameAgainFilm(data.continued.id);
    if (queueEdit !== fresh) return;
    if (!opened) {
      showFormError('Could not open that run\'s setup. The job remains in Pending.');
      return;
    }
    fresh.ready = true;
    showFormError('');
    queueEditLabel();
    return;
  }
  queueEdit = { id: data.id, token: data.token, pipeline: data.pipeline, ready: false, continued: null };
  reopening(data.pipeline);
  const edit = queueEdit;
  queueEditLabel();
  poll();
  try {
    const files = {};
    for (const name of data.files) {
      const response = await fetch(`/queue/run/edit/${id}/file/${encodeURIComponent(name)}`, { headers: { 'X-Queue-Edit-Token': data.token } });
      if (!response.ok) throw new Error(`Could not load ${name}.`);
      const blob = await response.blob();
      if (queueEdit !== edit) return;
      files[name] = new File([blob], data.filenames[name], { type: blob.type || 'application/octet-stream' });
    }
    if (pipeline !== data.pipeline) setPipeline(data.pipeline);
    if (pipeline === 'video') await loadVideoWorkflows();
    else if (pipeline === 'image') await loadImageWorkflows();
    else await loadWorkflows();
    if (queueEdit !== edit) return;
    const form = $(SIDE_FORMS[pipeline]), values = data.form;
    form.reset();
    for (const el of form.elements) if (el.type === 'checkbox') el.checked = false;
    const apply = () => {
      const indexes = {};
      for (const el of form.elements) {
        if (!el.name || el.type === 'file' || !(el.name in values)) continue;
        const all = Array.isArray(values[el.name]) ? values[el.name] : [values[el.name]];
        if (el.type === 'checkbox') el.checked = all.some(value => value && value !== '0');
        else {
          const index = indexes[el.name] || 0;
          const value = all[Math.min(index, all.length - 1)];
          indexes[el.name] = index + 1;
          if (!el.options || [...el.options].some(o => o.value === String(value) && !o.disabled)) el.value = value;
        }
      }
    };
    apply();
    const workflow = Array.isArray(values.workflow) ? values.workflow[0] : values.workflow;
    const workflowField = pipeline === 'image' ? $('imageWorkflow') : pipeline === 'video' ? $('videoWorkflow') : $('workflow');
    if (workflow && workflowField.value !== workflow && !edit.continued) throw new Error('The saved workflow is unavailable. The job remains in Pending.');
    if (pipeline === 'video') {
      imageBoxes().forEach(clearImage);
      mediaBoxes().forEach(clearMedia);
      imagesShown = Math.max(1, Object.keys(files).filter(name => /^image(_\d+)?$/.test(name)).length);
      mediaShown = Math.max(1, Object.keys(files).filter(name => /^ref_media(_\d+)?$/.test(name)).length);
      if (values.size && String(values.size) !== '') $('sizePreset').value = 'custom';
      syncVideoForm();
    } else if (pipeline === 'image') {
      sourceBoxes().forEach((box, i) => clearSource(box, i === 0));
      sourcesShown = Math.max(1, Object.keys(files).filter(name => /^image(_\d+)?$/.test(name)).length);
      if (values.size && !values.aspect) $('imageAspect').value = 'custom';
      syncImageForm();
    } else syncForm();
    for (const [name, file] of Object.entries(files)) {
      const input = [...form.elements].find(el => el.name === name && el.type === 'file');
      if (!input || input.disabled) throw new Error(`Cannot restore ${name} for this workflow. The job remains in Pending.`);
      putFile(input, file);
      const box = input.closest('.image-box');
      if (box && pipeline === 'image') showSource(box, sourceBoxes()[0] === box);
      else if (box && name.startsWith('ref_media')) showMedia(box);
      else if (box) showImage(box);
    }
    apply();
    if (pipeline === 'video') syncVideoForm(); else if (pipeline === 'image') syncImageForm(); else syncForm();
    const options = pipeline === 'video' ? (workflowTakes[$('videoWorkflow').value] || {}).options || []
      : pipeline === 'image' ? imageTakes().options || [] : (shortsTakes[$('workflow').value] || {}).options || [];
    if (Object.keys(data.options || {}).length) applyOptions($(OPTION_BOXES[pipeline]), options, data.options);
    edit.ready = true;
    showFormError('');
    reopened(pipeline);
    queueEditLabel();
    // Set in code, the form sends no input event: the footer's estimate is the job's, not the form's before it.
    queuePlan();
    if (WIDE.matches) $('optionsCard').scrollIntoView({ behavior: 'smooth' }); else showPage('generate');
  } catch (error) {
    if (queueEdit !== edit) return;
    showFormError(error.message || 'Could not restore the queued setup. The job remains in Pending.');
    alert(error.message || 'Could not restore the queued setup. The job remains in Pending.');
  }
}
$('cancelQueueEdit').addEventListener('click', async () => {
  if (!queueEdit) return;
  const edit = queueEdit;
  try {
    const body = await (await fetch(`/queue/run/edit/${edit.id}/cancel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: edit.token }),
    })).json();
    if (queueEdit !== edit) return;
    if (!body.ok) { alert(body.error || 'Could not cancel editing.'); return; }
    queueEdit = null;
    queueEditLabel();
    poll();
  } catch (error) { alert('Could not reach the panel. Try again.'); }
});
for (const form of ['formShorts', 'formVideo', 'formImage']) $(form).addEventListener('input', () => { if (!$('goError').hidden) showFormError(''); });
// Sends a form and reports how much of it is sent: an image over mobile data can take a while.
function postForm(url, form, progress) {
  return new Promise(resolve => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.responseType = 'json';
    xhr.upload.onprogress = e => { if (e.lengthComputable) progress(e.loaded / e.total); };
    xhr.onload = () => resolve(xhr.response || { error: `The panel answered ${xhr.status}. Try again.` });
    xhr.onerror = xhr.ontimeout = () => resolve({ error: 'Could not reach the panel. Try again.' });
    xhr.send(form);
  });
}
// From the tap until the panel has it: the buttons say so, and Status shows it on its way to the queue.
function showSending(share) {
  const pct = share === null ? '' : ` ${Math.round(share * 100)}%`;
  $('go').textContent = $('goStick').textContent = `Sending…${pct}`;
  $('queuePending').hidden = false;
  $('queuePendingText').textContent = `${SIDE_NAMES[pipeline]}: ${share !== null && share >= 1 ? 'adding to the queue…' : 'sending…'}`;
  $('queuePendingPct').textContent = pct.trim();
  $('queuePendingBar').style.width = `${Math.round((share || 0) * 100)}%`;
}
async function startJob(url, later = false, top = false) {
  if (submitting) return;
  if ((pipeline === 'video' || pipeline === 'image') && $(pipeline + 'PromptWriting').classList.contains('busy')) {
    showFormError('Wait for the prompt writer to finish first.');
    return;
  }
  if (queueEdit && pipeline !== queueEdit.pipeline) {
    showFormError('Return to the run being edited, or cancel editing first.');
    return;
  }
  if (queueEdit && !queueEdit.ready) {
    showFormError('The queued setup could not be restored. Open it again or cancel editing.');
    return;
  }
  showFormError('');
  submitting = true;
  $('go').disabled = $('goStick').disabled = $('goLater').disabled = $('goTop').disabled = $('goStickLater').disabled = $('goStickTop').disabled = true;
  showSending(0);
  if (later) $('goLater').textContent = 'Adding…';
  if (top) $('goTop').textContent = 'Adding…';
  const form = new FormData($(SIDE_FORMS[pipeline]));
  if (later) form.append('start_later', '1');
  if (top) form.append('queue_top', '1');
  if (queueEdit && queueEdit.continued) url = `/queue/run/edit/${queueEdit.id}/continue`;
  if (queueEdit) {
    form.append('queue_edit_id', String(queueEdit.id));
    form.append('queue_edit_token', queueEdit.token);
  }
  const body = await postForm(url, form, showSending);
  if (body.ok) {
    $('go').textContent = $('goStick').textContent = later ? 'Pending' : body.queued ? 'Queued' : 'Started';
    if (later) $('goLater').textContent = 'Pending';
    if (top) $('goTop').textContent = body.queued ? 'Queued first' : 'Started';
    await new Promise(resolve => setTimeout(resolve, 800));
  }
  submitting = false;
  $('go').disabled = $('goStick').disabled = $('goLater').disabled = $('goTop').disabled = $('goStickLater').disabled = $('goStickTop').disabled = false;
  $('goLater').textContent = 'Add to pending';
  $('goTop').textContent = 'Add to top of queue';
  if (body.ok && queueEdit) queueEdit = null;
  queueEditLabel();
  $('queuePending').hidden = true;
  $('go').textContent = $('goStick').textContent = queueSaves() ? 'Save to queue' : goLabel(wasRunning);
  $('formNote').hidden = !body.continued;
  if (body.continued) $('formNote').textContent = `Continuing what was already paid for: ${body.continued}`;
  if (!body.ok) {
    showFormError(body.error || 'Could not start.');
  } else if (url.startsWith('/queue/run/edit/')) {
    autoScroll = true;
    queuePlan();
  } else if (url.startsWith('/generate/video')) {
    // Keep the form intact so variants can be queued without entering everything again.
    autoScroll = true;
    queuePlan();
    if (body.shots) openShots(body.shots);
  } else if (url.startsWith('/generate/image')) {
    // Keep the prompt, sources and painting for another variant.
    autoScroll = true;
    queuePlan();
    if (body.shots) openShots(body.shots);
  } else if (body.queued) {
    queuePlan();
  } else {
    autoScroll = true;
  }
  poll();
}
$('go').addEventListener('click', () => {
  if (pipeline === 'video') saveVideoForm(); else if (pipeline === 'image') saveImageForm(); else saveForm();
  startJob(`/generate/${pipeline}`);
});
$('goStick').addEventListener('click', () => $('go').click());
$('goStickLater').addEventListener('click', () => $('goLater').click());
$('goStickTop').addEventListener('click', () => $('goTop').click());
// Into the queue, waiting at its end until you start it there.
$('goLater').addEventListener('click', () => {
  if (pipeline === 'video') saveVideoForm(); else if (pipeline === 'image') saveImageForm(); else saveForm();
  startJob(`/generate/${pipeline}`, true);
});
// Into the queue ahead of everything already waiting there.
$('goTop').addEventListener('click', () => {
  if (pipeline === 'video') saveVideoForm(); else if (pipeline === 'image') saveImageForm(); else saveForm();
  startJob(`/generate/${pipeline}`, false, true);
});

const PROMPT_FIELDS = { shorts: 'topic', video: 'prompt', image: 'imagePrompt' };
function syncPromptWriter(side) {
  const field = $(PROMPT_FIELDS[side]);
  $(side === 'video' ? 'writeVideoPrompt' : 'writeImagePrompt').disabled = field.readOnly || !field.value.trim();
  $(side === 'video' ? 'clearVideoPrompt' : 'clearImagePrompt').disabled = field.readOnly;
}
for (const side of ['video', 'image']) $(PROMPT_FIELDS[side]).addEventListener('input', () => syncPromptWriter(side));
function promptWriterSpeed() {
  const writer = lastStatus && lastStatus.prompt_writer;
  return writer && writer.running && writer.tokens ? `${writer.tokens.per_second.toFixed(1)} tok/s` : '';
}
async function writePrompt(side) {
  const epoch = workspaceEpoch;
  const field = $(PROMPT_FIELDS[side]), button = $(side === 'video' ? 'writeVideoPrompt' : 'writeImagePrompt');
  const box = $(side + 'PromptWriting'), error = $(side + 'PromptWriteError'), original = field.value;
  const bar = $(side + 'PromptProgress'), eta = $(side + 'PromptEta');
  error.hidden = true;
  if (!original.trim()) { error.textContent = 'Enter an idea first.'; error.hidden = false; return; }
  button.disabled = true;
  button.classList.add('working');
  field.readOnly = true;
  syncPromptWriter(side);
  box.classList.add('busy');
  box.setAttribute('aria-busy', 'true');
  bar.hidden = eta.hidden = false;
  bar.style.width = '0%';
  eta.textContent = 'Estimating…';
  let timer;
  try {
    const estimateResponse = await fetch('/api/write-prompt?pipeline=' + encodeURIComponent(side));
    const estimate = await estimateResponse.json();
    if (epoch !== workspaceEpoch) return;
    if (!estimateResponse.ok || !estimate.ok || !Number.isFinite(estimate.seconds) || estimate.seconds <= 0) throw new Error(estimate.error || 'Could not estimate prompt writing.');
    const start = performance.now();
    const update = () => {
      if (epoch !== workspaceEpoch) return;
      const elapsed = (performance.now() - start) / 1000, remaining = estimate.seconds - elapsed;
      bar.style.width = `${Math.min(95, Math.max(0, elapsed / estimate.seconds * 100))}%`;
      eta.textContent = [promptWriterSpeed(), remaining > 0 ? `${fmtEta(remaining)} left` : 'Taking longer than estimated'].filter(Boolean).join(' · ');
    };
    update();
    timer = setInterval(update, 1000);
    const response = await fetch('/api/write-prompt', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pipeline: side, prompt: original, model: estimate.model }) });
    const result = await response.json();
    if (epoch !== workspaceEpoch) return;
    if (!response.ok || !result.ok) throw new Error(result.error || 'Could not write the prompt.');
    if (field.value !== original) throw new Error('The prompt changed while writing; it was not replaced.');
    field.value = result.prompt;
    $(side + 'PromptWriterModel').value = estimate.model || '';
    const mode = $(side + 'PromptMode');
    if (side === 'image' && !mode.disabled) {
      mode.value = 'direct';
      mode.dispatchEvent(new Event('change', { bubbles: true }));
    }
    field.dispatchEvent(new Event('input', { bubbles: true }));
    if (side === 'video') saveVideoForm(); else saveImageForm();
  } catch (e) {
    if (epoch !== workspaceEpoch) return;
    error.textContent = e.message || 'Could not write the prompt.';
    error.hidden = false;
  } finally {
    clearInterval(timer);
    if (epoch === workspaceEpoch) {
      bar.hidden = eta.hidden = true;
      bar.style.width = '0%';
      button.classList.remove('working');
      field.readOnly = false;
      syncPromptWriter(side);
      box.classList.remove('busy');
      box.setAttribute('aria-busy', 'false');
    }
  }
}
$('writeVideoPrompt').addEventListener('click', () => writePrompt('video'));
$('writeImagePrompt').addEventListener('click', () => writePrompt('image'));
// Normal prompts survive a reload; private drafts stay only in this page's memory.
const PROMPTS_KEY = 'gen-center.prompts.normal';
function keptPrompts() {
  if (privateMode) return {};
  try { return JSON.parse(sessionStorage.getItem(PROMPTS_KEY) || '{}') || {}; } catch (e) { return {}; }
}
function keepPrompt(side) {
  if (privateMode) return;
  try { sessionStorage.setItem(PROMPTS_KEY, JSON.stringify({ ...keptPrompts(), [side]: $(PROMPT_FIELDS[side]).value })); } catch (e) {}
}
document.addEventListener('input', e => {
  const side = Object.keys(PROMPT_FIELDS).find(key => e.target && e.target.id === PROMPT_FIELDS[key]);
  if (side) keepPrompt(side);
});
function clearPrompt(side) {
  const field = $(PROMPT_FIELDS[side]);
  if (!field.value) return;
  field.value = '';
  field.dispatchEvent(new Event('input', { bubbles: true }));
  if (side !== 'shorts') syncPromptWriter(side);
}
for (const [id, side] of [['clearShortsPrompt', 'shorts'], ['clearVideoPrompt', 'video'], ['clearImagePrompt', 'image']]) {
  $(id).addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); clearPrompt(side); });
}
for (const [id, down, up, steps] of [['runs', 'runsDown', 'runsUp', 1], ['imageCount', 'imageCountDown', 'imageCountUp', 1], ['duration', 'durationDown', 'durationUp', 5]]) {
  for (const [button, direction] of [[down, -1], [up, 1]]) {
    $(button).addEventListener('click', () => {
      const field = $(id);
      if (direction < 0) field.stepDown(steps); else field.stepUp(steps);
      field.dispatchEvent(new Event('input', { bubbles: true }));
      field.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }
}
function syncPreviewRun() {
  const unavailable = pipeline === 'video' && !$('start').disabled && $('start').value === 'multishot';
  $('previewRun').disabled = unavailable;
  $('previewRunLabel').hidden = unavailable;
}
function setPipeline(side, remember = true, preservePrompt = false) {
  if (!preservePrompt && choosingFor) { clearPrompt(choosingFor.side); stopChoosing(); }
  // Each side opens with its headings folded.
  if (side !== pipeline) {
    if (!preservePrompt) clearPrompt(pipeline);
    if (!preservePrompt) for (const section of document.querySelectorAll('details.section')) section.open = false;
  }
  pipeline = side;
  if (side !== 'shorts') madeSide = side;
  syncPreviewRun();
  document.body.classList.toggle('on-shorts', side === 'shorts');
  document.body.classList.toggle('on-video', side === 'video');
  document.body.classList.toggle('on-image', side === 'image');
  for (const [id, own] of [['switchShorts', 'shorts'], ['switchVideo', 'video'], ['switchImage', 'image']]) {
    $(id).classList.toggle('active', side === own);
    $(id).setAttribute('aria-selected', side === own);
  }
  $('formNote').hidden = true;
  $(SIDE_FORMS[side]).appendChild($('formActions'));
  document.querySelector(`[data-workflow-actions="${side}"]`).appendChild($('keepSectionsOpen'));
  // One Preview run, in the Other settings of whichever form is showing.
  if (side !== 'shorts') $(side === 'image' ? 'imageReviewBox' : 'videoReviewBox').after($('previewRunLabel'));
  // Shorts' films by its tab; the others' films are the made ones, whichever side Generate is on.
  folder = side === 'shorts' ? 'output' : 'video';
  $('tabOutput').classList.add('active');
  $('tabUploaded').classList.remove('active');
  $('videos').scrollLeft = 0;
  if (remember) {
    try { localStorage.setItem(PIPELINE_KEY, side); } catch (e) {}
    if (window.history && history.replaceState) history.replaceState(null, '', `/${side}`);
  }
  redrawFiltered();
  refreshPlan();
}
for (const id of ['switchShorts', 'switchVideo', 'switchImage']) $(id).addEventListener('click', () => {
  const was = pipeline, side = $(id).dataset.pipeline;
  setPipeline(side);
  if (was !== side) carryImages(was, side);
});
// The images chosen on Image or Video, into the other's empty boxes, in order: one picked to edit is still there for
// a video workflow that takes images. Boxes already filled there keep theirs.
function carryImages(from, to) {
  if (!['image', 'video'].includes(from) || !['image', 'video'].includes(to)) return;
  const files = (from === 'image' ? sourceBoxes() : imageBoxes()).map(box => box.querySelector('input').files[0]).filter(Boolean);
  if (!files.length) return;
  const boxes = () => (to === 'image' ? sourceBoxes() : imageBoxes());
  if (boxes().some(box => box.querySelector('input').files.length)) return;  // It has its own: left as it is
  if (to === 'image') { sourcesShown = Math.max(sourcesShown, files.length); syncImageForm(); }
  else { imagesShown = Math.max(imagesShown, files.length); syncVideoForm(); }
  files.forEach((file, i) => {
    const box = boxes()[i];
    if (!box) return;
    const list = new DataTransfer();
    list.items.add(file);
    box.querySelector('input').files = list.files;
    if (to === 'image') showSource(box, i === 0); else showImage(box);
  });
  if (to === 'image') syncImageForm(); else syncVideoForm();
}
async function stopJob(url) {
  const body = await (await fetch(url, { method: 'POST' })).json();
  if (body.error) alert(body.error);
  poll();
}
$('stop').addEventListener('click', async () => {
  disarm($('skip'));
  if (!secondTap($('stop'))) return;
  const data = await queueRequest($('stop'), async () => (await fetch('/stop', { method: 'POST' })).json(), 'Stopped', 'Stopping…');
  if (data) poll();
});
$('skip').addEventListener('click', async () => {
  disarm($('stop'));
  if (!secondTap($('skip'))) return;
  // No question: it stops now, or as soon as it has something saved to continue from, and the queue goes on.
  const data = await queueRequest($('skip'), async () => (await fetch('/skip', { method: 'POST' })).json(), 'Paused', 'Pausing…');
  if (data) poll();
});

$('stopUpload').addEventListener('click', async () => {
  const held = uploadsQueued ? ` The ${uploadsQueued} queued after it will wait until you press Resume.` : '';
  if (!confirm(`Stop the upload? A video that has not finished sending stays in Ready.${held}`)) return;
  await stopJob('/publish/stop');
});

function openShutdownMenu() {
  const menu = $('shutdownMenu');
  menu.classList.remove('closing');
  menu.hidden = false;
  $('shutdown').setAttribute('aria-expanded', 'true');
}
function closeShutdownMenu() {
  const menu = $('shutdownMenu');
  if (menu.hidden || menu.classList.contains('closing')) return;
  menu.classList.add('closing');
  $('shutdown').setAttribute('aria-expanded', 'false');
  setTimeout(() => {
    if (menu.classList.contains('closing')) { menu.hidden = true; menu.classList.remove('closing'); }
  }, 150);
}
settingsDialog.addEventListener('close', () => {
  closeShutdownMenu();
  if (armed.shutdown) disarmTap('shutdown');
});
document.addEventListener('click', e => {
  if (!$('shutdownMenu').hidden && !(e.target.closest && e.target.closest('#shutdownMenu, #shutdown'))) closeShutdownMenu();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeShutdownMenu();
    if (armed.shutdown) disarmTap('shutdown');
  }
});
$('shutdown').addEventListener('click', async e => {
  e.preventDefault();
  if (!confirmTap('shutdown', 'Shut down')) { openShutdownMenu(); return; }
  closeShutdownMenu();
  const body = await (await fetch('/shutdown', { method: 'POST' })).json();
  if (!body.ok) { alert(body.error || 'Could not shut down.'); return; }
  document.body.innerHTML = '<div class="wrap"><h1>gen-center</h1><p class="sub">The control panel has shut down. Start it again with <b>start_webapp.pyw</b> or the <b>gen-center</b> shortcut.</p></div>';
});

// The section under the header, lit up in it.
