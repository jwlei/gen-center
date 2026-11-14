// --- The Workflow heading's hint icon opens its model guide (core/model_guide.py). ---
const GUIDE_SELECTS = { shorts: 'workflow', video: 'videoWorkflow', image: 'imageWorkflow' };
const workflowGuides = { shorts: {}, video: {}, image: {} }, builtInGuides = { shorts: null, video: null, image: null }, guideCache = {};
// Without a known model, the icon retains the workflow's contextual help.
function syncGuideLink(side) {
  const link = $(`${side}GuideLink`), chosen = $(GUIDE_SELECTS[side]).value;
  const guide = workflowGuides[side][chosen] || (chosen ? null : builtInGuides[side]);
  link.dataset.guide = guide ? guide.key : '';
  link.title = guide ? `About ${guide.title}` : 'About workflow';
  link.setAttribute('aria-label', link.title);
  link.setAttribute('aria-controls', guide ? 'modelGuide' : `${side}WorkflowHelp`);
  if (guide) {
    link.setAttribute('aria-haspopup', 'dialog');
    link.removeAttribute('aria-expanded');
    $(`${side}WorkflowHelp`).hidden = true;
  } else {
    link.removeAttribute('aria-haspopup');
    link.setAttribute('aria-expanded', String(!$(`${side}WorkflowHelp`).hidden));
  }
}
function setGuides(side, data) {
  workflowGuides[side] = Object.fromEntries(data.workflows.filter(w => w.guide).map(w => [w.name, w.guide]));
  builtInGuides[side] = data.built_in_guide || null;
  syncGuideLink(side);
}
// Short lines under headings that fold, so a phone reads it a part at a time; the first two parts start open.
function guideHtml(guide) {
  const list = items => `<ul>${items.map(item => `<li>${esc(item)}</li>`).join('')}</ul>`;
  return `<p class="model-guide-lead">${esc(guide.lead)}</p>`
    + `<dl class="guide-facts">${guide.facts.map(([what, value]) => `<dt>${esc(what)}</dt><dd>${esc(value)}</dd>`).join('')}</dl>`
    + guide.sections.map((part, number) => `<details${number < 2 ? ' open' : ''}><summary>${esc(part.title)}</summary>${list(part.items)}</details>`).join('')
    + (guide.faq.length ? `<details><summary>FAQ</summary>${guide.faq.map(([question, answer]) => `<details class="guide-q"><summary>${esc(question)}</summary><p>${esc(answer)}</p></details>`).join('')}</details>` : '')
    + `<details class="guide-sources"><summary>Sources</summary><ul>${guide.sources.map(([name, url]) => `<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(name)}</a></li>`).join('')}</ul></details>`;
}
async function openModelGuide(key, context = '') {
  let guide = guideCache[key];
  if (!guide) {
    try { guide = (await (await fetch(`/api/model-guide/${encodeURIComponent(key)}`)).json()).guide; } catch (e) { guide = null; }
    if (!guide) { alert('Could not open the guide.'); return; }
    guideCache[key] = guide;
  }
  $('modelGuideTitle').textContent = guide.title;
  $('modelGuideBody').innerHTML = (context ? `<p class="hint">${esc(context)}</p>` : '') + guideHtml(guide);
  $('modelGuideBody').scrollTop = 0;
  if (!$('modelGuide').open) $('modelGuide').showModal();
}
for (const side of Object.keys(GUIDE_SELECTS)) {
  $(`${side}GuideLink`).addEventListener('click', e => {
    const key = e.currentTarget.dataset.guide;
    if (!key) return;
    const hint = $(`${side}WorkflowHint`);
    openModelGuide(key, hint.hidden ? '' : hint.textContent);
  });
  $(GUIDE_SELECTS[side]).addEventListener('change', () => syncGuideLink(side));
}
$('connectGuideLink').addEventListener('click', e => openModelGuide(e.currentTarget.dataset.guide));
$('modelGuideClose').addEventListener('click', () => $('modelGuide').close());
// A tap outside it closes it, as the other boxes over the page do.
$('modelGuide').addEventListener('click', e => {
  if (e.target !== $('modelGuide')) return;
  const box = $('modelGuide').getBoundingClientRect();
  if (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom) $('modelGuide').close();
});
