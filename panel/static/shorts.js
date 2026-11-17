// --- Workflows saved in ComfyUI ---
let workflowsFor = null, shortsTakes = {}, shortsH3 = {};
function rememberedWorkflow() {
  try { return (JSON.parse(draftRead(STORE_KEY)) || {}).workflow || ''; } catch (e) { return ''; }
}
async function loadWorkflows(fresh) {
  // The list kept from last time at once (workflowList), drawn again if the one asked for behind it differs.
  let data = fresh && Array.isArray(fresh.workflows) ? fresh : null;
  if (!data) try { data = await workflowList('shorts', loadWorkflows); } catch (e) { return; }
  const select = $('workflow');
  const key = JSON.stringify(data);
  // Writing the options closes the list, and this also runs as it opens.
  if (select.dataset.key === key) return;
  const wanted = select.dataset.key ? select.value : startingWorkflow('shorts', rememberedWorkflow);
  select.dataset.key = key;
  const none = !data.online && !data.workflows.length;
  select.innerHTML = '<option value="">LTX23_I2V_T2V_shorts</option>' + data.workflows.map(w =>
    `<option value="${esc(w.name)}">${esc(w.label)}</option>`).join('')
    + (none ? '<option disabled>Yours appear once ComfyUI is on</option>' : '');
  if (data.workflows.some(w => w.name === wanted)) select.value = wanted;
  shortsTakes = Object.fromEntries(data.workflows.map(w => [w.name, w.takes]));
  shortsH3 = Object.fromEntries(data.workflows.map(w => [w.name, !!w.openh3]));
  setGuides('shorts', data);
  syncForm();
  applyDefaultPreset('shorts');
}
$('workflow').addEventListener('focus', loadWorkflows);

function syncForm() {
  syncGuideLink('shorts');
  $('avatarOpts').classList.toggle('hidden', $('avatar_clips').value === '0');
  $('workflowBox').classList.toggle('hidden', $('avatar_clips').value === '0');
  $('clipsSlider').classList.toggle('hidden', $('avatar_clips').value !== 'auto');
  $('avatar_style').disabled = !!$('workflow').value;
  const avatars = $('avatar_clips').value !== '0';
  syncH3Controls('shorts', avatars && !!shortsH3[$('workflow').value]);
  syncOptions('shortsOptions', 'shortsOptionsBox', avatars ? (shortsTakes[$('workflow').value] || {}).options || [] : [], $('workflow').value);
  syncSliders();
}
$('formShorts').addEventListener('change', () => { syncForm(); saveForm(); });

// --- Avatar sliders ---
// A typical video, for the estimate of how much of it is her.
const TYPICAL_VIDEO = 50, TYPICAL_SCENE = 5.5;
function syncRange(id, moved) {
  const box = $(id);
  const [low, high] = box.querySelectorAll('input');
  // The thumbs push each other along instead of crossing.
  if (+low.value > +high.value) {
    if (moved === high) low.value = high.value; else high.value = low.value;
  }
  const at = input => (input.value - input.min) / (input.max - input.min) * 100;
  box.querySelector('.fill').style.left = `${at(low)}%`;
  box.querySelector('.fill').style.right = `${100 - at(high)}%`;
  return [+low.value, +high.value];
}
function syncSliders(moved) {
  const [fewest, most] = syncRange('clipsRange', moved);
  const [shortest, longest] = syncRange('secondsRange', moved);
  $('clipsText').textContent = fewest === most ? `${most}` : `${fewest}–${most}`;
  $('secondsText').textContent = shortest === longest ? `${longest} s` : `${shortest}–${longest} s`;

  const layout = $('avatar_clips').value;
  const [low, high] = layout === 'auto' ? [fewest, most] : [+layout, +layout];
  const least = Math.round(low * Math.min(shortest, TYPICAL_SCENE));
  const greatest = Math.round(high * Math.min(longest, TYPICAL_SCENE));
  const share = s => Math.min(100, Math.round(100 * s / TYPICAL_VIDEO));
  const span = (a, b) => a === b ? `${a}` : `${a}–${b}`;
  $('avatarMix').innerHTML = `<b>About ${span(share(least), share(greatest))}% presenter</b>, the rest stock footage.`;
}
for (const id of ['clipsRange', 'secondsRange']) {
  $(id).addEventListener('input', e => syncSliders(e.target));
}
