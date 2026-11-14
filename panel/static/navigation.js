const JUMPS = [...$('jump').querySelectorAll('a')];
// A phone shows one section at a time, the one chosen in the footer. A desktop shows them all, with no footer.
const PAGE_KEY = 'comfyui-auto-gen.page';
const draftWorkspaces = new Map();
// Retain generated inputs themselves so switching does not discard files or unsaved editor text.
const DRAFT_NODES = ['imageBoxes', 'mediaBoxes', 'imageSources', 'shortsOptionsBox', 'videoOptionsBox', 'imageOptionsBox',
  'shortsNegativeSlot', 'videoNegativeSlot', 'imageNegativeSlot', 'shotsBody', 'promptEditorPages'];
const EDITOR_VISIBILITY = ['promptEditorText', 'promptEditorPages', 'promptEditorTurn', 'promptEditorSave',
  'promptEditorClear', 'promptEditorEnhance', 'promptEditorReset'];
const UPSCALE_DRAFT_FIELDS = ['viewerUpscaleSize', 'viewerUpscaleDenoise', 'viewerUpscaleStrength', 'filmUpscaleScale', 'filmUpscaleQuality'];
let emptyDraft = null;
function draftFields(form) {
  const indexes = {};
  return [...form.elements].filter(el => el.name && !['button', 'submit', 'reset'].includes(el.type)).map(el => {
    const name = el.id ? `id:${el.id}` : `name:${el.name}`, index = indexes[name] || 0;
    indexes[name] = index + 1;
    return [`${name}:${index}`, el];
  });
}
function captureDraft(clone = false) {
  return {
    pipeline,
    forms: Object.fromEntries(Object.entries(SIDE_FORMS).map(([side, id]) => [side,
      new Map(draftFields($(id)).map(([key, el]) => [key, { value: el.value, checked: el.checked, type: el.type,
        files: el.type === 'file' ? [...el.files] : null }]))])),
    nodes: DRAFT_NODES.map(id => { const box = $(id); return { id,
      children: [...box.childNodes].map(node => clone ? node.cloneNode(true) : node),
      key: box.dataset.key, workflow: box.dataset.workflow, options: box.optionList, hidden: box.hidden }; }),
    runtime: { imagesShown, mediaShown, sourcesShown, sourceSize, paint, videoMegapixels, videoBase, videoMadeAt,
      videoOffMp, videoLatentWas, imageLeastModel, imageDefaulted, imageStep, imageMadeAt, imageOffMp, imageUpscaleWas, imageShown },
    queueEdit, queueUpscaleEdit, shotsRun, shotsDirty, promptField, generatedEdit, promptEditorOriginal, promptEditorEnhanced, promptEditorModel,
    upscaleDraft: queueUpscaleEdit ? { method: upscaleMethod, values: UPSCALE_DRAFT_FIELDS.map(id => [id, $(id).value]) } : null,
    editorText: $('promptEditorText').value,
    areasHint: $('areasHint').textContent,
    editorVisibility: EDITOR_VISIBILITY.map(id => [id, $(id).hidden]),
    editorLabels: ['promptEditorTitle', 'promptEditorCount', 'promptEditorCancel'].map(id => [id, $(id).textContent]),
    openDialogs: ['promptEditor', 'shotsDialog', 'paintDialog'].filter(id => $(id).open),
    presetPicked: { ...presetPicked },
    presetEditors: capturePresetEditors(),
  };
}
function restoreDraft(state) {
  for (const { id, children, key, workflow, options, hidden } of state.nodes) {
    const box = $(id);
    box.replaceChildren(...children);
    if (key === undefined) delete box.dataset.key; else box.dataset.key = key;
    if (workflow === undefined) delete box.dataset.workflow; else box.dataset.workflow = workflow;
    box.optionList = options;
    box.hidden = hidden;
  }
  ({ imagesShown, mediaShown, sourcesShown, sourceSize, paint, videoMegapixels, videoBase, videoMadeAt,
    videoOffMp, videoLatentWas, imageLeastModel, imageDefaulted, imageStep, imageMadeAt, imageOffMp, imageUpscaleWas, imageShown } = state.runtime);
  const apply = () => {
    for (const [side, id] of Object.entries(SIDE_FORMS)) for (const [key, el] of draftFields($(id))) {
      const saved = state.forms[side].get(key);
      if (!saved) continue;
      if (saved.files) {
        const files = new DataTransfer();
        saved.files.forEach(file => files.items.add(file));
        el.files = files.files;
      } else if (['checkbox', 'radio'].includes(el.type)) el.checked = saved.checked;
      else el.value = saved.value;
    }
  };
  apply();
  Object.values(SIDE_SYNC).forEach(sync => sync());
  apply();
  const epoch = workspaceEpoch;
  for (const box of imageBoxes()) box.querySelector('img').onload = () => { if (epoch === workspaceEpoch) syncSize(); };
  const firstSource = sourceBoxes()[0];
  const preview = firstSource?.querySelector('input').files.length ? firstSource.querySelector('img') : null;
  if (preview) {
    preview.onload = () => {
      if (epoch !== workspaceEpoch) return;
      sourceSize = [preview.naturalWidth, preview.naturalHeight];
      syncImageForm();
    };
    if (preview.naturalWidth) preview.onload();
  }
  ({ queueEdit, queueUpscaleEdit, shotsRun, shotsDirty, promptField, generatedEdit, promptEditorOriginal, promptEditorEnhanced, promptEditorModel } = state);
  for (const side of Object.keys(SIDE_FORMS)) {
    delete presetPicked[side];
    if (state.presetPicked[side]) presetPicked[side] = state.presetPicked[side];
    syncPresets(side);
    syncPromptBox($(PROMPT_FIELDS[side]));
    keepPrompt(side);
    if (side !== 'shorts') syncPromptWriter(side);
  }
  $('promptEditorText').value = state.editorText;
  restorePresetEditors(state.presetEditors);
  $('areasHint').textContent = state.areasHint;
  setPromptEditorBusy(false);
  for (const [id, hidden] of state.editorVisibility) $(id).hidden = hidden;
  for (const [id, text] of state.editorLabels) $(id).textContent = text;
  queueEditLabel();
  setPipeline(state.pipeline, false, true);
  showFormError('');
  $('formNote').hidden = true;
  if (lastStatus) reconcileQueueEdits(lastStatus.queue, queueEdit, queueUpscaleEdit);
  for (const id of state.openDialogs) {
    if (id === 'paintDialog') openPaint(); else $(id).showModal();
  }
  if (queueUpscaleEdit && state.upscaleDraft) {
    openUpscaleSettings(state.upscaleDraft.method, queueUpscaleEdit);
    for (const [id, value] of state.upscaleDraft.values) $(id).value = value;
    showUpscaleTarget();
  }
}
function switchDraftWorkspace(on) {
  if (!emptyDraft) return;
  if (paint && $('paintDialog').open) {
    const canvas = paint.canvas;
    canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
    canvas.getContext('2d').drawImage($('paintCanvas'), 0, 0);
  }
  draftWorkspaces.set(privateMode, captureDraft());
  workspaceEpoch++;
  planRequest++;
  clearTimeout(planTimer);
  plan = null;
  for (const id of ['estimateTotal', 'estimateDetail', 'estimateContinues', 'goBarEta']) {
    $(id).textContent = '';
    $(id).removeAttribute('title');
  }
  $('estimateContinues').hidden = true;
  $('paintStage').classList.remove('busy');
  $('upscaleCancel').disabled = $('upscaleGo').disabled = false;
  paintPointers.clear();
  painting = paintTap = paintPinch = paintPan = null;
  paintResting = false;
  promptWriting = null;
  setPromptEditorBusy(false);
  for (const dialog of document.querySelectorAll('dialog[open]:not(#settingsDialog):not(#themeDialog)')) {
    dialog.querySelectorAll('video, audio').forEach(media => media.pause());
    dialog.close();
  }
  stopChoosing();
  viewing = viewerCollection = null;
  for (const side of ['video', 'image']) {
    const box = $(side + 'PromptWriting');
    box.classList.remove('busy');
    box.setAttribute('aria-busy', 'false');
    $(PROMPT_FIELDS[side]).readOnly = false;
    $(side === 'video' ? 'writeVideoPrompt' : 'writeImagePrompt').classList.remove('working');
    $(side + 'PromptProgress').hidden = $(side + 'PromptEta').hidden = $(side + 'PromptWriteError').hidden = true;
  }
  privateMode = on;
  restoreDraft(draftWorkspaces.get(on) || { ...emptyDraft, pipeline });
}
function renderPrivate(on) {
  if (typeof on !== 'boolean') return;
  if ((privateChanging || submitting) && on !== privateMode) return;
  const was = privateMode;
  if (on !== was) switchDraftWorkspace(on);
  privateMode = on;
  document.body.classList.toggle('private-mode', on);
  $('privateMode').checked = on;
  $('privateToggle').classList.toggle('on', on);
  $('privateToggle').setAttribute('aria-pressed', String(on));
  $('privateToggle').title = `Private mode: ${on ? 'on' : 'off'}`;
  // Either way the NSFW view follows: on with it, and off with it, so nothing NSFW is left in Output or Finished.
  if (on !== was) resetOutputView();
}
async function setPrivate(on) {
  if (privateChanging) return;
  if (submitting) {
    settingsNote('Wait for the current submission to finish before switching modes.', true);
    renderPrivate(privateMode);
    return;
  }
  privateChanging = true;
  $('privateMode').disabled = true;
  $('privateToggle').setAttribute('aria-disabled', 'true');
  try {
    const response = await fetch('/api/private', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on }) });
    const body = await response.json();
    if (!response.ok || !body.ok || typeof body.on !== 'boolean') {
      settingsNote(body.error || 'Could not change Private mode.', true);
      renderPrivate(privateMode);
      return;
    }
    privateChanging = false;
    renderPrivate(body.on);
    resumePolling();
  } catch (e) { settingsNote('Could not reach the panel.', true); renderPrivate(privateMode); }
  finally {
    privateChanging = false;
    $('privateMode').disabled = false;
    $('privateToggle').setAttribute('aria-disabled', 'false');
    renderPrivate(privateMode);
  }
}
$('privateMode').addEventListener('change', () => setPrivate($('privateMode').checked));
// The key in the top bar: Private mode on and off, as its Settings checkbox does.
$('privateToggle').addEventListener('click', e => { e.preventDefault(); setPrivate(!privateMode); });
// Output opens on the NSFW view in Private mode, and off it otherwise.
function resetOutputView() {
  const wanted = privateMode && pipeline !== 'shorts';
  if (nsfwView === wanted) return;
  nsfwView = wanted;
  redrawFiltered();
}
function showPage(page) {
  if (page === 'output' && document.body.dataset.page !== 'output') {
    holdOutput();
    resetOutputView();
  }
  document.body.dataset.page = page;
  if (page === 'output') placeKindsThumb();
  try { sessionStorage.setItem(PAGE_KEY, page); } catch (e) {}
  if (!WIDE.matches) window.scrollTo(0, 0);
  markJump();
}
// Each side's colour, for the menu's dots.
// The sides' colours as the stylesheet has them (:root), for the menus' dots and the running job's colour.
const SIDE_COLOURS = { shorts: 'var(--c-shorts)', video: 'var(--c-video)', image: 'var(--c-image)' };
// Tapped again: Status offers what opens over it (Finished, the log, Quota); Generate, the other sides; Output, a
// shortcut to what it shows, in a word.
const SIDE_PAGES = ['status', 'generate', 'output'];
// Shorts on top, then Videos and Images; Both at the bottom, in Output's violet.
const OUTPUT_SHORTCUTS = { shorts: ['Shorts', SIDE_COLOURS.shorts], video: ['Videos', SIDE_COLOURS.video], image: ['Images', SIDE_COLOURS.image], both: ['Both', 'var(--shared)'] };
// The side Generate was on before Shorts, to go back to when Output leaves Shorts.
let madeSide = 'image';
function openSideMenu(link) {
  const menu = $('sideMenu');
  const dot = colour => `<span class="side-dot" style="background:${colour}"></span>`;
  if (link.dataset.page === 'status') {
    // Status, tapped again: what opens over it.
    const finished = $('finishedCount').textContent;
    menu.innerHTML = [['finished', `Finished${finished ? ` (${finished})` : ''}`], ['log', 'Log'], ['quota', 'Quota']].map(([which, name]) =>
      `<button type="button" role="menuitem" data-panel="${which}">${dot('var(--shared)')}${name}</button>`).join('');
  } else if (link.dataset.page === 'output') {
    const here = pipeline === 'shorts' ? 'shorts' : outputKind;
    menu.innerHTML = Object.entries(OUTPUT_SHORTCUTS).filter(([kind]) => kind !== here).map(([kind, [name, colour]]) =>
      `<button type="button" role="menuitem" data-output-kind="${kind}">${dot(colour)}${name}</button>`).join('');
  } else {
    menu.innerHTML = Object.keys(SIDE_NAMES).filter(side => side !== pipeline).map(side =>
      `<button type="button" role="menuitem" data-side="${side}">${dot(SIDE_COLOURS[side])}${SIDE_NAMES[side]}</button>`).join('');
  }
  menu.classList.remove('closing');
  menu.hidden = false;
  // Over the button it came from, at least as wide.
  menu.style.minWidth = `${link.offsetWidth}px`;
  menu.style.left = `${Math.max(8, Math.min(link.offsetLeft, $('stick').offsetWidth - menu.offsetWidth - 8))}px`;
  menu.style.bottom = `${$('stick').offsetHeight - link.offsetTop + 6}px`;
  link.setAttribute('aria-expanded', 'true');
}
function closeSideMenu() {
  const menu = $('sideMenu');
  if (menu.hidden || menu.classList.contains('closing')) return;
  JUMPS.forEach(a => a.removeAttribute('aria-expanded'));
  menu.classList.add('closing');
  setTimeout(() => { if (menu.classList.contains('closing')) { menu.hidden = true; menu.classList.remove('closing'); } }, 150);
}
$('jump').addEventListener('click', e => {
  const link = e.target.closest && e.target.closest('a');
  if (!link || WIDE.matches) return;  // A desktop scrolls there instead
  e.preventDefault();
  const page = link.dataset.page;
  if (choosingFor && page !== 'output') {
    backToGenerate(choosingFor.side);
    stopChoosing();
    if (page === 'generate') return;
  }
  if (page === document.body.dataset.page && SIDE_PAGES.includes(page)) {
    if ($('sideMenu').hidden || $('sideMenu').classList.contains('closing')) openSideMenu(link); else closeSideMenu();
    return;
  }
  closeSideMenu();
  showPage(page);
});
$('sideMenu').addEventListener('click', e => {
  const choice = e.target.closest && e.target.closest('[data-side], [data-output-kind], [data-panel]');
  if (!choice) return;
  closeSideMenu();
  if (choice.dataset.panel) { openPanel(choice.dataset.panel); return; }
  const kind = choice.dataset.outputKind;
  if (!kind) setPipeline(choice.dataset.side);
  else if (kind === 'shorts') setPipeline('shorts');
  else {
    // Out of Shorts: Generate goes back to the side it was on, as Shorts is its own on both pages.
    if (pipeline === 'shorts') setPipeline(madeSide);
    setOutputKind(kind);
  }
  showPage(document.body.dataset.page);
});
// A tap anywhere else, or Escape, puts it away.
document.addEventListener('click', e => {
  if (!$('sideMenu').hidden && !(e.target.closest && (e.target.closest('#sideMenu') || e.target.closest('#jump')))) closeSideMenu();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSideMenu(); });
