// A choice's options, each said as its label where it has one (a LoRA without .safetensors), sent as its value.
function choiceOptions(option) {
  const labels = option.labels || {}, problems = option.problems || {};
  // One that can't run is shown greyed out, with why.
  return option.choices.map(value => `<option value="${esc(value)}"${value === option.default ? ' selected' : ''}${problems[value] ? ` disabled title="${esc(problems[value])}"` : ''}>${esc(labels[value] ?? value)}</option>`).join('');
}
function visibleLoraOptions(options) {
  if (privateMode) return options;
  const privateName = name => /nsfw|uncensor/i.test(String(name));
  const blocked = new Set();
  const visible = options.map(option => {
    // A file to pick (Model, Text, VAE): the workflow's own stays; with nothing else left to pick, it's shown greyed
    // out in its place, saying why.
    if (option.model) {
      const choices = option.choices.filter(value => value === option.default || !privateName(value));
      return choices.length > 1 ? { ...option, choices }
        : { ...option, choices, problem: option.problem || 'The others installed are only offered in Private mode.' };
    }
    if (option.kind === 'strength' && option.id.startsWith('lora_')
      && (option.private_only || privateName(option.id + ' ' + option.label))) {
      return { ...option, private_only: true, default: '0' };
    }
    if (option.kind !== 'lora_stack' && (option.kind !== 'choice' || !option.id.includes('lora'))) return option;
    const choices = option.choices.filter(value => !privateName(value));
    if (choices.length === option.choices.length) return option;
    if (!choices.length && option.parent) blocked.add(option.parent);
    return { ...option, choices, default: option.kind === 'lora_stack' ? option.default : choices.includes(option.default) ? option.default : choices[0] || '',
      ...(!choices.length ? { problem: 'These LoRAs require Private mode.' } : {}) };
  });
  return visible.filter(Boolean).map(option => blocked.has(option.id)
    ? { ...option, default: '0', problem: 'These LoRAs require Private mode.' } : option);
}
function loraStackRows(box) {
  const input = box.querySelector('[name=opt_additional_loras]');
  const rows = JSON.parse(input.value || '[]');
  if (!Array.isArray(rows) || rows.some(row => !row || typeof row.on !== 'boolean' || typeof row.name !== 'string')) {
    throw new Error('The saved additional LoRAs are invalid. Reset workflow options to clear them.');
  }
  return rows;
}
function renderLoraStack(box) {
  const option = (box.optionList || []).find(option => option.kind === 'lora_stack');
  if (!option) return;
  const stack = box.querySelector('[data-lora-stack]');
  if (!stack) return;
  try {
    const rows = loraStackRows(box);
    for (const row of rows) if (!option.choices.includes(row.name)) row.on = false;
    stack.querySelector('[name=opt_additional_loras]').value = JSON.stringify(rows);
    stack.querySelector('[data-lora-rows]').innerHTML = rows.map((row, index) => {
      const available = option.choices.includes(row.name);
      return `<div class="lora-line lora-extra" data-lora-index="${index}"><label class="check"><input type="checkbox" data-lora-on${row.on && available ? ' checked' : ''}${available ? '' : ' disabled'} aria-label="Enable additional LoRA"></label>`
        + `<select data-lora-name aria-label="Additional LoRA">${available ? '' : '<option value="">Unavailable in this mode</option>'}${choiceOptions({...option, default: row.name})}</select>`
        + `<input type="number" class="option-strength" data-lora-strength min="${option.min}" max="${option.max}" step="${option.step}" value="${esc(row.strength)}" aria-label="Additional LoRA strength">`
        + '<span class="lora-range"></span>'
        + `<button type="button" class="icon-btn" data-remove-lora="${index}" aria-label="Remove additional LoRA">${ICONS.trash}</button></div>`;
    }).join('');
    if (rows.some(row => !option.choices.includes(row.name))) {
      stack.querySelector('[data-lora-rows]').insertAdjacentHTML('beforeend', '<div class="hint">A saved LoRA is unavailable in this mode. Choose another or remove it.</div>');
    }
    syncLoraRanges(box);
  } catch (error) { showFormError(error.message); }
}
// The strength ranges for a LoRA (core/lora_hints.py), by its file's name: { ours, author }, or {} for one it doesn't know.
function loraRange(name) {
  const key = String(name || '').replace(/\\/g, '/').split('/').pop().replace(/\.safetensors$/i, '').toLowerCase();
  return (PANEL_CONFIG.lora_ranges || {})[key] || {};
}
// "0.5–1.5" as [0.5, 1.5].
function rangeBounds(range) {
  const [low, high] = String(range || '').split('–').map(Number);
  return Number.isFinite(low) && Number.isFinite(high) ? [low, high] : null;
}
// Beside each LoRA line's strength: our range for the LoRA chosen on it, and the author's under it.
function syncLoraRanges(root) {
  for (const line of root && root.querySelectorAll ? root.querySelectorAll('.lora-line') : []) {
    const select = line.querySelector('select'), out = line.querySelector('.lora-range');
    if (!out) continue;
    const { ours, author } = select ? loraRange(select.value) : {};
    out.innerHTML = (ours ? `<span class="lora-range-ours">${esc(ours)}</span>` : '') + (author ? `<span class="lora-range-author">${esc(author)}</span>` : '');
    out.title = [ours && `Worth using: ${ours}`, author && `Its author's: ${author}`].filter(Boolean).join('\n');
  }
}
// Another LoRA chosen: its strength brought within our range for it, and the ranges beside it shown.
document.addEventListener('change', e => {
  const line = e.target && e.target.closest && e.target.tagName === 'SELECT' && e.target.closest('.lora-line');
  if (!line) return;
  const bounds = rangeBounds(loraRange(e.target.value).ours), strength = line.querySelector('.option-strength');
  if (bounds && strength && strength.value !== '') {
    const value = Number(strength.value), within = Math.min(bounds[1], Math.max(bounds[0], value));
    if (within !== value) {
      strength.value = String(within);
      strength.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }
  syncLoraRanges(line.parentNode);
});
function rememberLoraStack(box) {
  const stack = box.querySelector('[data-lora-stack]');
  if (!stack) return;
  stack.querySelector('[name=opt_additional_loras]').value = JSON.stringify([...stack.querySelectorAll('[data-lora-index]')].map(row => ({
    on: row.querySelector('[data-lora-on]').checked, name: row.querySelector('[data-lora-name]').value,
    strength: row.querySelector('[data-lora-strength]').value,
  })));
}
// The image form's comparisons: the LoRA one's last count (syncLoraTests), and the switches of each.
let imageLoraTest = { on: false, count: 0 };
const IMAGE_LORA_TESTS = ['imageLoraStrengthTest', 'imageLoraStyleTest'], IMAGE_WORKFLOW_TESTS = ['imageWorkflowTestT2i', 'imageWorkflowTestEdit'];
// The files it runs (core/file_tests.py): each switch, and the setting it compares.
const IMAGE_FILE_TESTS = { imageModelTest: 'model_file', imageEncoderTest: 'text_encoder_file', imageVaeTest: 'vae_file' };
const IMAGE_TESTS = [...IMAGE_LORA_TESTS, ...IMAGE_WORKFLOW_TESTS, 'imageLlmTest', ...Object.keys(IMAGE_FILE_TESTS)];
let imageFileTest = { on: false, count: 1 };
// A comparison of the files it runs: each switch only where the workflow has another of that file installed, and
// every combination of those ticked, the LoRA comparison in each.
function syncFileTests(options) {
  let count = 1, on = false;
  const names = [];
  for (const [id, optionId] of Object.entries(IMAGE_FILE_TESTS)) {
    const option = options.find(o => o.id === optionId), choices = (option && option.choices) || [];
    const box = $(id);
    box.disabled = choices.length < 2;
    if (box.disabled) box.checked = false;
    const line = box.closest && box.closest('label');
    if (line) line.hidden = box.disabled;
    if (box.checked) { on = true; count *= choices.length; names.push(`${choices.length} ${option.label.toLowerCase()}s`); }
  }
  $('imageFileTests').hidden = Object.keys(IMAGE_FILE_TESTS).every(id => $(id).disabled);
  imageFileTest = { on, count };
  // As many as a set of your own prompt takes: a comparison is your prompt as written.
  const lora = imageLoraTest.on ? imageLoraTest.count : 1, total = count * lora, most = Number($('imageCount').dataset.most) || 50;
  $('imageFileTestHint').textContent = !on
    ? ''
    : total > most ? `That makes ${total} images: compare fewer at once (up to ${most}).`
    : `${total} images in one set: ${names.join(' x ')}${lora > 1 ? `, with the LoRA comparison in each` : ''}, on one seed and your prompt as written.`;
}
function syncLoraTests(boxId, options) {
  const side = boxId === 'imageOptionsBox' ? 'image' : boxId === 'videoOptionsBox' ? 'video' : null;
  if (!side) return;
  const box = $(side + 'LoraTests'), strength = $(side + 'LoraStrengthTest'), style = $(side + 'LoraStyleTest');
  const names = options.find(option => option.id === 'lora_name');
  const limit = options.find(option => option.id === 'lora_strength');
  const available = !!names?.choices.length;
  // With a workflow comparison, a LoRA comparison runs on each workflow, with its own style LoRAs: the form's
  // workflow having none doesn't stop it.
  const comparing = side === 'image' && !!imageWorkflowTest();
  strength.disabled = style.disabled = !(available || comparing) || (side === 'video' && !!queueEdit);
  const enabled = (available || comparing) && (strength.checked || style.checked);
  const step = $(side + 'LoraTestStep');
  step.min = step.step = String(limit?.step || 0.05);
  step.max = String(Math.min(2, limit?.max || 2));
  step.disabled = !available || !strength.checked;
  for (const button of box.querySelectorAll('[data-lora-step]')) button.disabled = step.disabled;
  $(side === 'image' ? 'imageReview' : 'review').disabled = enabled;
  const increment = Number(step.value), units = increment / Number(step.step);
  const valid = Number.isFinite(increment) && increment > 0 && increment <= Number(step.max)
    && Math.abs(units - Math.round(units)) < 1e-8;
  const tested = style.checked ? names?.choices || [] : [loraSelected(names, side)];
  const count = strength.checked && valid ? strengthImages(tested, increment, Number(step.max)) : tested.length;
  if (side === 'image') {
    imageLoraTest = { on: enabled, count };
    syncImageAmount();
  }
  box.querySelector('[data-lora-test-hint]').textContent = comparing
    ? (enabled ? 'On each compared workflow, with its own style LoRAs and strengths; one with none runs once.' : 'Add a LoRA comparison to each compared workflow.')
    : !available ? 'No style LoRAs are available for this workflow in this mode.'
    : enabled && strength.checked && !valid ? `Choose a strength increment in multiples of ${step.step}, up to ${step.max}.`
    : enabled ? `${count} ${side === 'image' ? 'images in one set' : 'separate complete videos'}. Same seed and current prompt as written; added LoRAs stay fixed. Strength tests run over each LoRA's range, ours or else the author's, in steps of the increment; one with neither from the increment to 2.0.`
    : 'For the primary LoRA.';
}
// The image form's comparisons: the LoRA one (syncLoraTests) and the workflow ones, all text to image or all edit.
// A workflow comparison: each usable workflow of its kind, as the server picks them (core/workflow_tests.py).
function imageWorkflowTest() {
  const kind = $('imageWorkflowTestT2i').checked ? 't2i' : $('imageWorkflowTestEdit').checked ? 'edit' : null;
  if (!kind) return null;
  const images = chosenSources();
  const workflows = imageWorkflowList.filter(t => kind === 't2i' ? t.max_images === 0
    : 1 <= t.min_images && t.min_images <= images && images <= t.max_images);
  return { kind, images, workflows: workflows.length, count: workflows.reduce((sum, t) => sum + loraImagesOn(t), 0) };
}
// How many images a LoRA comparison makes on one compared workflow, with its own style LoRAs, as the server counts
// them (core/workflow_tests.py): 1 when none is asked for, or it has none to compare at that increment.
function loraImagesOn(takes) {
  const style = $('imageLoraStyleTest').checked, strength = $('imageLoraStrengthTest').checked;
  if (!style && !strength) return 1;
  const options = visibleLoraOptions((takes.options || []).filter(option => !option.role));
  const names = options.find(option => option.id === 'lora_name'), limit = options.find(option => option.id === 'lora_strength');
  if (!names || names.problem || !names.choices.length || !limit) return 1;
  const tested = style ? names.choices : [loraSelected(names)];
  if (!strength) return tested.length;
  const step = Number($('imageLoraTestStep').value), top = Math.min(2, limit.max || 2), units = step / (limit.step || 0.05);
  if (!(step > 0 && step <= top && Math.abs(units - Math.round(units)) < 1e-8)) return 1;
  return strengthImages(tested, step, top);
}
// The LoRA the form has, of those it offers.
function loraSelected(names, side = 'image') {
  const form = $(side === 'video' ? 'formVideo' : 'formImage');
  const box = form && form.querySelector && form.querySelector('[name="opt_lora_name"]');
  return (box && box.value) || (names && names.default) || '';
}
// How many images a strength test makes over these LoRAs, as the server makes them (core/lora_tests.py): each from the
// increment up to the top of our range for it (core/lora_hints.py), the author's where there's none of ours, or the most
// a strength goes where neither is known.
function strengthImages(names, step, most) {
  return names.reduce((sum, name) => {
    const range = loraRange(name), bounds = rangeBounds(range.ours) || rangeBounds(range.author);
    // From the bottom of its range to its top; from the increment to the most a strength goes where it has none.
    const start = bounds ? bounds[0] : step, top = bounds ? Math.min(most, bounds[1]) : most;
    return sum + Math.max(1, Math.floor((top - start) / step + 1e-9) + 1);
  }, 0);
}
// An LLM comparison: Gemini when it has a key, and each local model, those that can't see an image left out when there
// are images, as the server picks them (panel/image.py compared_llms).
function imageLlmTest() {
  if (!$('imageLlmTest').checked) return null;
  const images = chosenSources();
  const gemini = [...$('imageLlm').options].some(option => option.value === 'gemini' && !option.disabled);
  return { images, count: (gemini ? 1 : 0) + (LOCAL_MODELS || []).filter(model => !images || model.vision).length };
}
// A comparison makes its own number of images: Amount shows it, locked, and gets your own back when none is on (the
// change listener below). It can't wait to read the prompts first either.
function syncImageAmount() {
  const llms = imageLlmTest(), test = imageWorkflowTest();
  // A LoRA comparison and one of the files it runs go together: every LoRA variation with every file.
  const lora = imageLoraTest.on ? imageLoraTest.count : 1, files = imageFileTest.on ? imageFileTest.count : 1;
  const on = !!llms || !!test || imageLoraTest.on || imageFileTest.on, count = llms ? llms.count : test ? test.count : lora * files;
  const amount = $('imageCount');
  if (on) {
    if (!('own' in amount.dataset)) amount.dataset.own = amount.disabled ? '1' : amount.value;
    if (count) amount.value = count;
  } else delete amount.dataset.own;
  amount.disabled = on;
  $('imageReview').disabled = on;
  $('imageLlmTestHint').textContent = !llms
    ? ''
    : !llms.count ? 'No prompt model can write it: add a Gemini key or a local model.'
    : `${llms.count} images in one set: each prompt model writes one prompt from yours${llms.images ? ' (those that can see the image)' : ''}, on one seed and this workflow.`;
  const what = test && (test.kind === 't2i' ? 'text-to-image' : 'edit');
  $('imageWorkflowTestHint').textContent = !test
    ? ''
    : test.kind === 'edit' && !test.images ? 'Choose the image to edit first.'
    : test.kind === 't2i' && test.images ? 'Text to image takes no image: remove it.'
    : !test.count ? `No ${what} workflow can run.`
    : `${test.count} images in one set: each of the ${test.workflows} ${what} workflows at its own default settings${test.count > test.workflows ? ', with the LoRA comparison on each that has a style LoRA' : ''}, the same seed and your prompt as written.`;
}
// One workflow comparison at a time, a LoRA comparison with it if you like; an LLM comparison writes its prompts, so
// it goes with neither (they use yours as written). All of them off, Amount has your own number back (before the
// form's change handler syncs).
$('imageHow').addEventListener('change', e => {
  const id = e.target && e.target.id;
  const fileTests = Object.keys(IMAGE_FILE_TESTS);
  if (e.target.checked && IMAGE_WORKFLOW_TESTS.includes(id)) {
    // Each compared workflow at its own defaults: its files are its own, not compared.
    for (const other of [...IMAGE_WORKFLOW_TESTS, 'imageLlmTest', ...fileTests]) if (other !== id) $(other).checked = false;
  } else if (e.target.checked && IMAGE_LORA_TESTS.includes(id)) {
    $('imageLlmTest').checked = false;
  } else if (e.target.checked && fileTests.includes(id)) {
    for (const other of [...IMAGE_WORKFLOW_TESTS, 'imageLlmTest']) $(other).checked = false;
  } else if (e.target.checked && id === 'imageLlmTest') {
    for (const other of [...IMAGE_WORKFLOW_TESTS, ...IMAGE_LORA_TESTS, ...fileTests]) $(other).checked = false;
  }
  syncFileTests(imageTakes().options || []);
  const amount = $('imageCount');
  if (!IMAGE_TESTS.some(other => $(other).checked) && 'own' in amount.dataset) amount.value = amount.dataset.own;
});
// What a switch has under it shows while it's on.
function syncBelow(box) {
  for (const under of box.querySelectorAll ? box.querySelectorAll('[data-below]') : []) {
    const toggle = box.querySelector(`input[type=checkbox][name="${under.dataset.below}"]`);
    if (toggle) under.classList.toggle('open', toggle.checked);
  }
}
// The chosen workflow's own options (core/workflow_options.py). A checkbox sends a hidden 0 before its own 1, so leaving
// it unticked still says so. Drawn again only for another workflow, so what you set stays while you fill in the rest.
function imageOptionHtml(option, all) {
  const name = `opt_${option.id}`, locked = option.problem ? ' disabled' : '';
  if (option.kind === 'strength' && option.private_only && !privateMode) {
    return `<input type="hidden" name="${esc(name)}_on" value="0">`;
  }
  if (option.kind === 'lora_stack') {
    return `<div data-lora-stack><input type="hidden" name="opt_additional_loras" value="${esc(option.default)}"><div data-lora-rows></div>`
      + `<button type="button" class="ghost" data-add-lora aria-label="Add another style LoRA" title="Add another style LoRA"${option.choices.length ? '' : ' disabled'}>+</button></div>`;
  }
  const problem = option.problem ? `<div class="hint">Can't be changed: ${esc(option.problem)}</div>` : '';
  // A setting that goes with another follows it, each on a line of its own, as Sampler, Scheduler and CFG do Steps.
  const beside = child => {
    const off = child.problem ? ' disabled' : '';
    const label = `<span class="option-sub">${esc(child.label)}</span>`;
    return `<span class="option-line">${child.kind === 'choice'
      ? `${label}<select name="opt_${esc(child.id)}" aria-label="${esc(child.label)}" title="${esc(child.label)}" class="option-choice"${off}>${choiceOptions(child)}</select>`
      : `${label}<input type="number" class="option-strength" name="opt_${esc(child.id)}" aria-label="${esc(child.label)}" title="${esc(child.label)}" min="${child.min}" max="${child.max}" step="${child.step}" value="${esc(child.default)}"${off}>`}</span>`;
  };
  const group = all.filter(other => other.parent === option.id);
  if (option.parent && all.some(other => other.id === option.parent)) return '';
  if (option.kind === 'group') {
    return `<div class="option-row"><label>${esc(option.label)}</label>${group.map(beside).join('')}${group.find(child => child.problem) ? `<div class="hint">Can't be changed: ${esc(group.find(child => child.problem).problem)}</div>` : ''}</div>`;
  }
  if (option.kind === 'text') {
    return `<label for="opt_${esc(option.id)}">${esc(option.label)}</label>
      <textarea id="opt_${esc(option.id)}" name="${esc(name)}" rows="3" maxlength="4000" data-prompt inputmode="none"${locked}>${esc(option.default)}</textarea>`;
  }
  if (option.kind === 'choice') {
    return `<div class="option-row"><label for="opt_${esc(option.id)}">${esc(option.label)}</label>
      <select id="opt_${esc(option.id)}" name="${esc(name)}" class="option-choice"${locked}>${choiceOptions(option)}</select>${group.map(beside).join('')}</div>`;
  }
  if (option.kind === 'number') {
    return `<div class="option-row"><label for="opt_${esc(option.id)}">${esc(option.label)}</label>
      <input type="number" id="opt_${esc(option.id)}" name="${esc(name)}" min="${option.min}" max="${option.max}" step="${option.step}" value="${esc(option.default)}"${locked}>${group.map(beside).join('')}</div>`;
  }
  if (option.kind === 'switch' && option.below) {
    const under = all.filter(other => other.parent === option.id).map(child => child.kind === 'choice'
      ? `<select name="opt_${esc(child.id)}" aria-label="${esc(child.label)}" title="${esc(child.label)}" class="option-choice"${locked}>${choiceOptions(child)}</select>`
      : `<input type="number" class="option-strength" name="opt_${esc(child.id)}" aria-label="${esc(child.label)}" title="${esc(child.label)}" min="${child.min}" max="${child.max}" step="${child.step}" value="${esc(child.default)}"${locked}>`).join('');
    // Its range worth using beside the strength, and the room the extra LoRAs' trash takes, so the strengths line up.
    return `<div class="lora-line"><label class="check"><input type="hidden" name="${esc(name)}" value="0"><input type="checkbox" name="${esc(name)}" aria-label="${esc(option.label)}" value="1"${option.default === '1' ? ' checked' : ''}${locked}></label>${under}<span class="lora-range"></span><span class="lora-gap" aria-hidden="true"></span></div>`;
  }
  if (option.kind === 'switch' && option.rows) {
    // What goes with it under it, each on a line of its own with its name, folded away until it's ticked (Reduce harshness).
    const on = option.default === '1';
    return `<label class="check"><input type="hidden" name="${esc(name)}" value="0"><input type="checkbox" name="${esc(name)}" value="1"${on ? ' checked' : ''}${locked}>
      <span>${esc(option.label)}${problem}</span></label>`
      + `<div class="option-reveal option-rows${on ? ' open' : ''}" data-below="${esc(name)}"><div class="option-reveal-in">${group.map(child => withHint(child, optionRowHtml(child))).join('')}</div></div>`;
  }
  if (option.kind === 'switch') {
    // What goes with it, such as a LoRA's file and strength with Enable LoRA, beside it.
    const choices = all.filter(other => other.parent === option.id).map(child => child.kind === 'choice'
      ? ` <select name="opt_${esc(child.id)}" aria-label="${esc(child.label)}" title="${esc(child.label)}" class="option-choice">${choiceOptions(child)}</select>`
      : ` <input type="number" class="option-strength" name="opt_${esc(child.id)}" aria-label="${esc(child.label)}" title="${esc(child.label)}" min="${child.min}" max="${child.max}" step="${child.step}" value="${esc(child.default)}">`).join('');
    return `<label class="check"><input type="hidden" name="${esc(name)}" value="0"><input type="checkbox" name="${esc(name)}" value="1"${option.default === '1' ? ' checked' : ''}${locked}>
      <span>${esc(option.label)}${choices}${problem}</span></label>`;
  }
  if (option.kind === 'strength') {
    const on = option.default !== '0';
    return `<label class="check"><input type="hidden" name="${esc(name)}_on" value="0"><input type="checkbox" name="${esc(name)}_on" value="1"${on ? ' checked' : ''}${locked}>
      <span>${esc(option.label)} <input type="number" class="option-strength" name="${esc(name)}_strength" aria-label="Strength" min="${option.min}" max="${option.max}" step="${option.step}" value="${esc(on ? option.default : option.usual || '1')}"${locked}>${problem}</span></label>`;
  }
  return '';
}
// One setting under a switch that has them in rows: its name, then its box, choice or tickbox, lined up with the rest.
function optionRowHtml(child) {
  const id = `opt_${child.id}`, off = child.problem ? ' disabled' : '';
  const control = child.kind === 'choice'
    ? `<select id="${esc(id)}" name="${esc(id)}" class="option-choice"${off}>${choiceOptions(child)}</select>`
    : child.kind === 'switch'
      ? `<input type="hidden" name="${esc(id)}" value="0"><input type="checkbox" id="${esc(id)}" name="${esc(id)}" value="1"${child.default === '1' ? ' checked' : ''}${off}>`
      : `<input type="number" id="${esc(id)}" name="${esc(id)}" class="option-strength" min="${child.min}" max="${child.max}" step="${child.step}" value="${esc(child.default)}"${off}>`;
  return `<div class="option-row"><label for="${esc(id)}">${esc(child.label)}</label>${control}</div>`;
}
// Steps, Sampler, Scheduler and CFG: each on its line, its name a button that drops a short hint under it.
const SAMPLING_OPTIONS = ['steps', 'sampler', 'scheduler', 'cfg'];
const SAMPLING_HINTS = {
  steps: 'How many times the model works over the picture. More takes longer and can add detail, up to a point. A turbo or distilled model is made for few (4 to 8).',
  sampler: 'How each step is taken. euler is the safe choice; others (res_multistep, dpmpp_2m, er_sde) can come out sharper or need more steps.',
  scheduler: 'How the noise is spread over the steps. simple suits most models; karras and beta spend more of them on fine detail.',
  cfg: 'How hard it follows the prompt rather than its own idea. Turbo and distilled models are made for 1; higher follows harder, but can burn the colours.',
};
function samplingHtml(option) {
  const name = `opt_${option.id}`, locked = option.problem ? ' disabled' : '';
  const control = option.kind === 'choice'
    ? `<select id="${esc(name)}" name="${esc(name)}" class="option-choice"${locked}>${choiceOptions(option)}</select>`
    : `<input type="number" id="${esc(name)}" name="${esc(name)}" class="option-strength" min="${option.min}" max="${option.max}" step="${option.step}" value="${esc(option.default)}"${locked}>`;
  const hint = [SAMPLING_HINTS[option.id], option.problem && `Can't be changed: ${option.problem}`].filter(Boolean).join(' ');
  return `<div class="option-row sampling-line"><button type="button" class="res-info option-info" aria-expanded="false" title="What it does"><span>${esc(option.label)}</span><span class="res-info-mark" aria-hidden="true">i</span></button>${control}</div>`
    + `<div class="res-hint option-hint" hidden>${esc(hint)}</div>`;
}
// What a setting does, where its name doesn't say (core/workflow_options.py HINTS): an (i) after its name, its text
// under it, shown and hidden by the page's own hint toggles.
function withHint(option, html) {
  if (!option.hint || !html) return html;
  const id = `hint_opt_${option.id.replace(/[^\w-]/g, '_')}`;
  const button = `<button type="button" class="hint-toggle" data-hint-target="${id}" aria-controls="${id}" aria-expanded="false" aria-label="About ${esc(option.label)}"><span class="res-info-mark" aria-hidden="true">i</span></button>`;
  const hint = `<div class="hint option-hint" id="${id}" hidden>${esc(option.hint)}</div>`;
  // After its name where it's shown (a tag's text, never an attribute such as aria-label), in its line or row.
  const named = html.indexOf(`>${esc(option.label)}`);
  const at = named >= 0 ? named + 1 + esc(option.label).length : -1;
  if (at < 0) return html + hint;
  // A switch's own hint goes under the switch, above the settings that fold out under it.
  const rows = html.indexOf('<div class="option-reveal option-rows');
  return rows > at ? html.slice(0, at) + button + html.slice(at, rows) + hint + html.slice(rows) : html.slice(0, at) + button + html.slice(at) + hint;
}
// A tap on its name drops its hint down; the next folds it away.
document.addEventListener('click', e => {
  const stepper = e.target.closest && e.target.closest('[data-lora-step]');
  if (stepper) {
    const input = $(stepper.dataset.loraStep);
    if (Number(stepper.dataset.step) > 0) input.stepUp(); else input.stepDown();
    input.dispatchEvent(new Event('change', {bubbles: true}));
    return;
  }
  const stackButton = e.target.closest && e.target.closest('[data-add-lora], [data-remove-lora]');
  if (stackButton) {
    const box = stackButton.closest('[id$=OptionsBox]');
    try {
      const rows = loraStackRows(box), option = box.optionList.find(option => option.kind === 'lora_stack');
      if (stackButton.hasAttribute('data-add-lora')) {
        const used = new Set([box.querySelector('[name=opt_lora_name]')?.value, ...rows.map(row => row.name)]);
        rows.push({on: true, name: option.choices.find(name => !used.has(name)) || option.choices[0], strength: '1'});
      } else rows.splice(Number(stackButton.dataset.removeLora), 1);
      box.querySelector('[name=opt_additional_loras]').value = JSON.stringify(rows);
      renderLoraStack(box);
      rememberOptions(box);
      queuePlan();
    } catch (error) { showFormError(error.message); }
    return;
  }
  const guideLink = e.target.closest && e.target.closest('[data-style-lora-guide]');
  if (guideLink) {
    openModelGuide('style_lora');
    return;
  }
  const toggle = e.target.closest && e.target.closest('[data-hint-target]');
  if (toggle) {
    if (toggle.dataset.guide) return;
    const hint = $(toggle.dataset.hintTarget);
    hint.hidden = !hint.hidden;
    toggle.setAttribute('aria-expanded', String(!hint.hidden));
    if (!hint.hidden) revealHint(hint);
    return;
  }
  const info = e.target.closest && e.target.closest('.option-info');
  if (!info) return;
  const hint = info.closest('.option-row').nextElementSibling;
  const open = info.getAttribute('aria-expanded') !== 'true';
  info.setAttribute('aria-expanded', String(open));
  if (hint) hint.hidden = !open;
  if (hint && open) revealHint(hint);
});
// An opened hint is brought into sight: scrolled up or down only as far as it takes, in its section or the page, clear
// of the header and the footer (its scroll-margin).
function revealHint(hint) {
  if (!hint || !hint.scrollIntoView) return;
  const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
  requestAnimationFrame(() => hint.scrollIntoView({ block: 'nearest', behavior }));
}
// Any form's: its section shows when the workflow has any. A way for the workflow to write its own prompt is chosen
// with the LLM instead (syncImageLlm), so it isn't drawn here.
function syncOptions(section, box, options, workflow = '') {
  options = visibleLoraOptions(options.filter(option => !option.role));
  syncLoraTests(box, options);
  // The negative prompt is typed at the bottom of the Prompt section, where there is one; the rest here.
  const slot = $(box.replace('OptionsBox', 'NegativeSlot'));
  const negative = options.find(option => option.id === 'negative' && option.kind === 'text');
  const key = JSON.stringify([workflow, privateMode, options]);
  $(section).hidden = !options.some(option => option !== negative);
  if ($(box).dataset.key === key) return;
  $(box).dataset.key = key;
  $(box).negative = slot;
  slot.innerHTML = negative ? imageOptionHtml(negative, options) : '';
  slot.hidden = !negative;
  $(box).dataset.workflow = `${section}|${workflow}`;
  // First, in a dark box of their own: Steps, Sampler, Scheduler and CFG, wherever the workflow has them. Then Use LoRA
  // in its own; then the rest, turbo and the like after what the workflow is about. No Advanced heading.
  const draw = list => list.map(option => withHint(option, imageOptionHtml(option, options))).join('');
  const sampling = SAMPLING_OPTIONS.map(id => options.find(option => option.id === id)).filter(Boolean);
  const lora = options.filter(option => option.id === 'lora' || option.parent === 'lora' || option.kind === 'lora_stack');
  // What changes how the sampling runs (Reduce harshness), and what goes under it: just below Sampling.
  const tuning = options.filter(option => option.under_sampling || options.some(other => other.under_sampling && other.id === option.parent));
  const speed = options.filter(option => option.speed);
  // Last of all: which files it runs, Model (another of its kind installed in ComfyUI, such as a fine-tune), its
  // text encoder and VAE.
  const models = options.filter(option => option.model);
  const rest = options.filter(option => !sampling.includes(option) && !tuning.includes(option) && !lora.includes(option) && !speed.includes(option) && !models.includes(option) && option !== negative);
  // Two kinds of LoRA, each under a word on what it does: a turbo one (lightning, n-step) makes it in fewer steps, and
  // comes first, as it sets the steps; a style one changes the look.
  // Each group's name alone, the same way in every group (what it's for is in its hint where it has one).
  const heading = (text, what, hint = '') => `<div class="options-subtitle">${text}${hint}</div>`;
  const loraHint = '<button type="button" class="hint-toggle" data-style-lora-guide aria-label="About style LoRA" aria-haspopup="dialog" aria-controls="modelGuide"><span class="res-info-mark" aria-hidden="true">i</span></button>';
  $(box).innerHTML = (sampling.length ? `<div class="options-section">${heading('Sampling', 'how each picture is worked')}<div class="options-sampling">${sampling.map(samplingHtml).join('')}</div></div>` : '')
    + (tuning.length ? `<div class="options-section options-tuning">${draw(tuning)}</div>` : '')
    + (speed.length ? `<div class="options-lora options-speed">${heading('Turbo LoRA', 'fewer steps, faster')}${draw(speed)}</div>` : '')
    + (lora.length ? `<div class="options-lora">${heading('Style LoRA', 'changes the look', loraHint)}${draw(lora)}</div>` : '')
    + (rest.length ? `<div class="options-section options-misc">${draw(rest.filter(option => !option.advanced)) + draw(rest.filter(option => option.advanced))}</div>` : '')
    + (models.length ? `<div class="options-section options-model">${draw(models)}</div>` : '');
  $(box).optionList = options;
  restoreOptions($(box));
  renderLoraStack($(box));
  syncLoraRanges($(box));
  syncBelow($(box));
  const reset = document.querySelector && document.querySelector(`[data-defaults="${box}"]`);
  if (reset) reset.hidden = !options.length;
}
// Use default, beside the workflow: its settings back to how the workflow is saved in ComfyUI, and what was
// remembered for it forgotten.
function useDefaultOptions(box) {
  for (const option of box.optionList || []) {
    const field = suffix => optionField(box, `[name="opt_${option.id}${suffix}"]:not([type=hidden])`);
    if (option.kind === 'lora_stack') box.querySelector('[name=opt_additional_loras]').value = option.default;
    else if (option.kind === 'switch') { const el = field(''); if (el) el.checked = option.default === '1'; }
    else if (option.kind === 'strength') {
      const on = field('_on'), strength = field('_strength'), active = option.default !== '0';
      if (on) on.checked = active;
      if (strength) strength.value = active ? option.default : option.usual || '1';
    } else { const el = field(''); if (el) el.value = option.default; }
  }
  syncBelow(box);
  renderLoraStack(box);
  const all = savedOptions();
  delete all[box.dataset.workflow];
  try { draftWrite(OPTIONS_KEY, JSON.stringify(all)); } catch (e) {}
}
document.addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('[data-defaults]');
  if (button) useDefaultOptions($(button.dataset.defaults));
});
// A turbo switch has its own step count, so Steps shows the one that goes with it once it's switched.
function followSwitch(box, changed) {
  if (!changed || changed.type !== 'checkbox') return;
  for (const option of (box.optionList || []).filter(option => option.follows && changed.name === `opt_${option.follows.switch}`)) {
    const field = box.querySelector(`[name="opt_${option.id}"]`);
    const steps = option.follows[changed.checked ? '1' : '0'];
    if (field && steps !== undefined) field.value = steps;
  }
}
// --- Each workflow's options as you last set them (per browser) ---
const OPTIONS_KEY = 'comfyui-auto-gen.workflow-options';
function savedOptions() {
  try { return JSON.parse(draftRead(OPTIONS_KEY)) || {}; } catch (e) { return {}; }
}
// The inputs you set: a checkbox's hidden "0" beside it is only there for the form.
const optionInputs = box => [box, box.negative].filter(Boolean).flatMap(part => [...part.querySelectorAll('input[name], select[name], textarea[name]')]).filter(el => el.type !== 'hidden' || el.name === 'opt_additional_loras');
// A field of the options, in the box or in the negative prompt's place in the Prompt section.
const optionField = (box, selector) => box.querySelector(selector) || (box.negative && box.negative.querySelector(selector));
function rememberOptions(box) {
  const all = savedOptions();
  all[box.dataset.workflow] = Object.fromEntries(optionInputs(box).map(el => [el.name, el.type === 'checkbox' ? el.checked : el.value]));
  try { draftWrite(OPTIONS_KEY, JSON.stringify(all)); } catch (e) {}
}
function restoreOptions(box) {
  const mine = savedOptions()[box.dataset.workflow];
  if (!mine) return;
  for (const el of optionInputs(box)) {
    if (!(el.name in mine) || el.disabled) continue;
    if (el.type === 'checkbox') el.checked = !!mine[el.name];
    // A choice the workflow no longer has stays as it was saved in ComfyUI.
    else if (!el.options || [...el.options].some(o => o.value === String(mine[el.name]))) el.value = mine[el.name];
  }
}
for (const box of ['shortsOptionsBox', 'videoOptionsBox', 'imageOptionsBox']) {
  $(box).addEventListener('change', e => { if (e.target.closest('[data-lora-stack]')) rememberLoraStack($(box)); followSwitch($(box), e.target); syncBelow($(box)); rememberOptions($(box)); });
  $(box).addEventListener('input', e => { if (e.target.closest('[data-lora-stack]')) rememberLoraStack($(box)); rememberOptions($(box)); });
  // The negative prompt, typed in the Prompt section, is remembered with the rest.
  $(box.replace('OptionsBox', 'NegativeSlot')).addEventListener('input', () => rememberOptions($(box)));
}
// The workflow's own way of working, such as text2image or image2image: at the top of Setup, as LLM or Exact prompt is.
// Under it, image to image's Denoise, and for inpaint the painting of what to redraw.
function syncImageWorkflowMode(options) {
  const mode = options.find(option => option.one_of);
  const denoise = mode && options.find(option => option.parent === mode.id && option.id.endsWith('.denoise'));
  const key = mode ? JSON.stringify([baseImageTakes().name, mode, denoise]) : '';
  if ($('imageWorkflowModeSlot').dataset.key !== key) {
    $('imageWorkflowModeSlot').dataset.key = key;
    // Set by Mode above it (image-inputs.js syncImageFamily), which says it as the model's modes.
    $('imageWorkflowModeSlot').innerHTML = mode
      ? `<select id="imageWorkflowMode" name="opt_${esc(mode.id)}" aria-label="${esc(mode.label)}">${choiceOptions(mode)}</select>` : '';
    const input = $('imageWorkflowDenoise');
    if (denoise) {
      Object.assign(input, { name: `opt_${denoise.id}`, min: denoise.min, max: denoise.max, step: denoise.step, value: denoise.default });
      input.dataset.default = denoise.default;
    } else input.removeAttribute('name');
  }
  const picked = mode ? $('imageWorkflowMode').value : '';
  const usesDenoise = !!denoise && (denoise.for || []).includes(picked);
  $('imageWorkflowDenoiseRow').hidden = !usesDenoise;
  if (!usesDenoise) $('imageWorkflowDenoiseHint').hidden = true;
  // Not sent when it isn't used: the workflow keeps its own.
  $('imageWorkflowDenoise').disabled = !usesDenoise;
  const inpaint = picked === 'inpaint';
  $('inpaintBox').hidden = !inpaint;
  $('inpaintMask').disabled = !inpaint;
  // Denoise is at the end of Setup and the painting under the image boxes: this box holds Mode alone.
  $('imageWorkflowModeBox').hidden = $('imageFamilyModeRow').hidden;
}
function syncImageOptions() {
  const options = imageTakes().options || [];
  syncImageFamily();
  syncFileTests(options);
  syncImageWorkflowMode(options);
  syncOptions('imageOptions', 'imageOptionsBox', options.filter(option => !IMAGE_UPSCALE_OPTIONS.includes(option.id) && !option.moved && !option.one_of && !(option.parent || '').startsWith('one_of_')), baseImageTakes().name);
  syncImageUpscale(options);
}

// A number setting left empty is its default again, as you leave it: Denoise's, and any in a workflow's settings.
document.addEventListener('change', e => {
  const input = e.target;
  if (!input || input.type !== 'number' || String(input.value).trim() !== '') return;
  const id = input.name && input.name.startsWith('opt_') ? input.name.slice(4) : '';
  const option = id && (imageTakes().options || []).find(o => o.id === id);
  const fallback = input.dataset.default ?? (option ? option.default : undefined);
  if (fallback != null && fallback !== '') input.value = fallback;
}, true);
