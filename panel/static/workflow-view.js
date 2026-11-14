// --- Log filters and the workflow view ---
{
  const apply = detailed => {
    logDetailed = detailed;
    $('logDetailed').setAttribute('aria-pressed', String(detailed));
    $('logSummary').setAttribute('aria-pressed', String(!detailed));
    renderLog(logLines, true);
  };
  if (localStorage.getItem('comfyui-auto-gen.logDetailed') === '1') apply(true);
  for (const [id, detailed] of [['logSummary', false], ['logDetailed', true]]) {
    $(id).addEventListener('click', () => {
      if (logDetailed === detailed) return;
      apply(detailed);
      try { localStorage.setItem('comfyui-auto-gen.logDetailed', detailed ? '1' : '0'); } catch (e) {}
    });
  }
}
for (const [id, cls, onWhenPressed] of [['logComfy', 'hide-comfy', false], ['logProblems', 'problems-only', true]]) {
  const saved = localStorage.getItem(`comfyui-auto-gen.${id}`);
  const apply = pressed => {
    $(id).setAttribute('aria-pressed', String(pressed));
    $('logPanes').classList.toggle(cls, pressed === onWhenPressed);
    if (autoScroll) $('log').scrollTop = $('log').scrollHeight;
  };
  if (saved !== null) apply(saved === '1');
  $(id).addEventListener('click', () => {
    const pressed = $(id).getAttribute('aria-pressed') !== 'true';
    apply(pressed);
    try { localStorage.setItem(`comfyui-auto-gen.${id}`, pressed ? '1' : '0'); } catch (e) {}
  });
}
let shownWorkflow = null;
async function showWorkflow() {
  $('workflowTitle').textContent = 'Workflow';
  $('workflowNote').textContent = 'Loading…';
  $('workflowOptions').innerHTML = $('workflowNodes').innerHTML = '';
  if (!$('workflowDialog').open) $('workflowDialog').showModal();
  let reply;
  try {
    const response = await fetch('/api/run-workflow');
    reply = await response.json();
  } catch (e) { reply = { error: 'The panel could not be reached.' }; }
  if (reply.error) { $('workflowNote').textContent = reply.error; shownWorkflow = null; return; }
  shownWorkflow = reply;
  $('workflowTitle').textContent = reply.name;
  const changed = reply.options.filter(option => option.changed).length;
  $('workflowNote').textContent = `${reply.nodes.length} nodes, as sent to ComfyUI${reply.running ? '' : ' (the last run)'}. `
    + (reply.options.length ? `${changed} of its ${reply.options.length} options set away from the workflow as saved.` : 'It has no options of its own.');
  $('workflowOptions').innerHTML = reply.options.map(option =>
    `<dt>${esc(option.label)}</dt><dd>${esc(option.value)}${option.changed ? ' · changed' : ''}</dd>`).join('');
  $('workflowNodes').innerHTML = reply.nodes.map(node =>
    `<details><summary>${esc(node.id)} · ${esc(node.type)}<small>${Object.keys(node.inputs).length} inputs</small></summary><dl>${
      Object.entries(node.inputs).map(([name, value]) => `<dt>${esc(name)}</dt><dd>${esc(value)}</dd>`).join('')}</dl></details>`).join('');
}
$('workflowClose').addEventListener('click', () => $('workflowDialog').close());
$('workflowDialog').addEventListener('click', e => { if (e.target === $('workflowDialog')) $('workflowDialog').close(); });
$('workflowExpand').addEventListener('click', () => {
  const all = [...$('workflowNodes').querySelectorAll('details')], open = all.some(el => !el.open);
  for (const el of all) el.open = open;
  $('workflowExpand').textContent = open ? 'Collapse all' : 'Expand all';
});
$('workflowCopy').addEventListener('click', async () => {
  if (!shownWorkflow) return;
  try { await navigator.clipboard.writeText(JSON.stringify(shownWorkflow.api, null, 2)); $('workflowCopy').textContent = 'Copied'; }
  catch (e) { $('workflowCopy').textContent = 'Could not copy'; }
  setTimeout(() => { $('workflowCopy').textContent = 'Copy JSON'; }, 1500);
});