let desktopGenerateActive = false;
function markJump() {
  const line = 16;
  // A desktop lights the last section scrolled past, in the page's order rather than the footer's.
  const top = a => $(a.hash.slice(1)).getBoundingClientRect().top;
  const here = WIDE.matches ? JUMPS.filter(a => top(a) <= line).sort((a, b) => top(a) - top(b)).pop() || JUMPS[0]
    : JUMPS.find(a => a.dataset.page === document.body.dataset.page) || JUMPS[0];
  if (WIDE.matches) {
    const generate = !!here && here.hash === '#optionsCard';
    desktopGenerateActive = generate;
  } else desktopGenerateActive = false;
  // In Generate (its page on a phone, scrolled to it on a desktop): what sits above every page takes the side's colour.
  document.body.classList.toggle('in-generate', WIDE.matches ? desktopGenerateActive : document.body.dataset.page === 'generate');
  JUMPS.forEach(a => a.classList.toggle('active', a === here));
  $('goBar').hidden = !WIDE.matches && document.body.dataset.page !== 'generate';
  syncStrips();
}
// The footer's height, once its bars have eased in or out.
$('stick').addEventListener('transitionend', () => document.documentElement.style.setProperty('--head', `${$('stick').offsetHeight}px`));
window.addEventListener('scroll', markJump, { passive: true });

for (const section of document.querySelectorAll('details.section')) section.addEventListener('toggle', markJump);
