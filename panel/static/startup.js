{
  // A first visit opens on Status; coming back in the same tab (a reload), on the page it last showed.
  let page = 'status';
  try { page = sessionStorage.getItem(PAGE_KEY) || page; } catch (e) {}
  if (!['status', 'generate', 'output'].includes(page)) page = 'status';
  document.body.dataset.page = page;
}
loadForm();
syncForm();
// New defaults reach a browser that remembered the old ones, once: only these fields, the rest of what it chose stays.
(function newDefaults() {
  const KEY = 'comfyui-auto-gen.defaults', VERSION = '2026-11-07', drop = {
    [VIDEO_STORE_KEY]: ['duration', 'review', 'size_preset', 'clip_seconds'], [IMAGE_STORE_KEY]: ['megapixels', 'review'] };
  try {
    if (localStorage.getItem(KEY) === VERSION) return;
    for (const [store, fields] of Object.entries(drop)) {
      const data = JSON.parse(localStorage.getItem(store) || 'null');
      if (data) { fields.forEach(field => delete data[field]); localStorage.setItem(store, JSON.stringify(data)); }
    }
    localStorage.setItem(KEY, VERSION);
  } catch (e) {}
})();
loadVideoForm();
syncVideoForm();
renderLocalModels();
loadImageForm();
syncImageForm();
{
  let side = PANEL_CONFIG.initial_pipeline;
  if (!side) try { side = localStorage.getItem(PIPELINE_KEY); } catch (e) {}
  setPipeline(side in SIDE_FORMS ? side : 'shorts', false);
}
emptyDraft = captureDraft(true);
for (const [side, id] of Object.entries(PROMPT_FIELDS)) {
  const kept = keptPrompts()[side];
  if (kept && !$(id).value) {
    $(id).value = kept;
    syncPromptBox($(id));
    if (side !== 'shorts') syncPromptWriter(side);
  }
}
renderPrivate(privateMode);
markJump();
wirePresets();
loadPresets();
poll();
setInterval(poll, 2000);
// A phone pauses a page it isn't showing, so catch up as soon as it is shown again.
document.addEventListener('visibilitychange', () => { if (!document.hidden) holdOutput(); });
window.addEventListener('pageshow', holdOutput);
window.addEventListener('focus', resumePolling);
window.addEventListener('online', resumePolling);
