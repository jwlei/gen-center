// The real page, as Flask rendered it, with a stub DOM: its script runs from top to
// bottom, then the parts that build HTML get called with awkward data.
//   node tests/page_check.cjs page.html  (test_panel.py saves that page and runs this)
const fs = require('fs');
const assert = require('assert');
const vm = require('vm');

const html = fs.readFileSync(process.argv[2], 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).find(s => s.includes('async function poll'));
assert(script, 'the page has its script');

const status0 = () => html.slice(html.indexOf('id="runCard"'), html.indexOf('id="optionsCard"'));
// Every id the script reaches for has to be on the page.
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]));
for (const [, id] of script.matchAll(/\$\('([A-Za-z]+)'\)/g)) assert(ids.has(id), `#${id} is on the page`);

function element(id) {
  return {
    id, dataset: {}, style: {}, hidden: false, innerHTML: '', textContent: '', value: '', className: '', elements: [], options: [], selectedOptions: [{}],
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    listeners: {}, listenersAll: {}, addEventListener(name, fn) { this.listeners[name] = fn; (this.listenersAll[name] = this.listenersAll[name] || []).push(fn); }, querySelectorAll: selector => (selector === 'input' ? [element('low'), element('high')] : []), querySelector: () => element('part'), setAttribute() {},
    reportValidity() { return true; }, dispatchEvent() {},
    getBoundingClientRect: () => ({ top: 0, bottom: 100 }), appendChild() {}, insertBefore() {}, after() {}, offsetHeight: 90, insertAdjacentHTML() {}, showModal() { this.open = true; }, close() { this.open = false; }, scrollTo() {}, scrollIntoView() {},
    pause() {}, play() { return Promise.resolve(); }, removeAttribute(name) { delete this[name]; },
  };
}
const els = {};
const wide = { matches: false, addEventListener() {} };
const documentListeners = {}, windowListeners = {};
const context = {
  // A picture loading in the background: it never finishes here, so the viewer keeps the small one it shows first.
  Image: class { constructor() { this.onload = null; this.src = ''; } },
  document: { getElementById: id => (els[id] = els[id] || element(id)), querySelectorAll: () => [], documentElement: { style: { setProperty() {} } }, body: element('body'), addEventListener(name, fn) { (documentListeners[name] = documentListeners[name] || []).push(fn); }, hidden: false },
  history: { replaceState() {} },
  window: { addEventListener(name, fn) { (windowListeners[name] = windowListeners[name] || []).push(fn); }, innerHeight: 800, matchMedia: () => wide, scrollTo() {} },
  localStorage: { getItem: () => null, setItem() {} },
  fetch: async () => { throw new Error('offline'); },
  FormData: class { delete() {} append() {} },
  location: { reload() { context.reloads++; } }, reloads: 0, AbortController,
  URL, Event: class { constructor(type, options) { this.type = type; this.bubbles = options.bubbles; } }, setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {}, requestAnimationFrame: () => 0, cancelAnimationFrame() {},
  confirm: () => true, alert() {}, console, Date, performance: { now: () => 0 }, Math, JSON, Set, Object, String,
};
vm.createContext(context);
vm.runInContext(script, context);
const run = code => vm.runInContext(code, context);

for (const side of ['video', 'shorts']) {
  const section = html.slice(html.indexOf(`id="${side}H3Creativity"`), html.indexOf('</select>', html.indexOf(`id="${side}H3Creativity"`)));
  for (const choice of ['restrained', 'balanced', 'bold', 'extreme']) assert(section.includes(`value="${choice}"`));
  assert(section.includes('value="balanced" selected'), `${side} defaults to balanced`);
}
assert(html.includes('value="gemma-4-12b"') && html.includes('value="qwen3-14b"'), 'Settings offers both OpenH3 models');
assert(els.writeVideoPrompt.innerHTML === run('ICONS.enhanced') && els.writeImagePrompt.innerHTML === run('ICONS.enhanced'), 'prompt writers use the detailed prompt icon');
assert(!html.includes('Local model uses the model in Settings.'), 'no local model hint');
assert(html.includes('value="review">Enhance before review') && html.includes('value="render">Enhance before each clip'));
// The model guide: a quiet link under each workflow picker, there when the workflow's model has a guide.
for (const id of ['shortsGuideLink', 'videoGuideLink', 'imageGuideLink']) assert(new RegExp(`<button type="button" class="guide-link" id="${id}" hidden></button>`).test(html), `${id} is under its picker`);
assert(/<dialog id="modelGuide"[^>]*>[\s\S]*id="modelGuideBody"[\s\S]*id="modelGuideClose"/.test(html), 'the guide opens in a box like the detailed prompt');
run(`setGuides('image', { workflows: [{ name: 'k.json', guide: { key: 'krea2', title: 'Krea-2 Turbo' } }, { name: 'x.json' }], built_in_guide: null })`);
els.imageWorkflow.value = 'k.json';
run("syncGuideLink('image')");
assert(!els.imageGuideLink.hidden && els.imageGuideLink.textContent === 'About Krea-2 Turbo' && els.imageGuideLink.dataset.guide === 'krea2', 'the link names the model');
els.imageWorkflow.value = 'x.json';
run("syncGuideLink('image')");
assert(els.imageGuideLink.hidden, 'a model with no guide has no link');
els.imageWorkflow.value = '';
run("syncGuideLink('image')");
assert(els.imageGuideLink.hidden, 'Automatic has no one model to describe');
run(`setGuides('video', { workflows: [], built_in_guide: { key: 'ltx23', title: 'LTX-2.3' } })`);
els.videoWorkflow.value = '';
assert(els.videoGuideLink.textContent === 'About LTX-2.3' && !els.videoGuideLink.hidden, 'the built-in workflow has its guide');
{
  const guide = run(`guideHtml({ lead: 'A <b>lead', facts: [['Size', '1 MP']], sections: [{ title: 'One', items: ['a'] }, { title: 'Two', items: ['b'] }, { title: 'Three', items: ['c'] }],
    faq: [['Q?', 'A.']], sources: [['Card', 'https://x.test/a?b=1&c=2']] })`);
  assert(guide.includes('A &lt;b&gt;lead') && guide.includes('<dt>Size</dt><dd>1 MP</dd>'), 'a guide is escaped, its facts a list');
  assert((guide.match(/<details open>/g) || []).length === 2 && guide.includes('<details><summary>Three</summary>'), 'the first two parts start open, the rest folded');
  assert(guide.includes('<summary>Q?</summary><p>A.</p>') && guide.includes('href="https://x.test/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer"'), 'questions fold, sources open elsewhere');
}
for (const side of ['video', 'shorts']) {
  const mode = els[side + 'H3Mode'], toggle = els[side + 'H3Enabled'], options = els[side + 'H3CreativityBox'];
  mode.value = 'off';
  run(`syncH3Controls('${side}', true)`);
  assert(!toggle.checked && options.hidden && els[side + 'H3Creativity'].disabled, `${side} starts disabled`);
  toggle.checked = true;
  toggle.listeners.change({ target: toggle });
  run(`syncH3Controls('${side}', true)`);
  assert.strictEqual(mode.value, 'render');
  assert(!options.hidden && !els[side + 'H3Creativity'].disabled, `${side} options appear when enabled`);
  if (side === 'video') mode.value = 'review';
  toggle.checked = false;
  toggle.listeners.change({ target: toggle });
  run(`syncH3Controls('${side}', true)`);
  assert.strictEqual(mode.value, 'off');
  assert(options.hidden, `${side} options hide when disabled`);
  toggle.checked = true;
  toggle.listeners.change({ target: toggle });
  assert.strictEqual(mode.value, side === 'video' ? 'review' : 'render', 'restores the chosen timing');
  run(`syncH3Controls('${side}', false)`);
  assert(mode.disabled && toggle.disabled && options.hidden, 'unsupported workflow sends no enhancement');
}

// Remembered options never touch a file input, which throws if you set its value.
for (const name of ['image', 'image_2', 'image_3']) assert(!run(`remembered({ name: '${name}', type: 'file' })`), name);
assert(run(`remembered({ name: 'llm', type: 'select-one' })`));
assert(!run(`remembered({ name: 'image_2_role', type: 'select-one' })`), 'each film starts from the default role');
assert(!run(`remembered({ name: 'image_5_role', type: 'select-one' })`));
{
  const savedStorage = context.localStorage;
  for (const [side, loader, key] of [['Video', 'loadVideoForm', 'comfyui-auto-gen.video.v1'],
                                      ['Image', 'loadImageForm', 'comfyui-auto-gen.image.v1']]) {
    const form = els[`form${side}`], original = form.elements;
    const select = { name: 'llm', type: 'select-one', value: '', options: [{ value: 'gemini' }, { value: 'local' }] };
    form.elements = [select];
    context.localStorage = { getItem: () => null };
    run(`${loader}()`);
    assert.strictEqual(select.value, 'local', `${side} defaults to local`);
    context.localStorage = { getItem: name => name === key ? JSON.stringify({ llm: 'gemini' }) : null };
    run(`${loader}()`);
    assert.strictEqual(select.value, 'gemini', `${side} brings back the model picked last in this browser`);
    form.elements = original;
  }
  context.localStorage = savedStorage;
}

// One box per image, built as a workflow needs them. The page's boxes, without a browser to parse them.
function imageBox(number) {
  const hiddenClass = () => ({ toggle(name, on) { this.on = on; } });
  // As in a browser, clearing an input's value empties its files.
  const input = { name: number === 1 ? 'image' : `image_${number}`, files: [], disabled: false, text: '',
    get value() { return this.text; }, set value(text) { this.text = text; if (!text) this.files = []; } };
  const parts = { input, img: { src: '', classList: hiddenClass() }, button: { classList: hiddenClass() }, label: { textContent: '' },
    select: { disabled: true, value: 'view', classList: hiddenClass() } };
  return { hidden: false, parts, querySelector: tag => tag === '[data-clear]' ? parts.button : tag === 'input[type="file"]' ? parts.input : parts[tag], classList: hiddenClass() };
}
const boxes = [];
const holder = context.document.getElementById('imageBoxes');
holder.querySelectorAll = () => boxes;
holder.insertAdjacentHTML = (_, html) => {
  assert(/type="file"/.test(html) && /<img class="preview hidden"/.test(html) && /data-clear/.test(html) && /data-pick="1"/.test(html));
  assert(/<div class="image-line">[\s\S]*type="file"[\s\S]*data-clear[\s\S]*<\/div>/.test(html), 'the image and what it is share one line');
  const number = boxes.length + 1;
  assert.strictEqual(html.includes(`name="image_${number}_role"`), number > 1, 'every image after the first has a role');
  if (number > 1) assert(/value="view">Same character, new view<[\s\S]*value="character">Another character<[\s\S]*value="place">Environment/.test(html));
  boxes.push(imageBox(boxes.length + 1));
};
const labels = () => boxes.filter(box => !box.hidden).map(box => box.parts.label.textContent);

context.URL = { createObjectURL: () => 'blob:x', revokeObjectURL() {} };
const choose = (index, file = {}) => {
  boxes[index].parts.input.files = [file];
  boxes[index].parts.input.value = 'chosen.png';
  run(`showImage(imageBoxes()[${index}]); syncImageInput()`);
};
const pressPlus = () => {
  assert(!els.addImage.hidden, 'the + is there to press');
  run('imagesShown++; syncImageInput()');
};
run('syncImageInput()');
assert.deepStrictEqual(labels(), ['Image 1: first frame'], 'one box to start with');
assert(els.addImage.hidden, 'no + until that box holds an image');
assert(els.imagesHint.hidden, 'nothing to say about an image 2 nobody chose');
choose(0);
pressPlus();
assert.deepStrictEqual(labels(), ['Image 1: first frame', 'Image 2 (optional)'], 'the built-in workflow');
assert(els.addImage.hidden, 'the next + waits for this box');
choose(1);
assert.strictEqual(boxes[1].parts.input.value, 'chosen.png');
assert(els.addImage.hidden, 'and one input has room for image 2, no more');
assert(boxes[1].parts.select.classList.on === false && boxes[1].parts.select.disabled === false, 'image 2 chosen: its role shows and is sent');
run('syncImageInput()');
assert(!els.imagesHint.hidden);
assert(els.imagesHint.textContent.includes('never sees'), 'one input to fill: the LLM alone sees image 2');

run(`workflowTakes = { r2v: { min_images: 0, max_images: 3 }, t2v: { min_images: 0, max_images: 0 }, ti2v: { min_images: 0, max_images: 1 } }`);
els.start.value = 'chain';
els.videoWorkflow.value = 'r2v';
run('syncImageInput()');
assert(els.start.disabled && els.start.hidden && !els.startUnavailable.hidden, 'reference workflow shows separate moments instead of a disabled continuous take');
assert(els.startHint.textContent.includes('cannot start a clip'), 'explains the workflow limitation');
assert.deepStrictEqual(labels(), ['Image 1: main character (optional)', 'Image 2 (optional)'], 'the boxes open stay open');
assert.strictEqual(boxes[1].parts.input.value, 'chosen.png', 'a workflow with room for it keeps the image');
pressPlus();
assert.deepStrictEqual(labels(), ['Image 1: main character (optional)', 'Image 2 (optional)', 'Image 3 (optional)']);
assert(els.imagesHint.textContent.includes('Every clip'));
assert(els.imagesHint.textContent.includes('takes 3 at most'), 'it says why the + stops');

els.videoWorkflow.value = 'ti2v';
run('syncImageInput()');
assert(!els.start.disabled && !els.start.hidden && els.startUnavailable.hidden, 'single-image workflow restores the selectable mode');
assert.strictEqual(els.start.value, 'chain', 'switching workflows keeps the original choice');
assert.deepStrictEqual(labels(), ['Image 1: first frame (optional: without one it starts from text)', 'Image 2 (optional)']);
assert(boxes[2].parts.input.disabled, 'a hidden box sends nothing');

els.videoWorkflow.value = 't2v';
boxes[1].parts.input.files = [];
run('syncImageInput()');
assert(els.start.disabled && !els.startUnavailable.hidden, 'text-only workflows also use separate moments');
assert.deepStrictEqual(labels(), [], 'text alone has no image to ask for');
assert(boxes[1].parts.input.disabled, 'an image a text-only workflow cannot take is kept, but not sent');
assert(els.imagesHint.hidden);

// Up to 20 boxes, one + at a time, and however many a workflow could take.
context.DataTransfer = class { constructor() { this.files = []; this.items = { add: file => this.files.push(file) }; } };
run('workflowTakes = { many: { min_images: 0, max_images: 30 }, minimax: { min_images: 0, max_images: 9 } }');
els.videoWorkflow.value = 'many';
run('imagesShown = 1; syncImageInput()');
for (let index = 0; index < 20; index++) {
  assert.strictEqual(labels().length, index + 1);
  choose(index, { number: index + 1 });
  if (index < 19) pressPlus();
}
assert(els.addImage.hidden, 'twenty is the most');
assert(!els.imagesHint.textContent.includes('at most'), 'the form\'s own limit, not the workflow\'s');

// Taking one out moves the rest up, each with its role, and leaves no gap.
boxes[3].parts.select.value = 'place';
boxes[4].parts.select.value = 'character';
run('removeImage(imageBoxes()[2]); syncImageInput()');
const chosen = () => boxes.filter(box => !box.hidden).map(box => (box.parts.input.files[0] || {}).number);
assert.deepStrictEqual(chosen().slice(0, 4), [1, 2, 4, 5]);
assert.strictEqual(chosen().length, 19);
assert.deepStrictEqual([boxes[2].parts.select.value, boxes[3].parts.select.value], ['place', 'character']);
assert.strictEqual(boxes[19].parts.input.value, '', 'the last box is emptied');
assert(!els.addImage.hidden, 'and there is room for one more');

// A workflow with less room keeps what fits, and an emptied list leaves one box.
els.videoWorkflow.value = 'minimax';
run('syncImageInput()');
assert.strictEqual(labels().length, 9);
assert(els.addImage.hidden && els.imagesHint.textContent.includes('takes 9 at most'));
assert(boxes[9].parts.input.disabled && boxes[9].parts.input.files.length, 'what no longer fits is not sent, but kept for a workflow that takes it');
run('imagesShown = 1; for (const box of imageBoxes()) clearImage(box); syncImageInput()');
assert.strictEqual(labels().length, 1);
assert.strictEqual(boxes[0].parts.button.classList.on, true, 'an empty first box has nothing to remove');

els.videoWorkflow.value = '';
run('workflowTakes = {}; syncImageInput()');

// H3 modes are enabled only by compatible workflows, and use their own controls.
run(`workflowTakes = { ref: { min_images: 0, max_images: 9 }, director: { min_images: 0, max_images: 9 },
                       other: { min_images: 0, max_images: 3 } };
     workflowMultishot = { ref: true }; workflowDirector = { director: true };
     workflowClips = { ref: [5, 15, 10], director: [5, 15, 10] };
     pipeline = 'video'`);
const clipRangeInputs = [element('low'), element('high')];
els.videoClipRange.querySelectorAll = () => clipRangeInputs;
els.videoWorkflow.value = 'ref';
els.start.value = 'multishot';
els.videoClipFixed.checked = false;
els.previewRun.checked = true;
run('syncVideoForm()');
assert(!els.startMultishot.disabled && els.startDirector.disabled);
assert(!els.multishotOptions.hidden && els.videoClipFixed.checked && els.videoClipFixedButton.disabled);
assert(els.previewRun.disabled && els.previewRunLabel.hidden && els.videoH3Enabled.disabled);
els.videoWorkflow.value = 'other';
run('syncVideoForm()');
assert(els.start.disabled && !els.previewRun.disabled && els.multishotOptions.hidden, 'unsupported workflow remains usable');
els.videoWorkflow.value = 'director';
els.start.value = 'director';
run('syncVideoForm()');
assert(!els.startDirector.disabled && els.startMultishot.disabled && !els.start.disabled);
assert(els.startHint.textContent.includes('exactly one image'));
assert(els.multishotOptions.hidden && !els.previewRun.disabled && !els.videoClipFixedButton.disabled);
assert(html.indexOf('id="sizePreset"') < html.indexOf('id="duration"') &&
       html.indexOf('id="videoClipFixedHint"') < html.indexOf('id="connectionBox"'), 'resolution precedes film length and connection follows clip length');
assert(html.indexOf('id="imageSizeBox"') < html.indexOf('id="imageCount"'), 'image resolution precedes the image count');
els.audioMode.value = 'none';
els.duration.min = '5'; els.duration.max = '600';
els.duration.value = '10';
els.videoClipFixed.checked = false;
els.videoClipSeconds.value = '5-15';
run('syncVideoForm()');
assert(els.start.disabled && els.start.hidden && !els.startUnavailable.hidden && !els.startSingle.disabled && /name="start" id="startSingle" value="image"/.test(html), 'single clip shows and submits Separate moments');
assert.strictEqual(els.start.value, 'director', 'single clip retains the previous choice for later');
els.duration.value = '25';
run('syncVideoForm()');
assert(!els.start.disabled && !els.start.hidden && els.startSingle.disabled && els.start.value === 'director', 'multiple clips restore the chosen mode');
els.duration.value = '10';
els.audioMode.value = 'file';
run('syncVideoForm()');
assert(!els.start.hidden && els.startSingle.disabled, 'audio length is unknown, so connection remains selectable');
els.audioMode.value = '';
els.duration.value = '';
els.duration.min = ''; els.duration.max = '';
run('workflowTakes = {}; workflowMultishot = {}; workflowDirector = {}; workflowClips = {};');
els.videoWorkflow.value = '';
els.start.value = 'chain';
els.previewRun.checked = false;
els.videoClipFixed.checked = false;
els.videoClipSeconds.value = '';
run('syncVideoForm()');
els.videoClipSeconds.value = '';

// Resolution presets: both shapes from 360p up to the workflow's own size, and that's the highest.
for (const size of ['640x352', '864x480', '960x544', '1280x736', '352x640', '480x864', '544x960', '736x1280']) {
  assert(html.includes(`<option value="${size}">`), size);
}
const filmSizes = html.slice(html.indexOf('id="sizePreset"'), html.indexOf('id="size"'));
assert.strictEqual([...filmSizes.matchAll(/<option value="(\d+)x(\d+)">/g)].filter(m => +m[1] * +m[2] > 1280 * 736).length, 0);
for (const selectId of ['sizePreset', 'avatarSize', 'imageAspect']) {
  const select = html.slice(html.indexOf(`id="${selectId}"`), html.indexOf('</select>', html.indexOf(`id="${selectId}"`)));
  const dimensions = [...select.matchAll(/<option value="(\d+)x(\d+)"[^>]*>([^<]*)<\/option>/g)];
  assert(dimensions.length, `${selectId} has resolution options`);
  for (const [, width, height, label] of dimensions) {
    assert(label.endsWith(` · ${(width * height / 1000000).toFixed(3)} MP`), `${selectId} ${width}x${height}: ${label}`);
  }
}
els.sizePreset = element('sizePreset');
els.sizePreset.options = [{ value: '' }, { value: '960x544' }, { value: '1280x736' }, { value: 'custom' }];
Object.defineProperty(els.sizePreset, 'selectedOptions', { get() { return [els.sizePreset.options.find(o => o.value === els.sizePreset.value) || {}]; } });
els.videoWorkflow = element('videoWorkflow');
els.size = element('size');
els.sizePreset.value = '352x640';
run('syncSize()');
assert.strictEqual(els.size.value, '352x640', 'the preset is what the form sends');
assert(els.size.hidden);
els.sizePreset.value = 'custom';
run('syncSize()');
assert(!els.size.hidden, 'a custom size has somewhere to go');
assert.strictEqual(els.size.value, '352x640', 'and starts from the last one');
els.sizePreset.value = '';
run('syncSize()');
assert.strictEqual(els.size.value, '', 'the default sends no size, so it follows the image');
run("workflowMost = { capped: 960 * 544 }; $('videoWorkflow').value = 'capped'");
els.sizePreset.value = '1280x736';
run('syncSize()');
// A size past the workflow's limit would very likely run out of memory: its shape, at the nearest pixel count below.
assert(!els.sizePreset.options.find(o => o.value === '1280x736').disabled, 'every size stays pickable');
const [heldW, heldH] = els.size.value.split('x').map(Number);
assert(heldW * heldH <= 960 * 544 && heldW % 32 === 0 && Math.abs(heldW / heldH - 1280 / 736) < 0.05, `held to the nearest below: ${els.size.value}`);
assert(!els.videoResNote.hidden && /nearest below/.test(els.videoResNote.textContent), 'and it says so');
// The stepper is there for a screen too, and scales it.
assert(!/videoMegapixelsBox'\)\.classList\.toggle/.test(script) && /class="count-stepper mp-stepper" id="videoMegapixelsBox"/.test(html), 'never hidden');
run("workflowMost = {}");

// The film length allows single-second input within the server's limits.
assert(/id="duration"[^>]*type="number"[^>]*min="5"[^>]*max="600"[^>]*step="1"/.test(html));
assert.strictEqual(run('clipCount(1)'), '1 clip');
assert.strictEqual(run('clipCount(75)'), '75 clips');
assert.strictEqual(run('filmLengthEstimate(30, 32)'), '≈0:32 · 4 clips');
assert.strictEqual(run('filmLengthEstimate(32, 32)'), '0:32 · 4 clips');

// One ETA for the run, on its bar: the status line and the step line don't repeat it.
assert(!script.includes('totalEta(') && !script.includes('Original ETA') && !script.includes('Adjusted ETA'));
assert(!html.includes('stageName') && !html.includes('stageTime') && !script.includes('Step ${n}'), 'the stepper says which step, with no line repeating it');
run(`renderEtaDetail({ changes: [], original_total: 600, adjusted_total: 600 })`);
assert.strictEqual(els.etaDetail.hidden, true, 'on track: nothing to explain');
assert.strictEqual(run(`etaShift({ changes: [{ text: 'x', seconds: 120 }], original_total: 600, adjusted_total: 720 })`), '+2 min', 'how far it moved');
assert.strictEqual(run(`etaShift({ changes: [], original_total: 600, adjusted_total: 600 })`), '');
run(`renderEtaDetail({ changes: [{ text: 'Clip <b>3</b> was slow', seconds: 120 }], original_total: 600, adjusted_total: 720 })`);
assert(els.etaDetail.hidden && script.includes("$('runProgressRight').classList.toggle('eta-moved', !!shift);"), 'moved: said on the time left, the detail folded');
run(`etaOpen = true; renderEtaDetail({ changes: [{ text: 'Clip <b>3</b> was slow', seconds: 120 }], original_total: 600, adjusted_total: 720 }); etaOpen = false`);
assert(!els.etaDetail.hidden && els.etaDetail.innerHTML.startsWith('<div class="eta-first">Original estimate: ~10 min (+2 min)</div>') && !els.etaDetail.innerHTML.includes('<b>3'),
  'tapped: the original estimate and the change, under it');
assert(script.includes("${etaShift(eta) ? ` (${etaShift(eta)})` : ''}"), 'the time left line ends with (+2 min)');
run(`etaOpen = true; renderEtaDetail({ changes: [{ text: 'Running faster than estimated', seconds: -120 }], original_total: 600, adjusted_total: 480 }); etaOpen = false`);
assert(els.etaDetail.innerHTML.includes('Original estimate: ~10 min (-2 min)') && !els.etaDetail.innerHTML.includes('Running faster'), 'no "running faster" line under it');
assert(/<span id="runProgressRight"><\/span><\/div>\s*<div class="hint eta-detail" id="etaDetail" hidden><\/div>\s*<div class="bar"><div id="runProgressBar">/.test(html)
  && /\.eta-detail \{ margin: 2px 0 0; text-align: right;/.test(html), 'the original estimate sits under the time left, over the bar, at the right');

// Shorts in YouTube red; the phone addresses are in the settings box, with copy buttons; no voice hint.
assert(/body\.on-shorts \{ --side: var\(--c-shorts\); \}/.test(html));
// The colours are written once, and everything else reads them.
assert(/:root \{ --c-shorts: #ff0033; --c-video: #4c8dff; --c-image: #2fbf71; --shared: #a07cff; \}/.test(html), 'each colour once');
{
  assert.strictEqual((html.match(/#ff0033|#4c8dff|#2fbf71|#a07cff/g) || []).length, 4, 'nowhere else in the page');
  assert(!/#ff0033|#4c8dff|#2fbf71|#a07cff/.test(script) && script.includes("const SIDE_COLOURS = { shorts: 'var(--c-shorts)', video: 'var(--c-video)', image: 'var(--c-image)' };"), 'nor in its script');
}
assert(/#restartComfy\.pulse \{ border-color: var\(--warn\); color: var\(--warn\);/.test(html) && !/e6b800|230, 184, 0/.test(html), "Restart ComfyUI's pulse: the same yellow as Restart panel's");
assert(script.includes("document.body.dataset.viewing = filmFolder === 'video' ? 'video' : 'shorts';") && script.includes("document.body.dataset.viewing = 'image';")
  && /#imageViewer, #viewerUpscaleBar, #upscaleSettings, #editMenu \{ --accent: var\(--item, var\(--shared\)\); \}/.test(html), 'the preview in the colour of what it shows');
// One theme: violet everywhere but Generate, which is its side's colour; what sits above every page follows where you are.
assert(/body \{ --accent: var\(--shared\); --page-accent: var\(--shared\); \}/.test(html)
  && /body\.in-generate \{ --page-accent: var\(--side\); \}/.test(html) && /#optionsCard, #goBar, \.jump a\[data-page="generate"\] \{ --accent: var\(--side\); \}/.test(html),
  'violet, but Generate in its side colour');
assert(/a#privateToggle\.on \{ opacity: 1; color: var\(--page-accent\); \}/.test(html)
  && /\.page-loader::before \{[^}]*var\(--page-accent\)/.test(html) && /\.disk \.bar > div \{ background: var\(--shared\); \}/.test(html),
  'the key and the loading bar by where you are; the disk bar violet');
assert(/\.switch\.output-kinds button\.active \{[^}]*color: var\(--kind\); \}/.test(html) && /\.output-kinds \{ position: relative; --kind: var\(--shared\); \}/.test(html), "Output's Both in violet, not the side's colour");
assert(/\.pills\.video \{ --pill: var\(--c-video\); \}/.test(html) && /\.pills\.image \{ --pill: var\(--c-image\); \}/.test(html), 'pills keep their kind\'s colour');
assert(/id="privateToggle"[^>]*><svg[^>]*><circle cx="12" cy="12" r="8"\/><circle cx="12" cy="12" r="2" fill="currentColor"\/><\/svg>/.test(html), 'the key: the same plain ring as the other view');
assert(/body\.on-shorts #videosCard, body\.on-shorts \.jump a#jumpResults \{ --accent: var\(--c-shorts\); \}/.test(html)
  && /body\.on-shorts\[data-page="output"\] \{ --page-accent: var\(--c-shorts\); \}/.test(html), "Output on Shorts in Shorts' red");
assert(script.includes("document.body.classList.toggle('in-generate', WIDE.matches ? desktopGenerateActive : document.body.dataset.page === 'generate');"), 'in Generate: by page, or scrolled to it');
assert(!html.includes('id="misc"') && /class="settings-row url-row"[^>]*>\s*<span class="url-name">Local<\/span><code>[^<]+<\/code><button type="button" class="copy-url"/.test(html));
assert(!/<summary>More<\/summary>/.test(html), 'no More dropdown');
assert(!/id="statusHead"[^>]*aria-controls/.test(status0()));
assert(/class="section-title">Status<\/div>\s*<div class="status">\s*<span class="dot" id="dot"[\s\S]*?id="statusText"[\s\S]*?<\/div>\s*<span class="status-times"/.test(status0()), 'status light and text follow the heading, separately from the times');
assert(/\.status-head \.status \{ margin: 0;/.test(html) && /\.status-times \{ display: flex; gap: 8px;/.test(html), 'status and times stay together beside the heading');
assert(!html.includes('If both Gemini voice models fail'));

// Times.
assert.strictEqual(run('stepEta({state:"kept",seconds:0})'), 'kept');
assert.strictEqual(run('stepEta({state:"done",seconds:65})'), '1:05');
assert.strictEqual(run('stepEta({state:"next",seconds:1860})'), '~31 min');
assert.strictEqual(run('stepEta({state:"now",seconds:0})'), 'any moment');
assert.strictEqual(run('fmtEta(9300)'), '~2h 35m');

// A film's shots: the text people and models write can hold anything.
const shots = {
  id: 'run_20261101_120000', title: 'A <b>storm</b>', brief: 'say "hi"', start: 'chain', llm: 'claude', busy: false, finished: false,
  shots: [
    { title: 'One', seconds: 8, prompt: 'She says </textarea><script>alert(1)</script>', rendered: true },
    { title: 'Two', seconds: 7, prompt: 'Plain', rendered: false },
  ],
};
context.shots = shots;
const dialog = run('shotsHtml(shots)');
assert(!dialog.includes('<b>storm'), 'titles are escaped');
assert(!dialog.includes('<script>'), 'prompts are escaped');
assert(!dialog.includes('</textarea><script'), 'a prompt can\'t close its own box');
assert(!dialog.includes('data-redo='), 'no generate-again button: an item is made again from Generate');
assert(dialog.includes('preload="none"'), 'clips only load when played');
assert(dialog.includes('Render the 1 left'));
assert(dialog.includes('also renders every shot after it'));

shots.busy = true;
const busy = run('shotsHtml(shots)');
assert(busy.includes('readonly') && !busy.includes('data-redo') && !busy.includes('data-save') && !busy.includes('data-render'),
  'a run that is going can only be read');
shots.busy = false;

shots.start = 'image';
assert(!run('shotsHtml(shots)').includes('Separate moments'), 'no hint for separate moments');
shots.finished = true;
assert(!run('shotsHtml(shots)').includes('data-render'), 'a finished film has nothing left to render');

// The Image side: a set's titles can hold anything, and its size is worked out as the pipeline does.
const sets = [{ id: 'image_20261102_120000', label: 'A <b>set', total: 3, size: '1024x1024', resolutions: ['1024x1024'], size_bytes: 2097152, llm: 'local', loras: ['one', '<two>'], generating: true, when: '02 Nov', model: 'krea2_<SFW>',
  images: [{ position: 1, title: '<i>Look', version: 5 }, { position: 3, title: 'Two', version: 6 }] }];
context.sets = sets;
const setHtml = run('imageSetHtml(sets[0])');
assert(!setHtml.includes('<b>set') && !setHtml.includes('<i>Look'), 'titles are escaped');
assert(setHtml.includes('/thumbnails/1?v=5') && setHtml.includes('loading="lazy"') && setHtml.includes('data-grid-set="image_20261102_120000"'), 'a small cover, that opens them all');
assert(setHtml.includes('data-delete-set=') && setHtml.includes('data-shots=') && !setHtml.includes('data-download-set='), 'no download on the card: the preview has it');
assert(setHtml.includes(`title="Prompts" aria-label="Prompts">${run('ICONS.enhanced')}</button>`), 'image Output prompts uses the star icon');
assert(setHtml.includes('krea2_&lt;SFW&gt; · 1024x1024 · 2.0 MB · 2 of 3 images'), 'workflow, resolution, total size and progress');
assert(run("outputCount({ total: 3, finished: true, images: [1, 2] })") === '2 images', 'finished sets show the current count');
assert(!setHtml.includes('target="_blank"') && !setHtml.includes('data-view-position="3"'), 'nothing opens in a new tab; the rest are in the grid');
const inRow = setHtml.slice(setHtml.indexOf('class="image-set-row'));
assert(inRow.includes('<img') && inRow.indexOf('<img') < inRow.indexOf('data-delete-set') && inRow.indexOf('data-shots') < inRow.indexOf('data-delete-set'), 'the pictures and their buttons share one line');

// Download on a set takes each image as a file of its own; the viewer's takes just the one it shows.
const clicked = [];
context.document.createElement = () => ({ click() { clicked.push(this.href); }, remove() {} });
context.document.body.appendChild = () => {};
context.setTimeout = fn => { fn(); return 0; };
run("downloadImages('image_20261102_120000', [1, 3])");
assert.deepStrictEqual(clicked, ['/image-runs/image_20261102_120000/files/1?download=1', '/image-runs/image_20261102_120000/files/3?download=1'], 'no zip');
context.setTimeout = () => 0;
assert(/<dialog id="imageViewer"[\s\S]*?id="viewerImage"[\s\S]*?class="viewer-tools-left">[\s\S]*?id="viewerVariations"[\s\S]*?id="viewerPrompts"[\s\S]*?id="viewerUpscale"[\s\S]*?class="viewer-tools-right">[\s\S]*?id="viewerDownload"[\s\S]*?id="viewerDelete"[\s\S]*?id="viewerClose"[\s\S]*?<\/dialog>/.test(html), 'more like this, prompt and upscale on the left; download and delete on the right; Close under them');
assert(/<a class="icon-btn" id="viewerDownload"[^>]*><\/a>/.test(html) && /<button type="button" class="icon-btn del" id="viewerDelete"/.test(html) && /id="viewerClose"[^>]*>Close<\/button>/.test(html), 'download and delete are icons, Close says so');
assert.strictEqual(els.viewerPrompts.innerHTML, run('ICONS.enhanced'), 'viewer prompts uses the shared star icon');
assert.strictEqual(els.viewerEdit.innerHTML, run('ICONS.prompts'), 'viewer Edit uses the pen icon');
assert.strictEqual(els.viewerVariations.innerHTML, run('ICONS.config'), 'More like this uses the settings slider');
assert.notStrictEqual(els.viewerEdit.innerHTML, els.viewerVariations.innerHTML, 'Edit and More like this have distinct icons');
assert(/dialog\.viewer::backdrop \{ background: rgba\(0, 0, 0, \.55\)/.test(html), 'over a dimmed page');
run('imageSets = sets');
context.document.getElementById('viewerMetaDetails').hidden = true;
run("openViewer('image_20261102_120000', 3)");
assert.strictEqual(els.imageViewer.open, true);
assert.strictEqual(els.viewerDownload.href, '/image-runs/image_20261102_120000/files/3?v=6&download=1');
assert.strictEqual(els.viewerTitle.textContent, 'Two');
assert.strictEqual(els.viewerCount.textContent, '2 of 2', 'which one of the set it is');
assert.strictEqual(els.viewerMeta.textContent, 'krea2_<SFW> · local');
assert(els.viewerMetaDetails.hidden && !els.viewerMeta.disabled, 'extra metadata starts collapsed');
els.viewerMeta.listeners.click();
assert(!els.viewerMetaDetails.hidden && els.viewerMetaDetails.textContent === 'LoRA: one\nLoRA: <two>', 'preview expands one LoRA per line as plain text');
els.viewerMeta.listeners.click();
assert(els.viewerMetaDetails.hidden, 'preview metadata collapses');
// A swipe, or an arrow key, goes through the set, and stops at its ends.
run("openViewer('image_20261102_120000', 1)");
assert.strictEqual(els.viewerTitle.textContent, '<i>Look');
assert.strictEqual(els.viewerCount.textContent, '1 of 2');
assert.strictEqual(run('stepViewer(-1)'), false, 'nothing before the first');
assert.strictEqual(run('stepViewer(1)'), true);
assert.strictEqual(run('viewing.position'), 3, 'the next one in the set, wherever it was numbered');
assert.strictEqual(els.viewerTitle.textContent, 'Two');
assert.strictEqual(els.viewerCount.textContent, '2 of 2');
assert.strictEqual(run('stepViewer(1)'), false, 'nothing after the last');
assert(/touchend[\s\S]*?Math\.abs\(dx\) > 50 && Math\.abs\(dx\) > Math\.abs\(dy\)/.test(script) && /ArrowRight/.test(script), 'swipes, and arrow keys on a desktop');
assert(/#viewerImage \{[^}]*touch-action: none;/.test(html), 'a swipe and a pinch are the page\'s, not the browser\'s');
{
  const image = els.viewerImage, video = els.viewerVideo, dialog = els.imageViewer;
  const saved = [image, video].map(media => ({ add: media.addEventListener, remove: media.removeEventListener }));
  const ghosts = [], events = new Map(), oldAppend = dialog.appendChild, oldCreate = context.document.createElement;
  for (const media of [image, video]) {
    events.set(media, {});
    media.addEventListener = (name, fn) => { events.get(media)[name] = fn; };
    media.removeEventListener = (name, fn) => { if (events.get(media)[name] === fn) delete events.get(media)[name]; };
    media.getBoundingClientRect = () => ({ left: 20, top: 30, width: 200, height: 100 });
  }
  const ghost = () => {
    const node = element('ghost');
    node.classes = [];
    node.classList.add = value => node.classes.push(value);
    node.remove = () => { node.removed = true; };
    node.getContext = () => ({ drawImage: () => { node.drawn = true; } });
    return node;
  };
  image.cloneNode = ghost;
  image.complete = true; image.naturalWidth = 100;
  video.readyState = 2; video.videoWidth = 200; video.videoHeight = 100;
  dialog.appendChild = node => ghosts.push(node);
  context.document.createElement = ghost;
  run("openViewer('image_20261102_120000', 1); stepViewer(1)");
  assert.strictEqual(ghosts.length, 1, 'keeps the previous image until the next is loaded');
  assert.strictEqual(ghosts[0].style.left, '20px');
  assert.strictEqual(ghosts[0].style.transform, 'none', 'previous media remains stationary');
  events.get(image).load();
  assert.deepStrictEqual(ghosts[0].classes, ['to-right'], 'forward uses a rightward fade');
  ghosts[0].listeners.animationend();
  assert(ghosts[0].removed, 'removes the previous frame after the fade');
  run('stepViewer(-1)');
  events.get(image).load();
  assert.deepStrictEqual(ghosts[1].classes, ['to-left'], 'backward uses a leftward fade');
  run('stepViewer(1)');
  assert(ghosts[1].removed, 'rapid navigation cleans up the previous transition');
  events.get(image).error();
  assert(ghosts[2].removed, 'a failed load does not leave an overlay');
  sets.push({ id: 'image_next', images: [{ position: 1, title: 'Next set', version: 1 }] });
  run("nsfwView = false; stepSet(1)");
  events.get(image).load();
  assert.deepStrictEqual(ghosts[3].classes, ['to-down'], 'next set fades downward');
  run('stepSet(-1)');
  events.get(image).load();
  assert.deepStrictEqual(ghosts[4].classes, ['to-up'], 'previous set fades upward');
  run('clearViewerTransition()');
  sets.pop();
  run("lastVideos = { output: [], uploaded: [], video: [{ name: 'a.mp4' }, { name: 'b.mp4' }] }; folder = 'video'; openFilm('a.mp4'); stepViewer(1)");
  assert(ghosts[5].drawn, 'video transitions retain the displayed frame');
  events.get(video).loadeddata();
  assert.deepStrictEqual(ghosts[5].classes, ['to-right'], 'forward video uses a rightward fade');
  run('clearViewerTransition()');
  assert(ghosts[5].removed && !events.get(video).loadeddata, 'cleanup removes the overlay and load listener');
  run('stepSet(-1)');
  events.get(video).loadeddata();
  assert.deepStrictEqual(ghosts[6].classes, ['to-up'], 'previous video uses the vertical fade');
  run('stepSet(1)');
  events.get(video).loadeddata();
  assert.deepStrictEqual(ghosts[7].classes, ['to-down'], 'next video uses the vertical fade');
  run('clearViewerTransition()');
  run("folder = 'output'");
  wide.matches = true;
  run("transitionViewer($('viewerImage'), 'to-up', () => {})");
  assert.strictEqual(ghosts.length, 8, 'reduced motion skips the transition');
  wide.matches = false;
  for (const [i, media] of [image, video].entries()) {
    media.addEventListener = saved[i].add; media.removeEventListener = saved[i].remove;
  }
  image.complete = false; video.readyState = 0;
  dialog.appendChild = oldAppend; context.document.createElement = oldCreate;
}
assert(/\.viewer-out\.to-left \{ mask-image: linear-gradient/.test(html) && /@keyframes viewer-fade-y/.test(html), 'directional fades cover both axes');
assert(!/viewer-from-(right|left|above|below)/.test(html), 'preview navigation no longer slides');
run('closeViewer()');
assert.strictEqual(els.imageViewer.open, false);
assert(/\.image-set-row \{ display: flex/.test(html) && /\.image-grid img \{ width: 56px/.test(html), 'and small enough to');
// An album: its cover opens them all in the grid; beside it, its pills (up to three lines) above its buttons, no strip.
assert(/<div class="image-set-row album">\s*<a href="#" class="album-cover" data-grid-set="[^"]+"[^>]*><img[^>]*\/thumbnails\/1\?v=5"><span class="album-count">2<\/span><\/a>\s*<div class="album-side">\s*(<div class="pills image" data-lines="3"[\s\S]*?<\/div>)?\s*<div class="image-set-actions">/.test(setHtml)
  && !setHtml.includes('album-strip') && !setHtml.includes('aria-label="All of them"'), 'the cover opens the grid; no strip, no grid button');
{
  const withPills = run("imageSetHtml({ ...sets[0], pills: [{ text: 'krea', kind: 'workflow' }, { text: '1024x1024' }] })");
  assert(/<div class="album-side">\s*<div class="pills image" data-lines="3"[^>]*><span class="pill workflow">krea<\/span>[\s\S]*?<\/div>\s*<div class="image-set-actions">/.test(withPills)
    && !/<\/div><div class="pills/.test(withPills.split('image-set-row')[0]), 'its pills beside the cover, above the buttons, not under the title');
  assert(/\.album-side \.pills \{ margin-top: 0; max-height: 62px; \}/.test(html), 'three lines of them');
}
assert(!setHtml.includes('upscaled-badge'), 'no badge on a picture that was not upscaled');
const upscaledHtml = run("imageSetHtml({ ...sets[0], images: [{ position: 1, title: 'a', version: 1, upscaled: 'SeedVR2' }, { position: 2, title: 'b', version: 1 }, { position: 3, title: 'c', version: 1, upscaled: '<x>' }] })");
assert((upscaledHtml.match(/class="upscaled-badge"/g) || []).length === 1 && upscaledHtml.includes('aria-label="Upscaled: SeedVR2"') && !upscaledHtml.includes('<x>'),
  'an upscaled cover has its badge');
assert(/\.album-count \{ position: absolute; left: 4px; bottom: 4px;/.test(html) && /\.upscaled-badge \{ position: absolute; right: 4px; bottom: 4px;/.test(html), 'count bottom left, badge bottom right');
assert(html.includes('<span class="upscaled-badge" id="viewerUpscaled" role="img" aria-label="Upscaled" hidden></span>') && script.includes("$('viewerUpscaled').hidden = !picture.upscaled;"), 'the preview has the badge too');
{
  const later = run("imageSetHtml({ ...sets[0], images: [{ position: 1, title: 'a', version: 1 }, { position: 2, title: 'b', version: 1, upscaled: 'SeedVR2' }] })");
  const cover = later.slice(later.indexOf('class="album-cover"'), later.indexOf('album-side'));
  assert(cover.includes('aria-label="Some of this set are upscaled"'), 'the cover says so when any of its set is upscaled');
  assert(!run("imageSetHtml({ ...sets[0], images: [{ position: 1, title: 'a', version: 1, upscaled: 'SeedVR2' }] })").includes('Some of this set'), 'not twice when the cover is the upscaled one');
}
assert(/<option value="x2">2×<\/option><option value="x3">3×<\/option><option value="x4">4×<\/option><option value="720">/.test(html), 'SeedVR2: 2×, 3× or 4×, then the resolutions');
assert.strictEqual(run("seedvr2Shorter('x3', 800)"), 2400, '3× its shorter side');
assert.strictEqual(run("seedvr2Shorter('x4', 800)"), 2560, 'within what SeedVR2 takes');
assert.strictEqual(run("seedvr2Shorter('1080', 800)"), 1080, 'a resolution as it is');
{
  // A long pill steps aside into the "+N"; the shorter ones after it take its room.
  const made = [0, 30, 0, 0].map(top => {
    const p = { _top: top, classes: new Set(), classList: { add(c) { p.classes.add(c); }, remove(c) { p.classes.delete(c); } } };
    Object.defineProperty(p, 'offsetTop', { get: () => (p.classes.has('spill') ? 0 : p._top) });
    return p;
  });
  const classes = new Set(), line = { children: made, dataset: { lines: '1' }, classList: { contains: c => classes.has(c), add: c => classes.add(c), remove: c => classes.delete(c), toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)) } };
  context.testLine = line;
  run('fitPills(testLine)');
  assert(made[1].classes.has('spill') && !made[2].classes.has('spill') && line.dataset.more === '+1', 'the long second one steps aside, the rest stay on the line');
  assert(/\.pills:not\(\.open\) \.pill\.spill \{ display: none; \}/.test(html), 'stepped aside until the line is opened');
}
assert(!html.includes('data-method="usdu"') && !html.includes('<option value="usdu">'), 'Ultimate SD is gone from the preview and the queue');
assert(html.includes(`<select id="viewerUpscaleDenoise"`) && html.includes('<option value="0">Denoise 0</option><option value="0.01">Denoise 0.01</option>')
  && html.includes('<option value="0.05">Denoise 0.05</option>\n    </select>') && script.includes("&denoise=${encodeURIComponent($('viewerUpscaleDenoise').value)}`")
  && script.includes("if (method === 'seedvr2') $('viewerUpscaleDenoise').value = '0';"), "SeedVR2's denoise: 0 to 0.05 a hundredth at a time, 0 unless set");
assert(html.includes('<input type="hidden" id="imageUpscaleDenoise" name="opt_image_upscale_denoise" value="0" disabled>'), "Generate's: a stepper's value, 0 to start with");
for (const id of ['imageUpscaleDenoise', 'imageUpscaleDenoiseValue', 'imageUpscaleDenoiseDown', 'imageUpscaleDenoiseUp']) context.document.getElementById(id);
run('setImageUpscaleDenoise(0)');
assert(els.imageUpscaleDenoiseDown.disabled && els.imageUpscaleDenoiseValue.textContent === '0', 'none, and no lower');
els.imageUpscaleDenoiseUp.listeners.click();
els.imageUpscaleDenoiseUp.listeners.click();
assert.strictEqual(els.imageUpscaleDenoise.value, '0.02', 'a hundredth at a time');
run('setImageUpscaleDenoise(0.2)');
assert(els.imageUpscaleDenoise.value === '0.05' && els.imageUpscaleDenoiseUp.disabled, 'held to 0.05, as Ultimate SD\'s kept 0.2 would be');
run('setImageUpscaleDenoise(0)');
assert(!html.includes('id="queueUpscaleSettings"') && script.includes("openUpscaleSettings(image ? (UPSCALE_METHODS_OFFERED.includes(data.upscale.method)"),
  "a queued upscale opens the viewer's own upscale box, filled in");
// The thumbnail grid: on a set's card and left of Close in the preview; a tap opens the preview at that one.
assert(setHtml.includes('data-grid-set="image_20261102_120000"') && /<button type="button" class="viewer-grid" id="viewerGrid"[^>]*><\/button>\s*<button type="button" class="plain viewer-use" id="viewerUse"[^>]*>Use<\/button>\s*<button type="button" class="plain" id="viewerClose">Close<\/button>\s*<button type="button" class="viewer-grid" id="viewerMove"/.test(html),
  'a grid button on each set; in the preview the grid left of Close, Move right of it');
{
  const opened = [];
  context.document.getElementById('thumbGridBody');
  context.opened = opened;
  run(`imageSets = [{ id: 'image_1', label: 'S', images: [{ position: 1, title: 'a', version: 1 }, { position: 3, title: '<b>', version: 2, upscaled: 'SeedVR2' }] }];
       viewing = { id: 'image_1', position: 3 }; oldOpenViewer = openViewer;`);
  run("openViewer = (id, position) => opened.push([id, position]); openThumbGrid({ set: 'image_1' })");
  const grid = els.thumbGridBody.innerHTML;
  assert(grid.includes('src="/image-runs/image_1/thumbnails/3?v=2"') && grid.includes('class="current"') && grid.includes('class="upscaled-badge"') && !grid.includes('<b>'),
    'its pictures, the one open outlined, upscaled ones badged, titles escaped');
  assert.strictEqual(els.thumbGridTitle.textContent, 'S (2)');
  els.thumbGridBody.listeners.click({ target: { closest: () => ({ dataset: { gridIndex: '1' } }) } });
  assert.strictEqual(JSON.stringify(opened), '[["image_1",3]]', 'a tap opens the preview there');
  run('openViewer = oldOpenViewer; imageSets = []; viewing = null');
}
// Collections: shown with Output's sets; one with NSFW in it only under the NSFW filter.
{
  for (const id of ['collections', 'moveList', 'moveNewName', 'moveError', 'moveSheet']) context.document.getElementById(id);
  run(`allImageSets = [{ id: 'image_1', label: 'S', images: [{ position: 1, file: 'a.png', title: 'a', version: 1 }, { position: 2, file: 'b.png', title: 'b', version: 1, collection: 'c_1' }] }];
       lastVideos = { ...lastVideos, video: [{ name: 'F.mp4', run: 'run_1', collection: 'c_1' }] };
       collections = [{ id: 'c_1', name: 'Mine <i>', nsfw: false, items: [{ kind: 'image', set: 'image_1', file: 'b.png' }, { kind: 'film', name: 'F.mp4' }] },
                      { id: 'c_2', name: 'Hot', nsfw: true, items: [{ kind: 'film', name: 'F.mp4' }] }];
       nsfwView = false; privateMode = false; pipeline = 'image'; outputKind = 'both';`);
  const albums = run("collectionAlbums('c_1')");
  assert(albums.images.length === 1 && albums.images[0].set === 'image_1' && albums.images[0].position === 2 && albums.films[0].name === 'F.mp4', 'its two albums, as their sets and Videos have them');
  assert.strictEqual(JSON.stringify(run('shownCollections().map(c => c.id)')), '["c_1"]', 'always shown, whatever the kind; NSFW ones out of the normal view');
  run('privateMode = true');
  assert.strictEqual(JSON.stringify(run('shownCollections().map(c => c.id)')), '["c_1"]', 'Private mode alone does not show NSFW ones');
  run('privateMode = false; nsfwView = true');
  assert.strictEqual(JSON.stringify(run('shownCollections().map(c => c.id)')), '["c_2"]', 'only NSFW ones under the NSFW filter');
  run("nsfwView = false; renderCollections()");
  const box = els.collections.innerHTML;
  assert(!html.includes('id="outputFilter"') && !html.includes('data-kind="collections"')
    && /<div class="switch output-kinds" id="outputKinds"[^>]*>\s*<span class="kinds-thumb" id="kindsThumb" aria-hidden="true"><\/span><button[^>]*data-kind="image">Images<\/button><button[^>]*data-kind="both">Both<\/button><button[^>]*data-kind="video">Videos<\/button>\s*<\/div>/.test(html),
    'Images, Both and Videos, Both in the middle, in place of the workflow filter; no Collections there');
  assert(/\.kinds-thumb \{[^}]*transition: transform \.32s/.test(html) && script.includes('thumb.style.transform = `translateX(${active.offsetLeft}px)`'), 'the lit pill slides to the one tapped');
  assert(/\.view-toggle \{[^}]*color: var\(--muted\); opacity: \.5;/.test(html) && /\.view-toggle\.on \{ opacity: 1; color: var\(--shared\); \}/.test(html), 'violet when on, a quiet grey when off');
  assert(/<\/div>\s*<button type="button" class="view-toggle" id="viewToggle" aria-pressed="false" aria-label="View">/.test(html) && !/id="viewToggle"[^>]*(title|NSFW)/.test(html),
    'the other view: a plain button at its right, saying nothing of what it shows');
  assert(/\.collections:not\(\[hidden\]\) \{[^}]*background: var\(--bg\); border: 1px solid var\(--line\)/.test(html), 'open, a dark bordered box of its own');
  assert(box.includes('<span class="tile-name">Mine &lt;i&gt;</span>') && /<button type="button" class="tile-cover" data-grid-collection="c_1"[^>]*><img [^>]*src="\/image-runs\/image_1\/thumbnails\/2\?v=1"><span class="album-count">2<\/span><\/button>/.test(box)
    && box.indexOf('class="tile-cover"') < box.indexOf('class="tile-name"') && box.includes('data-edit-collection="c_1"')
    && !box.includes('<details') && !box.includes('data-delete-collection') && !box.includes('collections-head'),
    'a tile: its first image with how many, its name small beneath (escaped), a pen to edit; no arrange for one');
  assert(/\.tile-name \{[^}]*font-size: \.7rem;/.test(html), 'the name is small text');
  assert(!els.collections.hidden);
  // The picture chosen for it, if still there; else the first image, else the first film.
  assert.strictEqual(JSON.stringify(run("collectionCover({ id: 'c_1', cover: { kind: 'film', name: 'F.mp4' } })")), '{"film":{"name":"F.mp4","run":"run_1","collection":"c_1"}}', 'a chosen film');
  assert(run("collectionCover({ id: 'c_1', cover: { kind: 'image', set: 'image_1', file: 'gone.png' } }).image.file") === 'b.png', 'one that has left it: the first image again');
  assert(run("collectionHtml({ id: 'c_1', name: 'x', cover: { kind: 'film', name: 'F.mp4' }, items: [{ kind: 'image', set: 'image_1', file: 'b.png' }, { kind: 'film', name: 'F.mp4' }] })").includes('src="/runs/run_1/image"'), 'shown by it');
  // In the preview: up and down go between its albums, and no further.
  run("viewerCollection = 'c_1'; viewing = { id: 'image_1', position: 2 }");
  assert.strictEqual(run('stepSet(-1)'), false, 'nothing above its images');
  assert(run("typeof collectionNeighbour(1)") === 'object' && run('collectionNeighbour(1)') === null, 'the only image: none beside it');
  // Move: the image open, by its set and file.
  assert.strictEqual(JSON.stringify(run('viewedItem()')), '{"kind":"image","run":"image_1","file":"b.png"}');
  run("viewing = { film: true, name: 'F.mp4', folder: 'video' }");
  assert.strictEqual(JSON.stringify(run('viewedItem()')), '{"kind":"film","name":"F.mp4"}');
  assert(!els.collectionsToggle.hidden && /<div class="output-filter-line not-shorts">\s*<button type="button" class="collections-toggle" id="collectionsToggle"/.test(html)
    && /\.collections-toggle \{ position: absolute; left: 0;/.test(html), 'its icon at the left of the line, shown to begin with');
  const keptStorage = { get: context.localStorage.getItem, set: context.localStorage.setItem };
  context.localStorage.setItem = (key, value) => { context.savedShown = [key, value]; };
  els.collectionsToggle.listeners.click();
  assert(els.collections.hidden && JSON.stringify(context.savedShown) === '["gen-center.collectionsShown","0"]', 'a tap hides them, and is remembered');
  context.localStorage.getItem = key => (key === 'gen-center.collectionsShown' ? '0' : null);
  run("collections = [...collections]; document.getElementById('collections').dataset.key = ''; renderCollections()");
  assert(els.collections.hidden && !els.collectionsToggle.hidden, 'kept hidden on the next draw, the icon still there');
  context.localStorage.getItem = keptStorage.get;
  context.localStorage.setItem = keptStorage.set;
  // Two or more: an arrange icon above the tiles, each tile dragged where it goes; the one placed takes its place among
  // those shown, and any not shown (here the NSFW one) stays where it was.
  run(`collections = ['c_1', 'c_h', 'c_2', 'c_3'].map(id => ({ id, name: id, nsfw: id === 'c_h', items: [{ kind: 'film', name: 'F.mp4' }] })); document.getElementById('collections').dataset.key = ''; renderCollections()`);
  const arranged = els.collections.innerHTML;
  assert(arranged.includes('class="collections-arrange" data-arrange-collections="1"') && !arranged.includes('data-collection="c_h"')
    && /data-collection="c_1" data-grid-index="0"/.test(arranged) && /data-collection="c_3" data-grid-index="2"/.test(arranged), 'arrange, and a numbered tile for each shown');
  run("placeCollections(['c_1', 'c_3', 'c_2'])");
  assert.strictEqual(JSON.stringify(run('collections.map(c => c.id)')), '["c_1","c_h","c_3","c_2"]', 'it takes its neighbour\'s place; the one not shown keeps its own');
  assert(els.collections.innerHTML.indexOf('data-collection="c_3"') < els.collections.innerHTML.indexOf('data-collection="c_2"'), 'drawn at once in the new order');
  // Arranging: a tap picks a tile (nothing opens), and only the picked one is dragged.
  const tile = id => ({ dataset: { collection: id }, closest(sel) { return sel.includes('.collection-tile') ? this : null; } });
  const tapped = [];
  const press = (target, dataset = {}) => els.collections.listeners.click({ target: { closest(sel) { return sel.includes('data-arrange-collections') && dataset.arrangeCollections ? { dataset, closest: () => null } : { dataset, closest: s => (s === '.collection-tile' ? tile(target) : null) }; } }, preventDefault() {} });
  press('c_1', { arrangeCollections: '1' });
  assert(run('collectionsArranging') === true && run('collectionSelected') === null, 'arrange on');
  press('c_3', { gridCollection: 'c_3' });
  assert(run('collectionSelected') === 'c_3', 'a tap picks it, nothing opens');
  press('c_3', { gridCollection: 'c_3' });
  assert(run('collectionSelected') === null, 'again lets it go');
  press('c_1', { arrangeCollections: '1' });
  assert(run('collectionsArranging') === false, 'arrange off');
  run("viewing = null; viewerCollection = null; collectionsArranging = false; collectionSelected = null");
  // Edit: name and picture; the picture is any of its own, or Automatic (the first image).
  for (const id of ['collectionEdit', 'collectionEditName', 'collectionEditPicker', 'collectionEditSave', 'collectionEditDelete', 'collectionEditCancel']) context.document.getElementById(id);
  run(`allImageSets = [{ id: 'image_1', label: 'S', images: [{ position: 1, file: 'a.png', title: 'a', version: 1 }, { position: 2, file: 'b.png', title: 'b', version: 1 }] }];
       collections = [{ id: 'c_1', name: 'Mine', items: [{ kind: 'image', set: 'image_1', file: 'a.png' }, { kind: 'image', set: 'image_1', file: 'b.png' }], cover: { kind: 'image', set: 'image_1', file: 'b.png' } }];
       $('collectionEdit').showModal = () => {}; openCollectionEdit('c_1')`);
  const picker = els.collectionEditPicker.innerHTML;
  assert(els.collectionEditName.value === 'Mine' && picker.includes('data-pick="auto"') && picker.includes('data-pick="0"') && picker.includes('data-pick="1"')
    && run('collectionEditing.pick') === 1, 'name filled in, its own pictures to pick from, its present one picked');
  assert(/<dialog id="collectionEdit" class="panel-dialog collection-edit"/.test(html) && /id="collectionEditDelete"/.test(html), 'a dialog with delete in it');
  run("viewing = null; viewerCollection = null; collections = []; allImageSets = []; renderCollections()");
  assert(els.collections.hidden && els.collectionsToggle.hidden, 'none: no box, no icon');
}
// Private mode's key in the top bar, by Settings: lit while on, and a tap turns it the other way.
{
  assert(/<div class="top-icons" id="topIcons">\s*<a href="#" id="privateToggle" role="button" aria-pressed="false"[^>]*><svg[\s\S]*?<\/a>\s*<a href="#" id="settingsBtn"/.test(html), 'the key, before Settings');
  for (const id of ['privateToggle', 'privateMode']) context.document.getElementById(id);
  const lit = new Set();
  els.privateToggle.classList = { toggle: (name, on) => (on ? lit.add(name) : lit.delete(name)), add() {}, remove() {}, contains: name => lit.has(name) };
  run('renderPrivate(true)');
  assert(lit.has('on') && els.privateToggle.title === 'Private mode (NSFW): on', 'lit while on');
  let sent;
  const keptFetch = context.fetch;
  context.fetch = (url, options) => { sent = { url, body: JSON.parse(options.body) }; return new Promise(() => {}); };
  els.privateToggle.listeners.click({ preventDefault() {} });
  context.fetch = keptFetch;
  assert(sent.url === '/api/private' && sent.body.on === false, 'a tap asks for it off');
  // Turned on, it opened Output on the NSFW filter: back to all, for what follows.
  run("renderPrivate(false)");
  assert.strictEqual(run('nsfwView'), false, 'Private mode off: the NSFW view goes off with it');
  run(`renderFinished([{ label: 'Hot', outcome: 'done', at: '17:06', pipeline: 'image', run_id: 'image_9', job_id: 9, nsfw: true }], [], [])`);
  assert(!els.finishedList.innerHTML.includes('Hot'), 'and Finished shows nothing NSFW');
  run('renderFinished([], [], [])');
}
// Arranging in the grid: the button left of Close, lit while on; a tap picks one rather than opening it.
{
  assert(/<div class="thumb-grid-foot">\s*<button type="button" class="thumb-grid-arrange" id="thumbGridArrange"[^>]*><\/button>\s*<button type="button" class="panel-close" id="thumbGridClose">/.test(html), 'arrange, left of Close');
  for (const id of ['thumbGrid', 'thumbGridArrange', 'thumbGridBody']) context.document.getElementById(id);
  const lit = new Set();
  els.thumbGridArrange.classList = { toggle: (name, on) => (on ? lit.add(name) : lit.delete(name)), add() {}, remove() {}, contains: name => lit.has(name) };
  run(`allImageSets = imageSets = [{ id: 'image_1', label: 'S', images: [{ position: 1, file: 'a.png', title: 'a', version: 1 }, { position: 2, file: 'b.png', title: 'b', version: 1 }] }];
       openThumbGrid({ set: 'image_1' })`);
  assert(!els.thumbGridArrange.hidden && !lit.has('on'), 'offered for a set, off to begin with');
  els.thumbGridArrange.listeners.click();
  assert(lit.has('on') && run('thumbGridArranging'), 'lit while arranging');
  context.opened = [];
  run('oldOpenViewer = openViewer; openViewer = (id, position) => opened.push(position)');
  els.thumbGridBody.listeners.click({ target: { closest: () => ({ dataset: { gridIndex: '1' } }) } });
  assert(run("thumbGridSelected === '1'") && context.opened.length === 0, 'a tap picks it, and opens nothing');
  assert.strictEqual(JSON.stringify(run('thumbGridItems.map(item => item.ref)')), '["a.png","b.png"]', 'a set is ordered by its files');
  run("openThumbGrid({ films: 'video' })");
  assert(els.thumbGridArrange.hidden && !run('thumbGridArranging'), 'not for the films in Video: they are in the order made');
  run('openViewer = oldOpenViewer; allImageSets = imageSets = []');
}
// Move: a menu growing over the preview's buttons, as Upscale's: + New on top, then the collections.
{
  assert(/<dialog id="moveSheet" class="panel-dialog upscale-dialog move-menu"/.test(html) && /dialog#viewerUpscaleBar, dialog#moveSheet, dialog#pillsMenu, dialog#editMenu \{[^}]*animation: menu-in/.test(html), 'it grows as the upscale menu does');
  for (const id of ['moveSheet', 'moveList', 'moveNewRow', 'moveNewName', 'moveError']) context.document.getElementById(id);
  run(`allImageSets = [{ id: 'image_1', images: [{ position: 1, file: 'a.png' }] }]; collections = [{ id: 'c_1', name: 'Mine', items: [] }];
       viewing = { id: 'image_1', position: 1 }; viewerCollection = null; oldPlace = placeOverViewerButtons; placeOverViewerButtons = () => {}`);
  run('openMoveSheet()');
  const menu = els.moveList.innerHTML;
  assert(menu.indexOf('data-move-new="1"') < menu.indexOf('data-move-to="c_1"') && menu.includes('>New</button>') && els.moveNewRow.hidden, '+ New first, its name only once asked for');
  els.moveNewName.focus = () => {};
  els.moveList.listeners.click({ target: { closest: selector => (selector === '[data-move-new]' ? {} : null) } });
  assert(!els.moveNewRow.hidden, '+ New: its name, in the menu');
  run(`collections = [{ id: 'c_1', name: 'Mine', items: [] }, { id: 'c_2', name: 'Hot', nsfw: true, items: [] }]; privateMode = false; nsfwView = false; openMoveSheet()`);
  assert(!els.moveList.innerHTML.includes('c_2'), 'one with NSFW in it: not offered with Private mode off');
  run('privateMode = true; openMoveSheet()');
  assert(!els.moveList.innerHTML.includes('data-move-to="c_2"') && !els.moveList.innerHTML.includes('data-move-to="c_1"'),
    'in Private mode without the NSFW filter: no NSFW one is shown, and the others are not its kind');
  run('nsfwView = true; openMoveSheet()');
  assert(!els.moveList.innerHTML.includes('data-move-to="c_1"') && els.moveList.innerHTML.includes('data-move-to="c_2" class="nsfw"'), 'in Private mode, under the NSFW filter: only those, dark red');
  run('privateMode = false; openMoveSheet()');
  assert(els.moveList.innerHTML.includes('c_1') && els.moveList.innerHTML.includes('c_2'), 'out of it, under the NSFW filter: all of them');
  run("nsfwView = false");
  // A batch: one main row with how many and a chevron; its items under it, set in, a tap away. Going, from what it
  // has made; done, from its set's pictures.
  run(`imageSets = [{ id: 'image_5', images: [{ position: 1, version: 1, title: 'A' }, { position: 2, version: 1, title: 'B' }, { position: 3, version: 1, title: 'C' }] }];
    renderFinished([], [], [{ label: 'One', outcome: 'done', at: '17:01', t: 1, pipeline: 'image', run_id: 'image_5', position: 1 },
      { label: 'Two', outcome: 'done', at: '17:02', t: 2, pipeline: 'image', run_id: 'image_5', position: 2 }])`);
  {
    const going = els.finishedList.innerHTML;
    assert(/<div class="result-batch" data-batch="image:image_5"><button[^>]*class="result done batch-main"[\s\S]*?<span class="batch-count">2<\/span><span class="batch-chevron"/.test(going)
      && (going.match(/batch-kid"/g) || []).length === 2 && going.split('data-key="made:image_5:2"').length - 1 === 2, 'going: the newest heads it; both are its items');
  }
  run(`renderFinished([{ label: 'Set of 3', outcome: 'done', at: '17:03', t: 3, pipeline: 'image', run_id: 'image_5', job_id: 7 }], [], [])`);
  {
    const done = els.finishedList.innerHTML;
    assert(/class="result done batch-main"[^>]*data-job-id="7"[\s\S]*?Set of 3[\s\S]*?<span class="batch-count">3<\/span>/.test(done)
      && ['A', 'B', 'C'].every(t => done.includes(`<span class="result-label">${t}</span>`)) && /class="result done batch-kid"[^>]*data-position="3"/.test(done), 'done: one row, its pictures under it');
    assert(!done.includes('result-batch open'), 'folded to begin with');
    const main = { classList: { contains: () => false }, parentElement: null };
    const batch = { dataset: { batch: 'image:image_5' }, classList: { on: false, contains() { return this.on; }, toggle(c, v) { this.on = v; } } };
    main.parentElement = batch;
    els.finishedList.listeners.click({ target: { closest: sel => (sel === '.batch-main' ? main : null) } });
    assert(batch.classList.on && run("openBatches.has('image:image_5')"), 'a tap on the main row opens it, and it stays open');
    run('renderFinished(...lastFinished)');
    assert(els.finishedList.innerHTML.includes('result-batch open'), 'still open at the next poll');
    run("openBatches.clear(); imageSets = []; renderFinished([], [], [])");
  }
  assert(/\.batch-kids \{ display: grid; grid-template-rows: 0fr;/.test(html) && /\.batch-kids-in \{[^}]*margin-left: 16px;[^}]*border-left: 2px solid var\(--line\); \}/.test(html), 'growing to their height, set in a little');
  assert(/\.batch-kids-in \{[^}]*overflow: clip;/.test(html) && /\.result-thumb \{[^}]*overflow: clip;/.test(html),
    'opened, a set scrolls with the list: clipped, not a scroll box of its own');
  run('privateMode = false');
  run('placeOverViewerButtons = oldPlace; viewing = null; collections = []; allImageSets = []; $("moveSheet").close()');
}
// In the grid, a tap opens only if the finger stayed put and the grid wasn't moving.
{
  run('gridTap = { x: 10, y: 10, at: 100, moving: false }; gridScrolledAt = 0');
  assert.strictEqual(run("gridTapped({ clientX: 13, clientY: 12, pointerType: 'touch' })"), true, 'a tap');
  run('gridTap = { x: 10, y: 10, at: 100, moving: false }; gridScrolledAt = 150');
  assert.strictEqual(run("gridTapped({ clientX: 10, clientY: 60, pointerType: 'touch' })"), false, 'a scroll is not a tap');
  run('gridTap = { x: 10, y: 10, at: 100, moving: true }; gridScrolledAt = 90');
  assert.strictEqual(run("gridTapped({ clientX: 10, clientY: 10, pointerType: 'touch' })"), false, 'a tap that stops a fling only stops it');
  // Pinch: the pictures' size between its least and most, kept; fingers lifted off a pinch don't open one.
  run('setThumbSize(1000)');
  assert.strictEqual(run('thumbSize'), 260, 'no bigger than its most');
  run('setThumbSize(5)');
  assert.strictEqual(run('thumbSize'), 48, 'no smaller than its least');
  run('setThumbSize(78); gridTap = { x: 10, y: 10, at: 100, moving: false }; gridScrolledAt = 0; gridPinchedAt = performance.now()');
  assert.strictEqual(run("gridTapped({ clientX: 10, clientY: 10, pointerType: 'touch' })"), false, 'the end of a pinch is no tap');
  run('gridPinchedAt = -Infinity');
  assert(/\.thumb-grid \{ display: grid; grid-template-columns: repeat\(auto-fill, minmax\(var\(--thumb-size, 78px\), 1fr\)\);/.test(html)
    && /\.thumb-grid-dialog \.panel-dialog-body \{[^}]*touch-action: pan-y; \}/.test(html)
    && script.includes("$('thumbGridBody').addEventListener('touchmove', e => {") && script.includes('}, { passive: false });'),
    'the grid sizes its pictures by the pinch, and two fingers pinch it rather than zoom the page');
  assert(/\.thumb-grid button\.current \{ outline: 2px solid var\(--accent\); outline-offset: -2px; \}/.test(html)
    && /button\.selected \{ outline: 2px dotted var\(--accent\); outline-offset: -2px;/.test(html), 'outlines inside the picture; the one held dotted');
  assert(/\.grid-ghost \{ margin: 0; padding: 0; border: 0; background: #000;[^}]*outline: 2px dotted color-mix\(in srgb, var\(--accent\) 55%, #000\)/.test(html) && script.includes("ghost.classList.add('grid-ghost')"), 'dragged, a copy follows the finger');
}
assert(/\.image-set-actions \[data-grid-set\], \.image-set-actions \[data-grid-collection\] \{ margin-right: auto; \}/.test(html), "the grid's button at the left, beside the cover");
// Output never shows what it drew before (another filter, Private mode since changed): held until a fresh answer.
assert(/#videos, #imageSets, #collections, #cnav \{ transition: opacity \.25s ease; \}/.test(html) && /body\.output-pending #cnav \{ visibility: hidden; opacity: 0; transition: none; \}/.test(html)
  && /body\.output-pending #videos, body\.output-pending #imageSets, body\.output-pending #collections,/.test(html)
  && /if \(page === 'output' && document\.body\.dataset\.page !== 'output'\) \{\s*holdOutput\(\);\s*resetOutputView\(\);/.test(script)
  && script.includes("window.addEventListener('pageshow', holdOutput);") && script.includes("if (askedAt >= outputHeldAt) document.body.classList.remove('output-pending');"),
  'held out of sight on going to Output and on coming back, until drawn from an answer asked for after');
// The preview's pills never grow in place: "+N" opens them all in a box over its buttons.
{
  for (const id of ['pillsMenu', 'pillsMenuBody']) context.document.getElementById(id);
  context.oldPlace = run('placeOverPills');
  run('placeOverPills = () => {}');
  const line = { innerHTML: '<span class="pill">a</span><span class="pill spill">b</span>', classList: { contains: name => name === 'image' || name === 'more' },
    closest: selector => (selector === '.viewer-meta-details' ? {} : null) };
  context.testLine = line;
  run('openPillsMenu(testLine)');
  assert(els.pillsMenu.open && els.pillsMenuBody.innerHTML.includes('>b<') && els.pillsMenuBody.className === 'pills image open', 'all of them, in their colour');
  run('placeOverPills = oldPlace; $("pillsMenu").close()');
  assert(script.includes('placeOverPills(box, line);') && script.includes("box.style.top = `${Math.max(8, at.bottom + 4 - box.getBoundingClientRect().height)}px`;"), 'grown up out of the pill line');
  assert(/<dialog id="pillsMenu" class="panel-dialog upscale-dialog pills-menu"/.test(html) && script.includes("if (line.closest('.viewer-meta-details')) {"), 'a box, growing as Move does');
}
assert(script.includes("if (pick) moveViewed({ to: pick.dataset.moveTo }, pick);") && /button\.picked \{ background: color-mix\(in srgb, var\(--accent\) 30%/.test(html)
  && /dialog#moveSheet\.moving \.upscale-methods button:not\(\.picked\) \{ opacity: \.4;/.test(html), 'the collection tapped lights up while it moves, the others dimmed');
// A clicked button's request on its way: it pulses until the answer is back.
{
  const classes = new Set(), attrs = {};
  context.busyButton = { classList: { toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)) }, setAttribute: (k, v) => { attrs[k] = v; } };
  run('markBusy(busyButton, 1)');
  assert(classes.has('is-busy') && attrs['aria-busy'] === 'true', 'busy while its request is out');
  run('markBusy(busyButton, -1)');
  assert(!classes.has('is-busy') && attrs['aria-busy'] === 'false', 'and back once answered');
  assert(script.includes("if (button && (button.closest('.count-stepper') || button.closest('[data-no-busy]'))) { lastPressed = null; return; }"), "a stepper's + and - never wait on the last press");
  assert(/\.is-busy \{ animation: busy-pulse/.test(html) && script.includes("const QUIET_REQUESTS = "), 'polls and estimates never pulse anything');
}
assert(/\.thumb-grid button \{[^}]*overflow: clip;/.test(html) && !/\.thumb-grid button \{[^}]*overflow: hidden/.test(html), 'a swipe on a picture scrolls the grid');
assert(/button, \[role="button"\], \.icon-btn, summary, \.count-stepper, \.count-stepper \.mp-field, \.pills, \.pill \{\s*-webkit-user-select: none; user-select: none; -webkit-touch-callout: none; \}/.test(html),
  'pressing a button or stepper quickly never selects its text');
assert(/\.prompt-progress::after \{[^}]*animation: bar-sheen 3\.6s/.test(html), "the prompt's bar has the light passing along it, as the others");
assert(script.includes("const other = at < 0 ? null : album[at + 1] || album[at - 1];") && script.includes("if (picture) openViewer(set.id, picture.position); else closeViewer();"),
  'deleting in a collection: on to the next in its album, found by its file');
assert(script.includes("if (was !== side) carryImages(was, side);") && script.includes("if (boxes().some(box => box.querySelector('input').files.length)) return;"),
  "switching side, the images chosen go into the other's empty boxes");
// Edit in the preview: a menu growing as the others do, to edit the image or make a video from it, each bordered
// in its page's colour; the video one's preset is a setting beside the image one's.
assert(/<button type="button" data-edit-to="image" style="--side:var\(--c-image\)"[^>]*>Edit image<\/button>\s*<button type="button" data-edit-to="video" style="--side:var\(--c-video\)"[^>]*>Make a video<\/button>/.test(html)
  && /dialog#editMenu \.upscale-methods button \{ text-align: center; border: 1px solid var\(--side\); \}/.test(html)
  && html.includes('<select id="editVideoPreset"') && script.includes("saveSettings({ edit_video_preset: $('editVideoPreset').value })")
  && script.includes("if (to === 'video') videoFromImage(id, position); else editInGenerate(id, position);"), 'Edit: image or video, by its page colour');
assert(/async function videoFromImage[\s\S]*?backToGenerate\('video'\);\s*\}/.test(script), "a video from an image lands on Video's Generate, not Image's");
// Picking from Output: a tap opens the preview, where Use (sharing Close's row) chooses it.
assert(/<button type="button" class="plain viewer-use" id="viewerUse" hidden[^>]*>Use<\/button>\s*<button type="button" class="plain" id="viewerClose">Close<\/button>/.test(html) && !script.includes("$('viewerMove').hidden = !!choosingFor;")
  && !script.includes('if (choosingFor) { chooseThis(view.dataset.viewSet') && script.includes("chooseThis(id, position);")
  && /\.viewer-actions\.choosing > button\.plain \{ flex: 1 1 0;/.test(html), 'Use beside Close while choosing; a tap on a thumbnail only opens it');
// Any box picks from Output: a reference box picks a film, with Use in its preview.
assert(/Select reference \$\{number\} from Output/.test(html) && script.includes("chooseFromOutput(pick.closest('.image-box'), 'video', 'media')")
  && script.includes("const choosing = !!choosingFor && (choosingFor.kind === 'media' ? video : !video);") && script.includes('chooseFilm(name, from);'),
  'reference boxes pick films too, Use choosing them');
const single = run("imageSetHtml({ id: 'image_9', label: 'One', total: 1, size: '1x1', when: 'now', images: [{ position: 1, title: 'x', version: 1 }] })");
assert(/<a href="\/image-runs\/image_9\/files\/1\?v=1" data-view-set="image_9" data-view-position="1"[^>]* class="album-cover">/.test(single) && !single.includes('album-count') && !single.includes('data-grid-set'),
  'one image: the same picture box, opening it, no count');
assert(/class="icon-btn del" data-delete-set="image_9"[^>]*aria-label="Delete"><svg/.test(single), 'icons, named');
assert(/<div class="image-set-actions"><button type="button" class="icon-btn" data-again-set="image_9"[^>]*aria-label="The same again"><svg[\s\S]*?data-shots="image_9"[\s\S]*?data-delete-set="image_9"/.test(single), 'the same again, then prompts, then delete');
assert(single.includes(`aria-label="The same again">${run('ICONS.config')}</button>`) && run('ICONS.config !== ICONS.again'), 'same again uses settings, distinct from retry');
for (const side of ['shorts', 'video', 'image']) {
  assert(html.includes(`data-preset-delete="${side}" title="Delete this preset" aria-label="Delete this preset" hidden>${run('ICONS.trash')}</button>`), 'preset deletion uses the shared trash icon');
}
assert(html.includes(`id="paintClear" title="Clear all paint" aria-label="Clear all paint">${run('ICONS.trash')}</button>`), 'clear paint uses the shared trash icon');
// It puts every option back as the set had it, the rest at the workflow's own default.
{
  const fields = {};
  const field = (name, type, extra = {}) => (fields[name] = { name, type, value: '', checked: false, ...extra });
  field('opt_up', 'checkbox'); field('opt_steps', 'number'); field('opt_lora_on', 'checkbox'); field('opt_lora_strength', 'number', { value: '1' });
  context.optBox2 = { dataset: {}, querySelector: selector => fields[/name="([^"]+)"/.exec(selector)[1]] || null };
  context.optDefs = [{ id: 'up', kind: 'switch', default: '0' }, { id: 'steps', kind: 'number', default: '20' }, { id: 'lora', kind: 'strength', default: '0' },
    { id: 'prompt_enhancer', kind: 'switch', default: '0', role: 'llm' }];
  run(`applyOptions(optBox2, optDefs, { up: '1', lora: '0.8', prompt_enhancer: '1' })`);
  assert(fields.opt_up.checked === true && fields.opt_steps.value === '20' && fields.opt_lora_on.checked === true && fields.opt_lora_strength.value === '0.8');
}
assert(/\.image-set-actions \{[^}]*justify-content: flex-end;[^}]*margin-top: auto;/.test(html) && /\.album-cover \{[^}]*width: 92px; height: 92px;/.test(html), 'the icons sit in the same place on every set');
assert(/\.image-set-row\.album \{ align-items: stretch; \}/.test(html) && /\.collection-tiles \{ display: grid; grid-template-columns: repeat\(auto-fill, minmax\(84px, 1fr\)\);/.test(html), "a collection's tiles in a grid");
assert(/\.album-cover img \{ position: absolute; inset: 0;/.test(html) && !/\.album-cover \{[^}]*min-height/.test(html), 'the cover is as tall as the buttons, not its picture');
assert(/input\[type=file\]::file-selector-button/.test(html), 'choosing a file has a real button');
run('imageSets = sets; renderImageSets()');
const once = els.imageSets.innerHTML;
assert(once.includes('2 of 3'));
els.imageSets.innerHTML = 'untouched';
run('renderImageSets()');
assert.strictEqual(els.imageSets.innerHTML, 'untouched', 'a poll with nothing new reloads no pictures');
const imageRun = { id: 'image_1', is_image: true, title: 'T', brief: 'b', llm: 'claude', direct: false, size: '1024x1024', busy: false, finished: false,
  shots: [{ title: 'One', prompt: '</textarea><script>x</script>', rendered: true, version: 1 }, { title: 'Two', prompt: 'p', rendered: false, version: 0 }] };
context.imageRun = imageRun;
const imageDialog = run('shotsHtml(imageRun)');
assert(!imageDialog.includes('<script>'), 'prompts are escaped');
assert(!imageDialog.includes('data-redo=') && imageDialog.includes('Make the 1 left') && imageDialog.includes('data-delete-image="2"'));
context.imageRun.pending = true;
const pendingImageDialog = run('shotsHtml(imageRun)');
assert(pendingImageDialog.includes('data-save="1"') && !pendingImageDialog.includes('readonly') && !pendingImageDialog.includes('data-redo=') && !pendingImageDialog.includes('data-delete-image=') && !pendingImageDialog.includes('data-render='), 'pending images allow prompt edits but not duplicate or destructive actions');
delete context.imageRun.pending;
context.pendingFilm = { ...shots, busy: false, pending: true, finished: false };
const pendingFilmDialog = run('shotsHtml(pendingFilm)');
assert(pendingFilmDialog.includes('data-save="1"') && !pendingFilmDialog.includes('readonly') && !pendingFilmDialog.includes('data-redo=') && !pendingFilmDialog.includes('data-render='), 'pending films allow prompt edits without starting twice');
// A set's prompts: a carousel, its count on the right of the title, the original prompt behind the title; small buttons under it.
assert(/<div class="shots-list carousel" id="shotsCarousel">/.test(imageDialog) && /<h2 class="shots-title">T<\/h2>\s*<span class="shots-count" id="shotsCount">1 of 2<\/span>/.test(imageDialog));
assert(/<div class="shots-list carousel" id="shotsCarousel">/.test(dialog) && dialog.includes('<span class="shots-count" id="shotsCount">1 of 2</span>'), 'a film\'s shots swipe the same way');
assert(script.includes("document.execCommand('copy')"), 'on a shade of its own; copying works over plain http on a phone too');
assert(!imageDialog.includes('Making an image again leaves') && imageDialog.includes('<div class="shots-foot centred small">') && !/shots-foot[^>]*>[^<]*<button[^>]*data-save/.test(imageDialog));
assert(/\.shots-foot button \{ flex: 0 1 auto; min-width: 96px; padding: 6px 18px; font-size: \.82rem;/.test(html), 'small buttons, as Quota\'s Close');
assert(!imageDialog.includes('finished</span>') && !imageDialog.includes('not made yet') && !run('shotsHtml(shots)').includes('not rendered yet'), 'no rendered or finished text on the items');
// Each item: more like this (and what an enhancer wrote) on the left; its seed, save and delete on the right.
for (const [what, built] of [['image', imageDialog], ['film', dialog]]) {
  assert(!built.includes('data-redo=') && /<div class="shot-actions-left"><button type="button" class="icon-btn" data-create="1"[^>]*aria-label="More like this[^"]*"><svg[^]*?<\/button><\/div>/.test(built) && !built.includes('data-prompt-open'), `${what}: more like this on the left; the prompt is its box`);
  assert(/<div class="shot-actions-right"><input type="hidden" id="seed_1" data-seed value="[^"]*"><button type="button" class="icon-btn seed-icon"[^>]*data-seed-open="1"[\s\S]*?data-save="1"[^>]*aria-label="Save the prompts"><svg/.test(built), `${what}: its seed, then save, on the right`);
}
assert(/data-save="1"[\s\S]*?<\/button><button type="button" class="icon-btn del" data-delete-image="1"[\s\S]*?<\/div>\s*<\/div>/.test(imageDialog), 'save, then delete, last');
assert(!/seed-icon pinned/.test(imageDialog) && !/\.seed-icon\.pinned/.test(html), 'a pinned seed is not lit');
assert(!imageDialog.includes('data-enhanced=') && !imageDialog.includes('briefFold'), 'no detailed prompt button where no enhancer wrote one');
context.imageRun.shots[0].enhanced_prompt = 'A <b>bright</b> lighthouse';
const withEnhanced = run('shotsHtml(imageRun)');
assert(/<div class="shot-actions-left"><button type="button" class="icon-btn" data-create="1"[\s\S]*?<\/button><button type="button" class="icon-btn" data-enhanced="1" aria-haspopup="dialog"/.test(withEnhanced), 'what the enhancer wrote, beside more like this on the left');
assert(!withEnhanced.includes('A &lt;b&gt;bright') && /\.prompt-detail-text \{[^}]*overflow-y: auto/.test(html)
  && /\.prompt-detail-actions \{ flex: none;/.test(html), 'the prompt opens separately with a fixed footer');
delete context.imageRun.shots[0].enhanced_prompt;
assert(/dialog\.viewer \.viewer-actions > \* \{[^}]*height: 32px;/.test(html), 'the viewer\'s buttons small too');
assert(/\$\('shotsDialog'\)\.addEventListener\('click', e => \{\s*if \(e\.target\.closest && \(e\.target\.closest\('\.seed-fold'\) \|\| e\.target\.closest\('\[data-fold\]'\)\)\) return;\s*closeSeedFolds\(\);/.test(script),
  'a tap anywhere else puts the seed away');
assert.strictEqual(run("runUrl('image_1')"), '/image-runs/image_1');
assert.strictEqual(run("runUrl('run_1')"), '/runs/run_1');
const picked = (aspect, megapixels, source) => {
  els.imageAspect.value = aspect;
  els.imageMegapixels.value = megapixels;
  run(`sourceSize = ${JSON.stringify(source)}`);
  return run(`pickedSize(${megapixels === 'image' ? 'null' : megapixels}).join("x")`);
};
assert.strictEqual(picked('1:1', '1', null), '1024x1024');
assert.strictEqual(picked('16:9', '1', null), '1360x768');
assert.strictEqual(picked('image', '1', null), '1024x1024', 'nothing to match: square');
assert.strictEqual(picked('image', 'image', [800, 1200]), '800x1200', 'the image\'s own resolution');
assert.strictEqual(picked('image', '1', [800, 1200]), '832x1248', 'its shape at the pixel count asked for');
assert.strictEqual(picked('1:1', 'image', [800, 1200]), '976x976', 'its pixel count in the shape asked for');
run('sourceSize = null');
// Automatic picks as the server does, and a model's limits grey out what it doesn't make well.
run(`imageWorkflowList = [{ min_images: 0, max_images: 0, size: true, model: 'krea2' }, { min_images: 1, max_images: 1, size: true, model: 'qwen_image_edit' },
  { min_images: 0, max_images: 16, size: true, model: 'fibo2' }]`);
assert.deepStrictEqual(['0', '1', '2', '17'].map(n => run(`(automaticTakes(${n}) || {}).model`)), ['krea2', 'qwen_image_edit', 'fibo2', undefined],
  'made for it first, Fibo 2.0 when nothing else fits');
els.imageAspect.options = [{ value: '1920x1080' }, { value: '1024x1024' }, { value: '3840x2160' }, { value: '16:9' }];
els.imageMegapixels.options = [{ value: 'image' }, { value: '1' }, { value: '2' }, { value: '6' }];
run(`imageWorkflows = { 'fibo.json': imageWorkflowList[2], 'krea.json': imageWorkflowList[0] }`);
els.imageWorkflow.value = 'fibo.json';
const fiboLimit = run('syncImageLimits()');
// Every screen stays pickable: past the model's pixel count it is made at the nearest below (imageResolution).
assert.deepStrictEqual(els.imageAspect.options.map(o => o.disabled), [false, false, false, undefined], 'Fibo 2.0: screens held, not greyed');
assert.deepStrictEqual(els.imageMegapixels.options.map(o => o.disabled), [undefined, false, true, true]);
assert(fiboLimit.includes('Fibo 2.0 makes images up to 1.1 MP'));
els.imageWorkflow.value = 'krea.json';
run('syncImageLimits()');
assert.deepStrictEqual(els.imageAspect.options.map(o => o.disabled), [false, false, false, undefined], 'Krea-2: 4K pickable, held below');
assert.deepStrictEqual(els.imageMegapixels.options.map(o => o.disabled), [undefined, false, false, true]);
els.imageWorkflow.value = '';
run('imageWorkflows = {}; imageWorkflowList = []');

// A workflow's own options: a checkbox says off too, what goes with a switch sits beside it, and a problem locks it.
context.options = [
  { id: 'group_2nd_pass', kind: 'switch', label: '2nd <b>pass', default: '1' },
  { id: 'group_up', kind: 'switch', label: 'Upscaler', default: '0' },
  { id: 'group_up.choice', kind: 'choice', label: 'Upscaler: choice', default: '4K', choices: ['1080p', '4K'], parent: 'group_up' },
  { id: 'face_lora_strength', kind: 'number', label: 'LoRA strength', default: '0.8', min: -2, max: 2, step: 0.05, parent: 'group_up' },
  { id: 'group_cc', kind: 'switch', label: 'Color correction', default: '0', problem: 'Needs <i>LayerColor' },
  { id: 'lora_k', kind: 'strength', label: 'LoRA: K', default: '0', min: -2, max: 2, step: 0.05, usual: '1' },
  { id: 'steps', kind: 'number', label: 'Steps', default: '8', min: 1, max: 150, step: 1 },
];
const optionsHtml = run('options.map(option => imageOptionHtml(option, options)).join("")');
assert(!optionsHtml.includes('<b>pass') && !optionsHtml.includes('<i>LayerColor'), 'labels and problems are escaped');
assert(/name="opt_group_2nd_pass" value="0"><input type="checkbox" name="opt_group_2nd_pass" value="1" checked/.test(optionsHtml), 'unticked still says so');
const upscaler = optionsHtml.slice(optionsHtml.indexOf('Upscaler'), optionsHtml.indexOf('Color correction'));
assert(upscaler.includes('name="opt_group_up.choice"') && upscaler.includes('<option value="4K" selected>4K</option>') && upscaler.includes('name="opt_face_lora_strength"'),
  'what goes with a switch is beside it');
// The LoRA setting: its switch, and under it while it's on, the file by name (no .safetensors) and its strength at the right.
const loraSettingHtml = run(`(() => { const all = [{ id: 'lora', kind: 'switch', label: 'Use LoRA', default: '0', advanced: true, below: true },
  { id: 'lora_name', kind: 'choice', label: 'LoRA', parent: 'lora', default: 'KNPV3_1.safetensors', choices: ['KNPV3_1.safetensors', 'b.safetensors'],
    labels: { 'KNPV3_1.safetensors': 'KNPV3', 'b.safetensors': 'b' } },
  { id: 'lora_strength', kind: 'number', label: 'Strength', parent: 'lora', default: '1', min: -2, max: 2, step: 0.05 }];
  return all.map(option => imageOptionHtml(option, all)).join(''); })()`);
assert(/<input type="checkbox" name="opt_lora" value="1">\s*<span>Use LoRA<\/span><\/label><div class="option-reveal" data-below="opt_lora"><div class="option-reveal-in"><div class="options-box option-row option-below"><select name="opt_lora_name"[^>]*><option value="KNPV3_1.safetensors" selected>KNPV3<\/option><option value="b.safetensors">b<\/option><\/select><input type="number" class="option-strength" name="opt_lora_strength"[^>]*value="1"/.test(loraSettingHtml),
  'off, its file and strength wait folded under it, in a dark box; each file said by name');
assert(/\.option-reveal \{ display: grid; grid-template-rows: 0fr; opacity: 0; transition: grid-template-rows \.3s/.test(html) && /\.option-reveal\.open \{ grid-template-rows: 1fr; opacity: 1; \}/.test(html)
  && script.includes("if (toggle) under.classList.toggle('open', toggle.checked);"), 'ticked, the box grows open smoothly');
// Steps, Sampler, Scheduler and CFG first, in a dark box, each named by a button with a hint; then Use LoRA in its own box.
run(`syncOptions('testOptions', 'testOptionsBox', [{ id: 'group_x', kind: 'switch', label: 'X', default: '0' },
    { id: 'lora', kind: 'switch', label: 'Use LoRA', default: '0', advanced: true, below: true },
    { id: 'cfg', kind: 'number', label: 'CFG', parent: 'steps', default: '1', min: 0, max: 30, step: 0.1, advanced: true },
    { id: 'steps', kind: 'number', label: 'Steps', default: '8', min: 1, max: 150, step: 1, advanced: true },
    { id: 'sampler', kind: 'choice', label: 'Sampler', parent: 'steps', default: 'euler', choices: ['euler', 'er_sde'], advanced: true },
    { id: 'switch_lightning_lora', kind: 'switch', label: 'Lightning LoRA (turbo)', default: '0', advanced: true, speed: true, primitive: true, below: true },
    { id: 'switch_lightning_lora_name', kind: 'choice', label: 'LoRA', parent: 'switch_lightning_lora', default: 't.safetensors', choices: ['t.safetensors', 'u.safetensors'], labels: { 't.safetensors': 't' }, advanced: true, speed: true },
    { id: 'switch_lightning_lora_strength', kind: 'number', label: 'Strength', parent: 'switch_lightning_lora', default: '1', min: -2, max: 2, step: 0.05, advanced: true, speed: true }], 'w')`);
const laidOut = els.testOptionsBox.innerHTML;
assert(/^<div class="options-section"><div class="options-subtitle">Sampling<span class="options-subtitle-what"> · how each picture is worked<\/span><\/div><div class="options-sampling"><div class="option-row sampling-line"><button type="button" class="res-info option-info"[^>]*><span>Steps<\/span>[\s\S]*?<span>Sampler<\/span>[\s\S]*?<span>CFG<\/span>[\s\S]*?<\/div><div class="options-lora options-speed"><div class="options-subtitle">Turbo LoRA<span class="options-subtitle-what"> · fewer steps, faster<\/span><\/div>[\s\S]*?<div class="options-lora"><div class="options-subtitle">Style LoRA<span class="options-subtitle-what"> · changes the look<\/span><\/div>/.test(laidOut)
  && !laidOut.includes('Advanced') && laidOut.indexOf('opt_group_x') > laidOut.indexOf('data-below="opt_lora"'), 'the four first, in their order, then the turbo LoRA, then Use LoRA, then the rest; no Advanced');
assert(/\.options-sampling \{ display: grid; grid-template-columns: max-content minmax\(0, 13em\);/.test(html) && /\.options-sampling \.sampling-line \{ display: contents; \}/.test(html)
  && !laidOut.includes('options-box options-sampling'), 'under a heading, no box; names and settings in two lined-up columns');
assert(/\.options-sampling \.option-hint \{ grid-column: 1 \/ -1; margin: 0; contain: inline-size;/.test(html), 'a hint wraps inside the columns, not widening them');
assert(/<div class="options-lora options-speed"><div class="options-subtitle">Turbo LoRA<span class="options-subtitle-what"> · fewer steps, faster<\/span><\/div><label class="check">[^]*?name="opt_switch_lightning_lora"[^]*?data-below="opt_switch_lightning_lora"[^]*?<select name="opt_switch_lightning_lora_name"[^>]*><option value="t.safetensors" selected>t<\/option>[^]*?<input type="number" class="option-strength" name="opt_switch_lightning_lora_strength"/.test(laidOut)
  && laidOut.indexOf('options-speed') < laidOut.indexOf('data-below="opt_lora"'), 'the turbo LoRA first, with the same switch, file and strength as Use LoRA, and a word on what sets it apart');
assert(laidOut.includes('<div class="res-hint option-hint" hidden>How many times') && script.includes("const info = e.target.closest && e.target.closest('.option-info');"), 'each name drops its hint');
// The negative prompt goes to the bottom of the Prompt section, not the options; with only it, there are no options to show.
run(`syncOptions('testOptions', 'testOptionsBox', [{ id: 'negative', kind: 'text', label: 'Negative prompt', default: 'blurry' }], 'n')`);
assert(/<textarea id="opt_negative" name="opt_negative"[^>]*>blurry<\/textarea>/.test(els.testNegativeSlot.innerHTML) && !els.testNegativeSlot.hidden, 'the negative prompt is in the Prompt section');
assert(!els.testOptionsBox.innerHTML.includes('opt_negative') && els.testOptions.hidden, 'not in the options, which have nothing else to show');
run(`syncOptions('testOptions', 'testOptionsBox', [{ id: 'steps', kind: 'number', label: 'Steps', default: '8', min: 1, max: 150, step: 1 }], 'm')`);
assert(els.testNegativeSlot.innerHTML === '' && els.testNegativeSlot.hidden && !els.testOptions.hidden, 'a workflow without one leaves the place empty');
assert(/<div id="imageNegativeSlot" class="negative-slot"><\/div>\s*<\/details>\s*<details class="section" id="imageOptions"/.test(html)
  && /<div id="videoNegativeSlot" class="negative-slot"><\/div>\s*<\/details>\s*<details class="section" id="videoOptions"/.test(html)
  && /<div id="shortsNegativeSlot" class="negative-slot"><\/div>\s*<\/details>\s*<details class="section" id="shortsOptions"/.test(html), 'last in each Prompt section');
assert(script.includes("$(box).addEventListener('change', e => { followSwitch($(box), e.target); syncBelow($(box)); rememberOptions($(box)); });")
  && /\.pipeline-form \.option-below select \{ flex: 1 1 auto;/.test(html), 'switched on, it shows; the file takes the width, the strength at its right');
assert(/name="opt_group_cc" value="1" disabled/.test(optionsHtml) && optionsHtml.includes("Can't be changed"), "one that can't run is locked, saying why");
assert(/name="opt_lora_k_on" value="1">/.test(optionsHtml) && /name="opt_lora_k_strength"[^>]*value="1"/.test(optionsHtml), 'an unused LoRA offers its usual strength');
assert(/<label for="opt_steps">Steps<\/label>/.test(optionsHtml) && /name="opt_steps"[^>]*value="8"/.test(optionsHtml));
// Sampler and CFG with Steps: each on a line of its own, its name then its setting.
const stepsHtml = run(`(() => { const all = [{ id: 'steps', kind: 'number', label: 'Steps', default: '8', min: 1, max: 150, step: 1 },
  { id: 'sampler', kind: 'choice', label: 'Sampler', default: 'euler', choices: ['euler', 'dpmpp_2m'], parent: 'steps' },
  { id: 'cfg', kind: 'number', label: 'CFG', default: '1', min: 0, max: 30, step: 0.1, parent: 'steps' }];
  return imageOptionHtml(all[0], all); })()`);
assert(/<span class="option-line"><span class="option-sub">Sampler<\/span><select name="opt_sampler"[\s\S]*?<\/select><\/span><span class="option-line"><span class="option-sub">CFG<\/span><input[^>]*name="opt_cfg"[^>]*><\/span>/.test(stepsHtml)
  && /\.option-row \.option-line \{ flex: 1 0 100%;/.test(html), 'each setting with Steps on a line of its own');
assert(!run("remembered({ name: 'opt_steps', type: 'number' })"), 'each workflow starts as it was saved');
for (const size of ['1920x1080', '2560x1440', '3840x2160', '1272x2772']) assert(html.includes(`<option value="${size}">`), size);
els.imageAspect.value = '1920x1080';
els.imageMegapixels.value = 'image';
run('syncImageSize()');
assert.strictEqual(els.imagePixelSize.textContent, '1920×1080', 'the size it makes, beside the heading');
// The stepper scales a screen too: its shape, at the pixel count stepped to, sent as an aspect and megapixels.
els.imageMegapixels.value = '1';
run('syncImageSize()');
const [stepW, stepH] = els.imagePixelSize.textContent.split('×').map(Number);
assert(Math.abs(stepW * stepH - 1e6) < 0.06e6 && Math.abs(stepW / stepH - 16 / 9) < 0.03, `a screen, stepped: ${els.imagePixelSize.textContent}`);
assert.strictEqual(els.imageMegapixels.value, '1.0');
run('imageStep = null');
els.imageMegapixels.value = 'image';
assert(!html.includes('id="imageSizeHint"') && !/21:9/.test(html), 'no size hint, and no 21:9');
assert(/<select id="sizePreset">[\s\S]*?<optgroup label="Aspect ratio">[\s\S]*?<optgroup label="Landscape 16:9">/.test(html), 'video: aspect ratios, then its presets');
run("outputKind = 'image'; setPipeline('image', false)");
assert.strictEqual(run('folder'), 'video', "off Shorts, films are the made ones whichever side Generate is on");
assert.strictEqual(els.jumpResults.textContent, 'Output', 'the footer says Output, whatever it shows');
run("setPipeline('shorts', false)");
assert.strictEqual(els.jumpResults.textContent, 'Output', 'on Shorts too');
assert(/\.check \.hint \{ display: block;/.test(html), 'a checkbox hint sits under its label');
run("setPipeline('video', false)");
assert.strictEqual(run('outputKind'), 'image', "Generate's side does not change what Output shows");
run("setOutputKind('both')");
run("setPipeline('shorts', false)");
assert(/body\.on-image \{ --side: var\(--c-image\); \}/.test(html));

// A stopped run reads top to bottom in its own box: title, details, then the buttons.
run(`renderStopped([{ id: 'image_1', pipeline: 'image', label: 'Wardrobe', detail: '1 of 2 images · 1376x768', when: '02 Nov 23:46', clips: 1, estimate: 190 }])`);
const stoppedBox = els.stoppedRuns.innerHTML;
assert(stoppedBox.includes('class="stopped-run"'), 'in a box of its own');
assert(stoppedBox.indexOf('Wardrobe') < stoppedBox.indexOf('Image · 1 of 2 images') && stoppedBox.indexOf('Image · 1 of 2 images') < stoppedBox.indexOf('class="stopped-actions"'), 'in that order');
assert(stoppedBox.includes('<div class="hint">02 Nov 23:46</div>') && stoppedBox.indexOf('Image · 1 of 2 images') < stoppedBox.indexOf('02 Nov 23:46') && stoppedBox.indexOf('02 Nov 23:46') < stoppedBox.indexOf('class="stopped-actions"'), 'the date on its own line, under the details');
assert(stoppedBox.indexOf('class="stopped-actions"') < stoppedBox.indexOf('data-continue') && stoppedBox.indexOf('data-continue') < stoppedBox.indexOf('data-shots') && stoppedBox.indexOf('data-shots') < stoppedBox.indexOf('data-config') && stoppedBox.indexOf('data-config') < stoppedBox.indexOf('data-discard'), 'continue is left of the other actions');
assert(stoppedBox.includes(`data-shots="image_1" aria-label="Prompts" title="View prompts">${run('ICONS.enhanced')}</button>`), 'failed and stopped runs use the star for prompts');
assert(/class="icon-btn start-item continue-item" data-continue="image_1"/.test(stoppedBox) && stoppedBox.includes('aria-label="Continue"'), 'continuation has an accessible play icon');
assert(/\.queue \.stopped-actions \.continue-item \{[^}]*color: var\(--ok\)/.test(html) && /\.queue \.stopped-actions \.icon-btn:not\(\.continue-item\) \{ color: var\(--muted\)/.test(html), 'only continuations have a green play icon');
assert(/\.stopped-run \{[^}]*border: 1px solid/.test(html));
run('renderStopped([])');

// Each form starts with its preset, above the line its sections start with; the workflow opens Generation. No Check setup.
for (const form of ['formShorts', 'formVideo', 'formImage']) {
  const start = html.indexOf(`id="${form}"`), section = html.indexOf('<details class="section"', start);
  const top = html.indexOf('class="workflow-top preset-top"', start);
  assert(top > start && top < section, `${form}: Preset first`);
  const inside = html.slice(section, html.indexOf('</details>', section));
  assert(/<summary class="section-title">Generation<\/summary>\s*<div class="workflow-in"[^>]*>\s*<div class="workflow-head"><label for="\w+">Workflow<\/label><button type="button" class="use-default"/.test(inside), `${form}: Workflow at the top of Generation`);
}
assert(!html.includes('first-child > .section:first-child'), 'every form has the line above Generation');
assert(!html.includes('id="check"') && !script.includes('/check/'), 'no Check setup');

// A phone shows one section at a time, from the footer, and the bars over it ease in and out.
for (const page of ['status', 'generate', 'quota', 'output']) {
  assert(new RegExp(`data-page="${page}"`).test(status0() + html), page);
  assert(html.includes(`body[data-page="${page}"] .dashboard > [data-page="${page}"]`), `${page} shows alone`);
}
run("showPage('status')");
assert.strictEqual(context.document.body.dataset.page, 'status');
run("showPage('generate')");
assert.strictEqual(context.document.body.dataset.page, 'generate');
// The progress bars: in the header, left of its icons; a tap grows one down over the page.
assert(/<div class="top">\s*<div class="top-main" id="topMain">\s*<div class="head-strips" id="headStrips">\s*<div class="strip" id="runStrip"[\s\S]*?id="uploadStrip"/.test(html)
  && !/<div class="stick" id="stick">[\s\S]*?id="runStrip"[\s\S]*?<\/nav>/.test(html) && html.indexOf('id="runStrip"') < html.indexOf('id="stick"'), 'in the header, not the footer');
assert(/\.head-strips \{ position: absolute; top: 0; left: 0; right: 0; z-index: 30;/.test(html)
  && /\.head-strips\.opened \{ background: var\(--bg\); box-shadow:/.test(html) && !/\.head-strips \.strip\.open \{ background/.test(html),
  'floating, so it never moves the page; opened, no box of its own, the page behind it');
assert(/\.head-strips\.empty \{ opacity: 0; transform: translateY\(-6px\); visibility: hidden;/.test(html) && /\.head-strips \{[^}]*transition:[^}]*opacity \.25s ease, transform \.25s ease, visibility \.25s; \}/.test(html),
  'it eases in and out as the page changes, rather than popping');
assert(script.includes("document.addEventListener('click', e => { if (!(e.target.closest && e.target.closest('#headStrips'))) foldStrips(); });")
  && script.includes("window.addEventListener('scroll', foldStrips, { passive: true });"), 'opened, a tap elsewhere or a scroll folds it');
assert(/@keyframes page-in/.test(html) && /prefers-reduced-motion/.test(html), 'pages slide in, unless motion is turned down');

// Films.
run("folder = 'video'");
const film = { name: 'A_run_20261101_120000.mp4', run: 'run_20261101_120000', title: 'A <i>film</i>', created: '01/11 12:00', size_mb: 40, mtime: 1 };
context.film = film;
const card = run('filmHtml(film)');
assert(!card.includes('<video') && card.includes('loading="lazy"'), 'a page of films must not hold the browser\'s connections: a poster, playing only when asked');
assert(!card.includes('<i>film'), 'film titles are escaped');
assert(card.includes('data-shots="run_20261101_120000"') && !card.includes('data-up=') && !card.includes('data-download-film='), 'a film is downloaded from the preview, not uploaded');
assert(card.includes(`aria-label="Shots">${run('ICONS.enhanced')}</button>`), 'film Output prompts uses the star icon');
film.run = null;
const orphan = run('filmHtml(film)');
assert(!orphan.includes('data-shots') && !orphan.includes('poster='), 'a film whose run is gone has no shots to open');

// The list of runs waiting: a plan is rendered, a stopped run is continued.
run(`renderStopped([{ id: 'run_1', pipeline: 'video', label: 'A <b>plan', detail: 'Plan ready, 8 shots', clips: 0, estimate: 1860 }])`);
const box = els.stoppedRuns;
assert.strictEqual(box.hidden, false);
assert(box.innerHTML.includes('A &lt;b&gt;plan') && box.innerHTML.includes('~31 min'));
assert(box.innerHTML.includes('data-shots="run_1"') && box.innerHTML.includes('data-continue="run_1"') && box.innerHTML.includes('aria-label="Render"'));
const written = box.innerHTML;
box.innerHTML = 'untouched';
run(`renderStopped([{ id: 'run_1', pipeline: 'video', label: 'A <b>plan', detail: 'Plan ready, 8 shots', clips: 0, estimate: 1860 }])`);
assert.strictEqual(box.innerHTML, 'untouched', 'a poll must not replace buttons that have not changed');
assert(written.length > 0);
run(`renderStopped([{ id: 'run_1', pipeline: 'video', label: 'x', detail: 'y', clips: 2, estimate: 60 }])`);
assert(box.innerHTML.includes('aria-label="Continue"'));
run(`renderStopped([], [{ id: 7, pipeline: 'video', label: 'Continue', detail: '', resume: 'run_1', continuation: true }, { id: 8, pipeline: 'image', label: 'new', detail: '', continuation: false }, { id: 9, pipeline: 'image', label: 'upscale', detail: '', resume: 'image_1', continuation: false }])`);
assert(box.innerHTML.includes('data-shots="run_1"') && box.innerHTML.includes('data-edit="7"') && box.innerHTML.includes('data-start="7"'), 'a parked continuation exposes prompts and its other controls');
assert(box.innerHTML.indexOf('data-start="7"') < box.innerHTML.indexOf('data-shots="run_1"'), 'pending start is left of prompts');
assert(box.innerHTML.includes(`data-shots="run_1" aria-label="Prompts" title="View prompts">${run('ICONS.enhanced')}</button>`), 'pending prompts use the star');
assert(box.innerHTML.includes('class="icon-btn start-item continue-item" data-start="7"') && box.innerHTML.includes('class="icon-btn start-item" data-start="8"') && box.innerHTML.includes('class="icon-btn start-item" data-start="9"'), 'only the continued job is green');
assert(box.innerHTML.includes(`data-start="8" aria-label="Add to the queue" title="Add to the queue: it starts when the queue gets to it">${run('ICONS.queue')}</button>`), 'pending: the queue icon, which only queues');
assert(!box.innerHTML.includes('data-run-now'), 'with the queue running or busy, no play: it would only queue too');
run(`renderStopped([], [{ id: 8, pipeline: 'image', label: 'new', detail: '', continuation: false }], [], true)`);
assert(box.innerHTML.includes(`data-run-now="8" aria-label="Run this now"`) && box.innerHTML.indexOf('data-start="8"') < box.innerHTML.indexOf('data-run-now="8"'),
  'on hold and idle: a play to the right of the queue icon, to run it now');
run('renderStopped([])');
assert.strictEqual(box.hidden, true);
run(`renderStopped([{ id: 'run_failed', pipeline: 'video', label: 'Failed', detail: 'Stopped', clips: 0, estimate: 60, outcome: { outcome: 'failed', why: 'Error' } }])`);
assert(els.failedRuns.innerHTML.indexOf('data-continue="run_failed"') < els.failedRuns.innerHTML.indexOf('data-shots="run_failed"'), 'failed retry is left of prompts');
run(`renderStopped([], [], [{ job_id: 7, pipeline: 'image', label: 'No plan', outcome: 'failed', note: 'Failed to start' }])`);
assert(els.failedRuns.innerHTML.includes('data-job-id="7"') && els.failedRuns.innerHTML.includes('No saved run to retry'), 'failures without a saved run still appear under Failed');
assert(els.failedRuns.innerHTML.includes('data-dismiss-job="7"') && els.failedRuns.innerHTML.includes('unsaved-actions'), 'a failure without a saved run has a delete button');
run(`renderStopped([], [], [{ job_id: 8, pipeline: 'video', label: 'Kept', outcome: 'failed', note: 'ComfyUI stopped', recoverable: true }])`);
assert(els.failedRuns.innerHTML.includes('data-requeue-job="8"') && !els.failedRuns.innerHTML.includes('No saved run to retry'), 'a failure with kept settings can go back to Pending');
assert(els.failedRuns.innerHTML.includes('data-requeue-edit="1"') && els.failedRuns.innerHTML.includes('Change settings'), 'a failure with kept settings has the sliders button');
assert(els.failedRuns.innerHTML.includes('data-dismiss-job="8"'), 'a failure with kept settings can still be deleted');
// How a run or upload ended is said once, under Finished, newest first; the status itself goes back to Idle.
const finishedClasses = {};
els.finishedToggle.classList.toggle = (name, value) => { finishedClasses[name] = value; };
run(`renderUpload({ lines: [{ n: 1, t: '17:00', text: 'x' }], running: false, started_at: '17:00', elapsed: 1, returncode: 1, stopped: true, queue: { items: [], held: false, results: [] } })`);
assert.strictEqual(els.uploadBox.hidden, true, 'an upload that ended has nothing to show here');
run(`renderFinished([{ label: 'A <b>run', outcome: 'done', at: '17:05', pipeline: 'video' }, { label: 'B', outcome: 'failed', note: 'exit 1', at: '17:10', pipeline: 'image' }],
  [{ label: 'C', outcome: 'done', at: '17:20' }])`);
assert.strictEqual(els.finishedToggle.disabled, false);
assert.strictEqual(finishedClasses.empty, false, 'phone icon appears when results exist');
assert(els.finishedLabel.innerHTML.startsWith('Finished (3)') && els.finishedLabel.innerHTML.includes('1 failed'));
assert.strictEqual(els.finishedCount.textContent, '3');
assert.strictEqual(els.finishedToggle.title, 'Finished (3) · 1 failed');
const order = ['>C<', '>B (exit 1)<', '>A &lt;b&gt;run<'].map(text => els.finishedList.innerHTML.indexOf(text));
assert(order.every(i => i >= 0) && order[0] < order[1] && order[1] < order[2], 'newest first, escaped');
assert(/data-goto="video"/.test(els.finishedList.innerHTML) && /<span class="result-mark">✔<\/span><span class="result-type">Video<\/span><span class="result-label">A &lt;b&gt;run[^<]*<\/span><span class="when">17:05<\/span>/.test(els.finishedList.innerHTML), 'its type before its title, the time last');
assert(/class="result done" style="--side:var\(--c-video\)" data-goto="video"/.test(els.finishedList.innerHTML) && /class="result failed"/.test(els.finishedList.innerHTML), 'each outlined in the colour of the page that made it');
assert(/\.results \.result \{ display: flex; align-items: center;/.test(html) && /border: 1px solid var\(--side/.test(html) && /\.result \.when \{ margin-left: auto;/.test(html)
  && /\.result-label \{[^}]*-webkit-line-clamp: 2/.test(html), 'outlined, text left, the time quietly at the right');
assert(/id="skip"[^>]*>Cancel<\/button>/.test(html) && /id="stop"[^>]*>Stop<\/button>/.test(html) && /\.run-actions \{ display: flex; justify-content: center;/.test(html), 'Cancel and Stop, small and centred');
assert(/data-goto="shorts" data-tab="uploaded"[^>]*>[\s\S]*?<span class="result-type">Upload</.test(els.finishedList.innerHTML), 'an upload goes to what was uploaded');
// Kept over a restart: a quiet Clear at the end, and one from another day says which.
assert(!els.finishedList.innerHTML.includes('finished-clear') && els.finishedFoot.hidden === false, 'Clear is outside the list, shown while it has something');
assert(/<div class="finished-foot" id="finishedFoot" hidden><button type="button" class="finished-clear" id="finishedClear"[^>]*>Clear<\/button><\/div>/.test(html), 'a discreet Clear under the list');
assert(/if \(cleared\) \{\s*if \(panelShown && panelShown\.which === 'finished'\) closePanel\(\);\s*else if \(DESK\.matches && document\.body\.dataset\.runtab === 'finished'\) setRunTab\('queue'\);/.test(script), 'cleared, Finished closes');
assert(/\$\('finishedClear'\)\.addEventListener\('click'[\s\S]{0,160}secondTap\(button\)[\s\S]{0,900}fetch\('\/queue\/finished\/clear', \{ method: 'POST' \}\)/.test(html), 'Clear asks first, swipes them out, then empties it');
{ const d = run('clearDelays(6)'); assert(d[0] === 0 && d.every((v, i) => i < 2 || v - d[i - 1] < d[i - 1] - (d[i - 2] ?? 0)), 'from the top, each sooner after the last than the one before'); }
assert(/#finishedList \{ overflow-x: clip; \}/.test(html) && !/#finishedList \{ overflow-x: hidden/.test(html), 'the list scrolls with the box, not on its own');
// A small picture of what it made on the left, and a swipe to the right takes it off the list.
run(`imageSets = [{ id: 'image_1', images: [{ position: 2, version: 9 }] }];
  renderFinished([{ label: 'Set', outcome: 'done', at: '17:05', pipeline: 'image', run_id: 'image_1', job_id: 4 },
    { label: 'Film', outcome: 'done', at: '17:06', pipeline: 'video', run_id: 'run_1', film: 'f.mp4', job_id: 5 }],
    [{ label: 'Up', outcome: 'done', at: '17:07', job_id: 4 }], [{ label: 'Made', outcome: 'done', at: '17:08', pipeline: 'image', run_id: 'image_2', position: 2 }])`);
{
  const list = els.finishedList.innerHTML;
  assert(list.includes('<span class="result-thumb"><img loading="lazy" alt="" src="/image-runs/image_1/thumbnails/2?v=9" onerror="this.remove()"></span><span class="result-mark">'), 'an image set: its first picture');
  assert(list.includes('src="/runs/run_1/image"'), "a film: its run's start image");
  assert(/data-lane="upload" data-key="upload:4">\s*<span class="result-thumb"><\/span>/.test(list), 'an upload: an empty space, so the rows line up');
  assert(list.includes('data-lane="run" data-key="run:4"') && list.includes('data-key="made:image_2:2"'), 'a key per row, by lane, so an upload and a run with one number differ');
  run(`forgottenResults.add('run:5'); forgottenResults.add('made:image_2:2'); renderFinished([{ label: 'Film', outcome: 'done', at: '17:06', pipeline: 'video', run_id: 'run_1', job_id: 5 }], [], [{ label: 'Made', outcome: 'done', at: '17:08', pipeline: 'image', run_id: 'image_2', position: 2 }])`);
  assert(!els.finishedList.innerHTML.includes('data-key='), 'swiped away: not brought back by the next poll');
  run('forgottenResults.clear(); imageSets = []');
  run(`nsfwView = false; renderFinished([{ label: 'Hot', outcome: 'done', at: '17:06', pipeline: 'image', run_id: 'image_9', job_id: 9, nsfw: true }], [], [{ label: 'HotNow', outcome: 'done', at: '17:08', pipeline: 'image', run_id: 'image_10', position: 1, nsfw: true }])`);
  assert(!els.finishedList.innerHTML.includes('Hot'), 'Finished: NSFW not shown without the NSFW filter');
  run('nsfwView = true; renderFinished(...lastFinished)');
  assert(els.finishedList.innerHTML.includes('Hot') && els.finishedList.innerHTML.includes('HotNow'), 'Finished: NSFW shown under the NSFW filter');
  run("nsfwView = false");
}
assert(script.includes("fetch(`/queue/${encodeURIComponent(d.lane)}/finished/${encodeURIComponent(d.jobId)}/forget`, { method: 'POST' })")
  && /\.results \.result\.swiped \{[^}]*translateX\(110%\)/.test(html) && /\.results \.result\.collapsing \{[^}]*height: 0 !important/.test(html)
  && /\.results \.result \{[^}]*touch-action: pan-y;/.test(html), 'it slides out, its space closes, and the server forgets it; scrolling still works');
assert.strictEqual(run(`finishedWhen({ at: '17:05', t: Date.now() / 1000 })`), '17:05', 'today: the time alone');
assert(run(`finishedWhen({ at: '17:05', t: Date.now() / 1000 - 3 * 86400 })`).endsWith(' 17:05') && run(`finishedWhen({ at: '17:05', t: Date.now() / 1000 - 3 * 86400 })`) !== '17:05', 'another day: its date too');
// One tap takes you to that side's output.
run("goToOutput('image')");
assert.strictEqual(run('pipeline'), 'image');
assert.strictEqual(context.document.body.dataset.page, 'output');
run("setPipeline('shorts', false)");
// On phones Log is beside Settings, Quota is inside Settings, and Finished is beside the run controls.
assert(/<div class="status-toggles" id="statusToggles">[\s\S]*?id="queueToggle"[\s\S]*?id="logToggle"[\s\S]*?id="finishedToggle"[\s\S]*?id="quotaToggle"/.test(html), 'desktop tabs');
assert(/#logToggle \{ grid-column: 1;/.test(html) && /#finishedToggle \{ grid-column: 2;/.test(html));
for (const id of ['logToggle', 'finishedToggle', 'quotaToggle']) {
  assert(new RegExp(`id="${id}"[^>]*aria-label="[^"]+"`).test(html), `${id} has an accessible name`);
}
{
  const moved = [];
  for (const id of ['settingsHead', 'runActions', 'statusToggles']) context.document.getElementById(id).appendChild = el => moved.push(`${id}:${el.id}`);
  els.topIcons.insertBefore = (el, before) => moved.push(`topIcons:${el.id}:before:${before ? before.id : 'end'}`);
  context.document.getElementById('privateToggle').nextSibling = { id: 'settingsBtn' };
  wide.matches = false;
  run('placePanelControls()');
  assert.deepStrictEqual(moved.splice(0), ['topIcons:finishedToggle:before:settingsBtn', 'topIcons:logToggle:before:settingsBtn', 'settingsHead:quotaToggle'],
    'in the header: Finished right of the key, then the log, then the gear');
  assert(!els.runActions.hidden && els.skip.hidden && els.stop.hidden, 'idle: no run controls');
  assert(/\.top-icons \.panel-icon \{ width: auto; height: auto; padding: 0; gap: 3px; color: var\(--muted\); opacity: \.7;/.test(html)
    && /\.top-icons #finishedToggle\.empty \{ display: none; \}/.test(html), "the header's icons all one quiet grey; Finished only with something in it");
  run('lastStatus = { running: true }; placePanelControls()');
  assert(!els.skip.hidden && !els.stop.hidden, 'run controls appear during generation');
  moved.length = 0;
  wide.matches = true;
  run('lastStatus = null; placePanelControls()');
  assert.deepStrictEqual(moved, ['statusToggles:logToggle', 'statusToggles:finishedToggle', 'statusToggles:quotaToggle']);
  assert(els.runActions.hidden, 'desktop run controls remain hidden when idle');
  wide.matches = false;
  run('placePanelControls()');
}
assert(!html.includes('Expand to see the log'));
{
  const moved = [];
  context.document.getElementById('panelDialogBody').appendChild = el => moved.push(el.id);
  context.document.getElementById('quotaCard').parentNode = { insertBefore: el => moved.push('back:' + el.id) };
  run("openPanel('quota')");
  assert.deepStrictEqual(moved, ['quotaCard']);
  assert(els.panelDialog.open && els.panelDialogTitle.textContent === 'Quota today');
  run('closePanel()');
  assert.deepStrictEqual(moved, ['quotaCard', 'back:quotaCard'], 'and back where it was');
  assert.strictEqual(els.panelDialog.open, false);
  // Finished: its Clear goes to the box's own foot, above Close, outside what scrolls; then back under the list.
  moved.length = 0;
  const home = { insertBefore: (el, before) => moved.push(`back:${el.id}`) };
  context.document.getElementById('finishedList').parentNode = home;
  context.document.getElementById('finishedFoot').parentNode = home;
  els.panelDialog.insertBefore = (el, before) => moved.push(`dialog:${el.id}:before:${before.id}`);
  run("openPanel('finished')");
  assert.deepStrictEqual(moved, ['finishedList', 'dialog:finishedFoot:before:panelDialogClose']);
  run('closePanel()');
  assert.deepStrictEqual(moved.slice(2), ['back:finishedFoot', 'back:finishedList'], 'the foot back first, then the list in front of it');
  assert(/dialog\.panel-dialog > \.finished-foot \{ position: absolute; right: 14px; bottom: 12px;/.test(html)
    && /dialog\.panel-dialog > \.finished-foot \.finished-clear \{ padding: 6px 10px; font-size: \.82rem;[^}]*border: 1px solid transparent;/.test(html),
    "in the box's bottom-right corner, sized as Close so they share a line");
}
assert(/dialog\.panel-dialog::backdrop \{[^}]*backdrop-filter: blur\(6px\)/.test(html) && /\.panel-close \{ align-self: center;/.test(html), 'over a blurred page, with a close in the middle under it');
assert(/\.status-queue:has\(> :not\(\[hidden\]\)\) \{[^}]*background: var\(--bg\)/.test(html), 'the runs in a darker box');
// Status's parts grow in and close out (a copy closes, the part hidden at once); a new stage eases in; idle, the nudge
// comes in slowly after a second.
assert(script.includes("const SMOOTH_PARTS = ['currentWork', 'currentWorkSize', 'runProgress',") && script.includes("watcher.observe(el, { attributes: true, attributeFilter: ['hidden', 'class'] });")
  && script.includes("for (const id of ['stageDetail', 'comfyNow']) replay($(id), 'stage-in');"), 'smooth in and out, and from stage to stage');
{
  context.document.getElementById('smoothHost');
  const host = els.smoothHost, inserted = [];
  host.insertBefore = (el, before) => inserted.push(el);
  const copy = { attrs: { id: 'x' }, removeAttribute(n) { delete this.attrs[n]; }, setAttribute(n, v) { this.attrs[n] = v; }, querySelectorAll: () => [], style: {},
    offsetHeight: 40, animate(frames) { this.frames = frames; return {}; } };
  context.smoothCopy = copy;
  context.smoothEl = { parentNode: host };
  run('smoothOut(smoothEl, smoothCopy)');
  assert(inserted[0] === copy && !('id' in copy.attrs) && copy.attrs['aria-hidden'] === 'true' && copy.frames[0].height === '40px' && copy.frames[1].height === '0px',
    'hidden: a copy without ids closes from its height to nothing');
}
assert(/\.nudge \{[^}]*animation: nudge-in 1\.4s ease 1s both,/.test(html) && /@keyframes nudge-in \{ from \{ opacity: 0; transform: translateY\(6px\); \}/.test(html), 'the nudge: in slowly, after a second');
assert(/\.status-queue > \.queue:not\(\[hidden\]\) ~ \.queue:not\(\[hidden\]\) \{ margin-top: 10px; padding-top: 4px; border-top: 1px solid var\(--line\); \}/.test(html), 'a thin line between the queue, Pending and Failed');
assert(/\.status-queue:has\(> :not\(\[hidden\]\)\) \{ margin: 14px -10px 0; padding: 2px 12px 12px;/.test(html), 'wider, out into the card, with its own room inside');
run('renderFinished([], [])');
assert(els.finishedToggle.disabled === true && els.finishedLabel.innerHTML === 'Finished' && els.finishedCount.textContent === '', 'still there, greyed out, when nothing has finished');
assert.strictEqual(finishedClasses.empty, true, 'phone icon is hidden when there are no results');
assert(/\.run-actions \{ position: relative;[^}]*align-items: center/.test(html) && /\.run-actions:not\(:has\(#skip:not\(\[hidden\]\)\)\) \{ display: none; \}/.test(html), 'phone run actions: centred, and gone when idle');
assert(!script.includes("'Finished ✔'") && !script.includes('Upload finished') && !script.includes('Failed (exit'));

// The header: a short status on Run, and a bar under it per job.
const idle = { running: false, stopped: false, returncode: null, elapsed: 0, progress: {}, upload: { running: false, elapsed: 0 } };
context.idle = idle;
// The footer's Status is just that, with its dot: what is being made shows in Status and the bars.
assert(/<a href="#runCard" data-page="status" class="run">Status<\/a>/.test(html) && !html.includes('jumpDot'));
const rendering = { ...idle, running: true, elapsed: 400, progress: { stage: [2, 4, 'Clips'], detail: 'Clip 2 of 75: The harbour, 8s',
  eta: { total_left: 600, adjusted_total: 1000 } } };
context.rendering = rendering;
run('renderStrips(idle)');
assert(els.runStrip.hidden && els.uploadStrip.hidden, 'nothing going, no bars');
const barOf = id => { const bar = context.document.getElementById(id); bar.parentElement = element('bar'); return bar; };
for (const id of ['runStripBar', 'uploadStripBar', 'runProgressBar', 'uploadProgressBar']) barOf(id);
for (const id of ['runProgress', 'uploadProgress']) context.document.getElementById(id).getBoundingClientRect = () => ({ top: 5000, bottom: 5100 });
run('renderStrips(rendering)');
assert.strictEqual(els.runStrip.hidden, false, 'away from Status, the footer has the bar');
assert.strictEqual(els.runProgress.hidden, false, 'and Status has it in full');
assert.strictEqual(els.runProgressBar.style.width, '40%');
assert.strictEqual(els.runProgressText.textContent, '40%', 'how far along on the left, nothing else');
assert(/^~10 min left, done around /.test(els.runProgressRight.textContent), 'when it ends on the right');
assert.strictEqual(els.runStripText.textContent, 'Clips');
assert.strictEqual(els.runStripRight.textContent, '40% · ~10 min left');
assert.strictEqual(els.runStripPct.textContent, '40%', 'folded, only how far along');
assert(/\.head-strips \.strip \.strip-right \{ max-width: 0; opacity: 0; \}/.test(html) && /\.head-strips \.strip\.open \.strip-pct, \.strip-pct:empty \{ max-width: 0; opacity: 0; \}/.test(html)
  && /\.head-strips \.strip-more \{ display: grid; grid-template-rows: 0fr;/.test(html) && /\.head-strips \.strip\.open \.strip-more \{ grid-template-rows: 1fr;/.test(html)
  && /<div class="strip-more"><div class="strip-more-in">/.test(html)
  && /\.head-strips \.strip \.bar \{ height: 6px;/.test(html), 'the percentage folded, the whole line opened, each easing into the other; the details grow to their own height; a thicker bar');
assert(script.includes("box.classList.add('pinning');") && /\.head-strips\.pinning, \.head-strips\.pinning \* \{ transition: none !important; \}/.test(html)
  && script.includes('move.onfinish = move.oncancel = done;'), 'changing place, one animation moves it: its own transitions wait');
assert.strictEqual(els.runStripBar.style.width, '40%');
// A status, as statusHtml writes it: its first line, the count under it on the left, and the time on the right.
const lines = el => ({ first: (/class="status-first">([^<]*)</.exec(el.innerHTML) || [])[1] || '',
  count: (/class="status-count">([^<]*)</.exec(el.innerHTML) || [])[1] || '', time: (/class="time"[^>]*>([^<]*)</.exec(el.innerHTML) || [])[1] || '',
  twoLines: el.innerHTML.startsWith('<div class="status-first">') });
context.statusLinesOf = lines;
assert.strictEqual(els.runStripCount.textContent, 'Clip 2 of 75', 'opened: which clip, on the first line');
assert.strictEqual(els.runStripHint.textContent, 'Clips · The harbour, 8s', 'and what it is doing on the second, with when it ends');
context.titled = { ...rendering, pipeline: 'video', queue: { current: { label: '3 videos: Harbour at dusk', facts: { count: 3 } } }, progress: { ...rendering.progress, run: [2, 3] } };
run('renderStrips(titled)');
assert.strictEqual(els.runStripText.textContent, 'Video(3): Harbour at dusk', 'the title');
assert.strictEqual(els.runStripCount.textContent, 'Video 2 of 3 · Clip 2 of 75');
context.uploading = { ...idle, upload: { running: true, elapsed: 75, progress: { upload: [2, 3, 'A.mp4'] } } };
run('renderStrips(uploading)');
assert.strictEqual(els.uploadStripText.textContent, 'Uploading A.mp4');
assert.strictEqual(els.uploadStripCount.textContent, 'Video 2 of 3');
assert.strictEqual(els.uploadStripTotal.textContent, '1:15 so far', 'an upload: what it sends, which of how many and its time');
assert.strictEqual(lines(els.uploadProgressHint).first, 'Uploading - A.mp4');
assert.strictEqual(els.uploadStripBar.style.width, '33%');
assert.strictEqual(els.uploadProgressBar.style.width, '33%');
assert.strictEqual(lines(els.uploadProgressHint).first, 'Uploading - A.mp4');
assert.strictEqual(els.uploadProgressRight.textContent, '33%', 'the status line above it has the time so far');
assert.strictEqual(els.uploadProgress.hidden, false);

// Folded, a footer bar is one line: the bar, how far along and when it ends. The rest opens when tapped.
assert(/id="runStrip" role="button"[^>]*>\s*<div class="strip-line"><div class="bar"><div id="runStripBar"><\/div><\/div><span class="strip-pct" id="runStripPct"><\/span><span class="strip-right" id="runStripRight"><\/span><\/div>\s*<div class="strip-more"><div class="strip-more-in">\s*<div class="strip-head"><b id="runStripText"><\/b><span id="runStripCount"><\/span><\/div>\s*<div class="hint strip-sub"><span id="runStripHint"><\/span><span id="runStripTotal"><\/span><\/div>/.test(html), 'opened: two lines under the bar');
assert(/^Done around \d/.test(els.runStripTotal.textContent), 'opened, it says when the run ends');
const classes = () => { const on = new Set(); return { add: c => on.add(c), remove: c => on.delete(c), contains: c => on.has(c), toggle(c, yes) { if (yes) on.add(c); else on.delete(c); } }; };
els.runStrip.classList = classes();
const timers = [];
context.setTimeout = (fn, ms) => { timers.push([fn, ms]); return timers.length; };
context.document.body.dataset.page = 'generate';
for (const id of ['headStrips', 'topMain']) context.document.getElementById(id);
els.topMain.getBoundingClientRect = () => ({ left: 16, right: 330 });
const keptDocEl = context.document.documentElement;
context.document.documentElement = { ...keptDocEl, clientWidth: 400 };
run("tapStrip('run')");
context.document.documentElement = keptDocEl;
assert(els.runStrip.classList.contains('open'), 'a tap opens it');
assert(els.headStrips.style.left === '-16px' && els.headStrips.style.right === '-70px', "opened, the screen's full width, edge to edge over the icons");
assert(/body:not\(\.strips-out\) \.head-strips:not\(\.opened\) \{ left: 12\.5%; right: 12\.5%; \}/.test(html)
  && /\.head-strips\.opened \{ border-radius: 0; padding-left: 16px; padding-right: 16px; \}/.test(html), 'folded, a quarter shorter, in the middle; opened, square');
assert.strictEqual(timers[timers.length - 1][1], 5000);
timers[timers.length - 1][0]();
assert(!els.runStrip.classList.contains('open'), 'it folds again by itself after five seconds');
assert.strictEqual(context.document.body.dataset.page, 'generate');
run("tapStrip('run')");
run("tapStrip('run')");
assert.strictEqual(context.document.body.dataset.page, 'status', 'a tap while open goes to Status');
assert(!els.runStrip.classList.contains('open'));
context.setTimeout = () => 0;
assert(/\.go-bar button \{[^}]*padding: 8px 14px; font-size: \.85rem;/.test(html), 'the footer button is the smaller one');

// The log: stages are sections with their outcome on the heading, routine lines fold into one, and problems stay on show.
const logSample = [
  '▶ Stage 2/4: Stock footage',
  '🎥 Starting Double-Feature Video Download (Pexels)...',
  "   🔍 Searching Pexels for: 'lion'...",
  '   ✅ Scene 1 Ready (A + B).',
  '      ⚠️ Scene 2 Clip A missing. Using Clip B for both.',
  '   ✅ Scene 2 Ready (A + B).',
  "   🔍 Searching Pexels for: 'tiger'...",
  '   ❌ Scene 3 Completely Failed (No videos found).',
  '🎥 Assets Downloaded: {1: 2, 2: 2}',
  '▶ Stage 3/4: Avatar clips',
  '   🎬 Clip 1/2 · scene 1: 5s image-to-video',
  '      🌱 Seed 123',
  '🎛️ ComfyUI: 10 steps',
  '      ⏱️ Rendered in 42s',
  '      ✅ Saved avatar_scene_1.mp4',
  '   🎬 Clip 2/2 · scene 2: 5s image-to-video',
  '      🌱 Seed 456',
  '   ❌ Scene 2 avatar failed: boom',
  '   ❌ Scene 2 avatar clip not made; using stock footage.',
  '▶ Stage 4/4: Compose',
  '   ' + 'a very long prompt '.repeat(30),
].map((text, i) => ({ n: i + 1, t: `10:${String(Math.floor(i / 6)).padStart(2, '0')}:${String(i % 6 * 10).padStart(2, '0')}`, text, ...(text.startsWith('🎛️') ? { k: 'comfy' } : {}) }));
context.logSample = logSample;
run('var logSummary = logHtml(logSample, false)');
run('var logFull = logHtml(logSample, true)');
const summary = context.logSummary, full = context.logFull;
assert(summary.includes('▶ Stage 3/4 · Avatar clips · 1/2 clips · <span class="bad">1 failed</span>'), 'a stage says how its clips went');
assert(summary.includes('🎬 Clip 1/2 · Scene 1 · 5s · image-to-video · saved in 42s'), 'a clip is one line');
assert(summary.indexOf('Seed 123') > summary.indexOf('grp-body') && summary.indexOf('Saved avatar_scene_1') < summary.indexOf('Clip 2/2'), 'its seed and render details wait inside it');
assert(/class="ln [^"]*child"[^>]*><span class="t">[^<]*<\/span><span class="x">\s*✅ Saved avatar_scene_1/.test(summary), 'the saved file is a child of its clip');
assert(summary.includes('🎥 Stock footage: 2/3 scenes ready · scene 2 using fallback · scene 3 failed'), 'the stock footage is one line');
assert(summary.includes('⚠️ Scene 2: avatar failed · using stock footage'), 'what failed and what happened next is one line');
assert(summary.includes('Scene 2 Clip A missing') && summary.includes('Scene 3 Completely Failed'), 'warnings and failures stay on show');
assert(summary.includes('Show full prompt') && summary.includes('class="ln  long'), 'a long prompt is cut short, with a way to read it all');
assert(!full.includes('Show full prompt') && !full.includes('grp-body') && full.includes('Seed 123') && full.includes('avatar clip not made'), 'Detailed keeps every line as printed');
assert(/class="stage-sec open"[^>]*data-key="s10"/.test(summary) === false && /class="stage-sec"[^>]*data-key="s10"/.test(summary), 'a finished stage is closed');
assert(/class="stage-sec open"[^>]*data-key="s20"/.test(summary), 'the stage being run is open');
assert(!/class="stage-sec"/.test(full), 'Detailed opens every stage');
assert(/\.stage-sec:not\(\.open\) \.stage-body \.ln:not\(\.err\):not\(\.warn\) \{ display: none; \}/.test(html), 'a closed stage keeps its warnings and errors');
assert(html.includes('id="logSummary"') && html.includes('id="logDetailed"') && html.includes('id="logProblems"'), 'Summary, Detailed and Errors are all there');

// A log keeps where you are reading: the upload log only follows when it's at its end, and old lines going off the
// top don't move what you're looking at.
assert(!script.includes("logWriter($('uploadLog'), () => true)"), 'the upload log does not always jump to its end');
context.fakeLog = { rows: [], scrollTop: 0,
  get scrollHeight() { return this.rows.length * 10; }, get children() { return this.rows; },
  get firstElementChild() { const rows = this.rows; return rows.length ? { remove: () => rows.shift() } : null; },
  set innerHTML(text) { this.rows = text.match(/class="ln/g) || []; },
  insertAdjacentHTML(_, text) { this.rows.push(...(text.match(/class="ln/g) || [])); } };
context.lines = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => ({ n: a + i, t: '', text: 'x' }));
run('var writeFake = logWriter(fakeLog, () => false)');
run('writeFake(lines(1, 100))');
context.fakeLog.scrollTop = 800;
run('writeFake(lines(1, 100))');
assert.strictEqual(context.fakeLog.scrollTop, 800, 'nothing new, nothing moves');
run('writeFake(lines(51, 120))');
assert.strictEqual(context.fakeLog.rows.length, 70);
assert.strictEqual(context.fakeLog.scrollTop, 300, 'line 81 is still at the top of the view');
for (const id of ['runProgress', 'uploadProgress']) context.document.getElementById(id).getBoundingClientRect = () => ({ top: 0, bottom: 100 });
run('syncStrips()');
assert(els.runStrip.hidden && els.uploadStrip.hidden, "with Status's own bars in sight, these would only repeat them");
assert.deepStrictEqual([...html.matchAll(/<a href="#(\w+)"/g)].map(m => m[1]), ['runCard', 'optionsCard', 'videosCard'], 'Quota is in Status now');
assert(!html.includes('name="avatar_source"') && !html.includes('name="lang"'), 'Shorts always uses ComfyUI, and the voice says the language');

// Nothing a video does can hold up the status: no video loads until you press play.
assert(!/preload="(metadata|auto)"/.test(script) && !/preload="(metadata|auto)"/.test(html), 'videos must not hold the browser\'s connections');

// Shorts previews only its own videos; the made films are with the images, never Shorts'.
const made = name => ({ name, created: '01/11 12:00', size_mb: 1, mtime: 1 });
run(`lastVideos = ${JSON.stringify({ output: [made('a_short.mp4')], uploaded: [made('uploaded_short.mp4')], video: [made('a_film.mp4')] })}; outputKind = 'video'`);
run("setPipeline('video', false)");
assert(els.imageSets.innerHTML.includes('a_film.mp4') && !els.imageSets.innerHTML.includes('short.mp4') && !els.videos.innerHTML.includes('mp4'), 'Videos shows films only');
run("setPipeline('shorts', false)");
assert(els.videos.innerHTML.includes('a_short.mp4') && !els.videos.innerHTML.includes('a_film.mp4'), 'Shorts shows Shorts only');
assert(!els.videos.innerHTML.includes('uploaded_short.mp4'), 'and what is ready, until you open Uploaded');
run("setTab('uploaded')");
assert(els.videos.innerHTML.includes('uploaded_short.mp4') && !els.videos.innerHTML.includes('a_film.mp4'));
// Shorts have the same rows as films and image sets; a Short ready to go has an upload icon first.
run("setTab('output')");
assert(/<div class="image-set film" data-name="a_short\.mp4">[\s\S]*?class="icon-btn" data-up="a_short\.mp4"[^>]*aria-label="Upload to YouTube"><svg/.test(els.videos.innerHTML));
run("setTab('uploaded')");
assert(!els.videos.innerHTML.includes('data-up='), 'nothing to upload once it is up');
run("setPipeline('shorts', false)");

// Every link goes somewhere. The footer's order is its own: a desktop lights up by where the sections are.
const links = [...html.matchAll(/<a href="#(\w+)"/g)].map(m => m[1]);
for (const id of links) assert(ids.has(id), `#${id} is on the page`);
// Deleting takes two taps, on every image and video delete button.
for (const asked of ["confirm('Delete ' + d.del", "confirm('Delete this image?", "confirm('Delete this set?", 'confirm(`Delete image ${d.deleteImage}']) {
  assert(!script.includes(asked), `${asked} is a second tap now`);
}
context.tapped = { textContent: 'Delete', innerHTML: 'Delete', dataset: {}, classList: classes(), style: {}, getBoundingClientRect: () => ({ width: 72 }) };
assert.strictEqual(run('secondTap(tapped)'), false, 'the first tap only asks');
assert(context.tapped.classList.contains('armed') && context.tapped.textContent === 'Confirm');
assert.strictEqual(context.tapped.style.width, '72px', 'at the size it was');
assert(/button\.armed[^{]*\{[^}]*display: inline-flex; align-items: center; justify-content: center;/.test(html), 'its tick in the middle');
assert(/button\.armed[^{]*\{[^}]*flex: 0 0 auto;/.test(html), 'Confirm keeps the width it had, even in the viewer, whose buttons grow from nothing');
assert.strictEqual(run('secondTap(tapped)'), true, 'the second deletes');
assert.strictEqual(context.tapped.innerHTML, 'Delete');
run('secondTap(tapped)');
run('disarm(tapped)');
assert(!context.tapped.classList.contains('armed') && context.tapped.innerHTML === 'Delete', 'and left alone it goes back');
// An icon turns red with a tick instead: "Confirm" wouldn't fit, and it keeps its size too.
context.iconTapped = { innerHTML: '<svg>bin</svg>', dataset: {}, classList: classes(), style: {}, getBoundingClientRect: () => ({ width: 40 }) };
context.iconTapped.classList.add('icon-btn');
run('secondTap(iconTapped)');
assert(context.iconTapped.innerHTML.includes('m5 12 5 5 9-10') && context.iconTapped.style.width === '40px');
run('disarm(iconTapped)');
assert.strictEqual(context.iconTapped.innerHTML, '<svg>bin</svg>');
assert.strictEqual(context.tapped.style.width, '', 'and its own size again');

// The generation queue redraws together with Pending and Failed; upload departures keep their own animation.
const queueEl = { dataset: { title: 'Queue', lane: 'run' }, hidden: false, innerHTML: '', nodes: [],
  querySelector() { return null; },
  querySelectorAll(selector) { return selector.startsWith('.queue-request') || selector.startsWith('.armed') ? [] : this.nodes; } };
const queueTimers = [];
context.queueEl = queueEl;
context.setTimeout = (fn, ms) => { queueTimers.push([fn, ms]); return 1; };
context.twoQueued = { items: [{ id: 1, label: 'First', pipeline: 'video', detail: 'd' }, { id: 2, label: 'Second', pipeline: 'image', detail: 'd' }], held: false };
run('renderQueue(queueEl, twoQueued, 0)');
assert(queueEl.innerHTML.includes('data-id="1"') && queueEl.innerHTML.includes('data-id="2"'));
const first = { dataset: { id: '1' }, style: {}, offsetHeight: 40, classList: classes() };
queueEl.nodes = [first, { dataset: { id: '2' }, style: {}, offsetHeight: 40, classList: classes() }];
run('renderQueue(queueEl, twoQueued, 0, true)');
assert(!first.classList.contains('leaving'), 'generation departures are coordinated with the other sections');
assert(!queueEl.innerHTML.includes('data-id="1"') && queueEl.innerHTML.includes('data-id="2"'));
queueEl.dataset.lane = 'upload';
run('renderQueue(queueEl, twoQueued, 0, true)');
assert(first.classList.contains('leaving') && first.style.height === '40px', 'an upload still slides out of its queue');
queueEl.nodes = [];
queueTimers[queueTimers.length - 1][0]();
assert(!queueEl.innerHTML.includes('data-id="1"') && queueEl.innerHTML.includes('data-id="2"') && queueEl.innerHTML.includes('Queue (1)'));
context.setTimeout = () => 0;
run("showWork('Video: First')");
assert(els.currentWork.hidden === false && els.currentWork.textContent === 'Video: First');
assert(/nextUp \? workHeading\(ready\[0\], ready\[0\]\.pipeline\)/.test(script), 'between two jobs, the next ready one already shows');

// Moving between sections changes both heights at once, including a disappearing section.
{
  const saved = ['runQueue', 'stoppedRuns', 'failedRuns', 'queueBox'].map(id => [id, els[id]]);
  const animations = [], ghosts = [];
  function fakeSection(id) {
    const el = { id, hidden: true, dataset: { html: '' }, height: 0, rows: [], style: {},
      getClientRects() { return this.hidden ? [] : [1]; },
      getBoundingClientRect() { return { height: this.height }; },
      querySelectorAll() { return this.rows; },
      cloneNode() { return { ...fakeSection('copy'), hidden: false, height: this.height, removeAttribute() {}, setAttribute() {},
        remove() { this.removed = true; } }; },
      parentNode: { insertBefore(node) { ghosts.push(node); } },
      animate(frames) {
        const animation = { target: this, frames, cancel() { this.cancelled = true; if (this.oncancel) this.oncancel(); } };
        animations.push(animation);
        return animation;
      },
    };
    return el;
  }
  const queue = els.runQueue = fakeSection('runQueue'), pending = els.stoppedRuns = fakeSection('stoppedRuns');
  els.failedRuns = fakeSection('failedRuns');
  els.queueBox = { getClientRects: () => [1] };
  const row = top => ({ dataset: { motionKey: 'queue-1' }, getClientRects: () => [1],
    getBoundingClientRect: () => ({ top }), animate(frames) { animations.push({ target: this, frames }); } });
  context.testDraw = () => { queue.hidden = false; queue.height = 80; queue.dataset.html = 'one'; queue.rows = [row(100)]; };
  run('runSectionsDrawn = false; renderRunSections(testDraw)');
  assert.strictEqual(animations.length, 0, 'the first status draws without animation');
  context.testDraw = () => {
    queue.hidden = true; queue.dataset.html = ''; queue.rows = [];
    pending.hidden = false; pending.height = 120; pending.dataset.html = 'one'; pending.rows = [row(150)];
  };
  run('renderRunSections(testDraw)');
  assert.strictEqual(ghosts.length, 1, 'a disappearing section keeps its space while it closes');
  assert.deepStrictEqual(Array.from(animations[0].frames, frame => frame.height), ['80px', '0px']);
  assert.deepStrictEqual(Array.from(animations[1].frames, frame => frame.height), ['0px', '120px']);
  assert.strictEqual(animations[2].frames[0].opacity, 0, 'the moved run fades into its destination');
  run('renderRunSections(testDraw)');
  assert(!animations[0].cancelled && !animations[1].cancelled, 'an unchanged poll does not interrupt the transition');
  animations[0].onfinish();
  assert(ghosts[0].removed, 'the disappearing section is removed after its transition');
  context.window.matchMedia = () => ({ matches: true });
  context.testDraw = () => { pending.hidden = true; pending.dataset.html = ''; };
  const count = animations.length;
  run('renderRunSections(testDraw)');
  assert.strictEqual(animations.length, count, 'reduced motion draws immediately');
  context.window.matchMedia = () => wide;
  for (const [id, el] of saved) els[id] = el;
}
assert(/<button type="button" class="current-work" id="currentWork" aria-haspopup="dialog"/.test(html) && /<dialog id="runFacts" class="panel-dialog run-facts"/.test(html), 'the run title opens what it renders with');
assert(!html.includes('.current-work::after'), 'the clickable run title has no chevron after it');
{
  // The detailed prompt closes on a tap outside it, not on one inside.
  const dialog = els.promptDetail, savedClose = dialog.close, savedBox = dialog.getBoundingClientRect;
  let closed = 0;
  dialog.close = () => { closed++; };
  dialog.getBoundingClientRect = () => ({ left: 100, right: 500, top: 100, bottom: 700 });
  dialog.listeners.click({ target: dialog, clientX: 50, clientY: 300 });
  assert.strictEqual(closed, 1, 'a tap outside closes it');
  dialog.listeners.click({ target: dialog, clientX: 300, clientY: 300 });
  dialog.listeners.click({ target: els.promptDetailText, clientX: 300, clientY: 300 });
  assert.strictEqual(closed, 1, 'a tap inside does not');
  dialog.close = savedClose;
  dialog.getBoundingClientRect = savedBox;
}
assert(/<textarea id="promptEditorText"[^>]*><\/textarea>\s*<div class="prompt-progress-track"><div class="prompt-progress" id="promptEditorProgress" hidden><\/div><\/div>/.test(html)
  && /\.prompt-progress-track \{ position: absolute; inset: 1px; border-radius: 9px; overflow: clip;/.test(html), 'the prompt editor has a progress bar inside the top of its box, following its corners');
assert(/#promptEditorEnhance\.working svg \{ animation: prompt-writing-icon/.test(html) && /\$\('promptEditorEnhance'\)\.classList\.toggle\('working', busy\)/.test(html), 'the write button animates while the LLM writes');
assert(/button\.classList\.add\('working'\)/.test(html) && /button\.classList\.remove\('working'\)/.test(html), 'the form write button animates too');
assert(/rgba\(255, 255, 255, \.38\)/.test(html) && /#runCard \.step\.done \{ border-color: var\(--job, var\(--shared\)\); \}/.test(html), 'a brighter sweep, finished stages in full colour');
assert(/#comfyBar::after[^{]*\{[^}]*animation: bar-sheen 3\.6s/.test(html) && /\.step\.now::before \{[^}]*animation: step-sheen 3\.6s/.test(html), 'live bars and the stage under way have a slow, quiet sheen');
assert(!/\.disk \.bar > div::after/.test(html), 'the disk meter does not flash');
assert(/new ResizeObserver\(\(\) => \{[\s\S]{0,200}height < lastHeight && window\.scrollY > 0[\s\S]{0,300}window\.scrollTo\(0, y\)/.test(html), 'a page made shorter by a fold is repainted, not left black at the top');
// A fold that shrinks the page under a scrolled screen: scrolled to the new end by the page first, then let go, and the
// whole page drawn again, so nothing is left black at the top.
{
  const root = context.document.documentElement, body = context.document.body, win = context.window;
  const saved = { scrollY: win.scrollY, scrollTo: win.scrollTo, raf: context.requestAnimationFrame };
  const frames = [], scrolls = [], opacities = [];
  Object.defineProperty(root, 'scrollHeight', { configurable: true, get: () => Math.max(1500, parseFloat(body.style.minHeight) || 0) });
  body.style.minHeight = '';
  let opacity = '';
  Object.defineProperty(body.style, 'opacity', { configurable: true, get: () => opacity, set: v => { opacity = v; opacities.push(v); } });
  win.scrollY = 1600;
  win.scrollTo = (x, y) => { scrolls.push(y); win.scrollY = y; };
  context.requestAnimationFrame = fn => { frames.push(fn); return frames.length; };
  run('holdHeight()');
  assert.strictEqual(body.style.minHeight, '1500px', 'held at its height while it folds');
  body.style.minHeight = '2400px';  // as it was before the fold, scrolled to 1600
  run('releaseHeight()');
  assert.deepStrictEqual(scrolls, [700], 'scrolled to where the page now ends (1500 - 800) before it shrinks');
  assert.strictEqual(body.style.minHeight, '2400px', 'and only then let go, a frame later');
  while (frames.length) frames.shift()(0);
  assert.strictEqual(body.style.minHeight, '', 'let go');
  assert.deepStrictEqual(opacities, ['.999', ''], 'the page drawn again once, unseen');
  delete root.scrollHeight;
  Object.assign(win, { scrollY: saved.scrollY, scrollTo: saved.scrollTo });
  context.requestAnimationFrame = saved.raf;
}
assert(/workItem = running \? queue\.current : nextUp \? ready\[0\] : null;/.test(script) && script.includes("[['Workflow', facts.workflow], ['Resolution', facts.resolution], ...(facts.prompt ? [['Prompt', facts.prompt]] : [])]"));
assert.strictEqual(run("workHeading({label: '1 video: A film'}, 'video')"), 'Video: A film');
assert.strictEqual(run("workHeading({label: '1 video'}, 'video')"), 'Video:');
assert.strictEqual(run("workHeading({label: '5 images: Cats', facts: {count: 5}}, 'image')"), 'Image(5): Cats');
// Out of Private mode an NSFW job's title is a plain one, in the heading, the queues and what it makes now; in it, its own.
run('privateMode = false');
assert.strictEqual(run("workHeading({label: '5 images: Cats', facts: {count: 5}, nsfw: true}, 'image')"), 'Image(5): Untitled');
assert.strictEqual(run("workHeading({label: '5 images: Cats', facts: {count: 5}}, 'image')"), 'Image(5): Cats', 'not NSFW: its own title');
assert.strictEqual(run("nowDetail({progress: {detail: 'Image 2 of 5: A cat'}, queue: {current: {nsfw: true}}})"), 'Image 2 of 5');
run('privateMode = true');
assert.strictEqual(run("workHeading({label: '5 images: Cats', facts: {count: 5}, nsfw: true}, 'image')"), 'Image(5): Cats', 'Private mode on: its own title');
run('privateMode = false');
assert.strictEqual(run("sizeText('880x1920')"), '880 × 1920');
assert.strictEqual(run("workHeading({label: '1 image: Cat'}, 'image')"), 'Image: Cat');
assert.strictEqual(run("workHeading({label: '3 videos', facts: {count: 3}}, 'shorts')"), 'Shorts(3):');
assert.strictEqual(run("workHeading({label: 'Topic', facts: {count: 2}}, 'shorts')"), 'Shorts(2): Topic');
assert.strictEqual(run("workHeading({label: 'Upscale: Film'}, 'video')"), 'Video: Upscale: Film');
assert(/#stageDetail \{ text-align: left; \}/.test(html), 'the stage status lines up like every other');
assert(/id="viewerVariations"[^>]*><\/button>\s*<button type="button" class="icon-btn" id="viewerPrompts"[^>]*><\/button>/.test(html) && script.includes("openPromptDetail(detailed, data.brief, data.direct ? 'yours' : 'detailed');"), 'More like this beside Prompts, which opens its detailed prompt (yours, made from it word for word)');
for (const id of ['promptDetail', 'promptDetailTitle', 'promptDetailText', 'promptDetailYours', 'promptDetailCopy']) context.document.getElementById(id);
run("openPromptDetail('long version', 'my words', 'yours')");
assert(els.promptDetailTitle.textContent === 'Your prompt' && els.promptDetailText.textContent === 'my words' && els.promptDetailYours.title === 'Detailed prompt'
  && els.promptDetailYours.innerHTML === run('ICONS.enhanced'), 'an exact prompt opens on yours; the button below goes to the detailed one');
run("$('promptDetail').close()");
assert(/#currentWork\.arrive \{ animation: work-arrive/.test(html) && /\.queue-item\.leaving \{[^}]*animation: queue-leave/.test(html));
assert(/dialog\.viewer \.viewer-actions > \* \{ flex: 1 1 0; min-width: 0; max-width: 120px; height: 32px;/.test(html), 'Download, Delete and Close share the available space');
assert(/\.image-set-actions button\.armed, \.acts button\.armed[^{]*\{\s*background: var\(--err\) !important;/.test(html), 'Confirm is red in Output too');
context.withLoras = { ...context.oneImage0 = { id: 'image_2', label: 'L', total: 1, size: '1x1', when: 'now', images: [] }, loras: ['KNPV3_1 (0.8)', '<b>x'] };
const loraHtml = run('imageSetHtml(withLoras)');
assert(/<\/div><div class="meta loras"[^>]*>LoRA: KNPV3_1 \(0\.8\), &lt;b&gt;x<\/div>/.test(loraHtml), 'LoRAs on a line of their own, escaped');
assert(!run('imageSetHtml(oneImage0)').includes('LoRA'), 'none, no line');
assert(run("filmHtml({ name: 'f.mp4', created: 'now', size_mb: 1, loras: ['a'] })").includes('>LoRA: a</div>'), 'films too');
const filmWithH3 = run("filmHtml({ name: 'f.mp4', created: 'now', loras: ['a'], h3_mode: 'render', h3_creativity: 'balanced' })");
assert(filmWithH3.includes('LoRA: a</div><div class="meta">OpenH3-IR: Before each clip · Balanced</div>'), 'OpenH3 follows LoRA');
assert(!run("filmHtml({ name: 'f.mp4', created: 'now', h3_mode: 'off' })").includes('OpenH3-IR:'), 'disabled OpenH3 is omitted');
assert(run("filmHtml({ name: 'f.mp4', created: 'now', connection: 'chain', loras: ['a'] })").includes('<div class="meta">Clips: Continuous take</div><div class="meta loras"'), 'how clips connect, in shorthand, before LoRA');
assert(!run("filmHtml({ name: 'f.mp4', created: 'now' })").includes('Clips:'), 'unknown: no line');
run("viewerMetadata({ model: 'H3', connection: 'infinite', loras: ['x'] })");
assert.strictEqual(els.viewerMetaDetails.textContent, 'Clips: H3 Infinite continuation\nLoRA: x', 'and in the preview details');
run("viewerMetadata({ model: 'H3', llm: 'local', loras: ['x'], h3_mode: 'review', h3_creativity: 'bold' })");
els.viewerMeta.listeners.click();
assert.strictEqual(els.viewerMetaDetails.textContent, 'LoRA: x\nOpenH3-IR: Before review · Bold');
run("viewerMetadata({ model: 'other' })");
assert(els.viewerMetaDetails.hidden && els.viewerMeta.disabled, 'no metadata leaves nothing to expand');
// A run that stopped short says so under Stopped runs: a small word on its title's line, and why under a fold.
// Output is only what was made.
run(`renderStopped([{ id: 'run_1', pipeline: 'video', label: 'Jungle Flight', detail: 'Plan ready', when: 'now', estimate: 60, clips: 0,
  outcome: { outcome: 'not rendered', why: 'Asked to read\\n<b>x', at: 5 } }, { id: 'run_2', pipeline: 'video', label: 'Fine', detail: 'd', when: 'now', estimate: 1, clips: 0 }])`);
const stoppedHtml = els.stoppedRuns.innerHTML;
assert(/<div class="run-head"><div class="what"><span class="queue-title" data-title-key="run-run_1">Jungle Flight<\/span><\/div><span class="run-tag">not rendered<\/span><\/div>/.test(stoppedHtml), 'on the same line as its title');
assert(/<details class="why"><summary>Why<\/summary><div class="why-text">Asked to read\n&lt;b&gt;x<\/div><\/details>/.test(stoppedHtml), 'why, escaped, under a fold');
assert.strictEqual((stoppedHtml.match(/run-tag/g) || []).length, 1, 'nothing to say for one you stopped yourself');
assert(!script.includes('failed_films') && !script.includes('filmsHtml'), 'Output lists what was made, nothing else');

context.oneImage = { id: 'image_1', label: 'One', total: 1, size: '1024x1024', when: 'now', images: [{ position: 1, title: 'x', version: 1 }] };
assert(!run('imageSetHtml(oneImage)').includes('1 of 1'), 'one image on its own says no "1 of 1"');

// The footer: tapping the page you're on again offers the same page on the other sides.
context.document.body.dataset.page = 'generate';
run("setPipeline('shorts', false)");
const genLink = { dataset: { page: 'generate' }, offsetWidth: 80, offsetLeft: 100, offsetTop: 40, setAttribute() {}, removeAttribute() {} };
context.genLink = genLink;
run('openSideMenu(genLink)');
assert.strictEqual(els.sideMenu.hidden, false);
assert(els.sideMenu.innerHTML.includes('data-side="video"') && els.sideMenu.innerHTML.includes('data-side="image"') && !els.sideMenu.innerHTML.includes('data-side="shorts"'),
  'the other two sides, not the one you are on');
assert(/\.side-menu \{[^}]*animation: menu-in/.test(html) && /@keyframes menu-in \{ from \{ opacity: 0; transform: translateY\(8px\) scale\(\.94\)/.test(html), 'grows and fades in, upwards');
assert(/if \(page === document\.body\.dataset\.page && SIDE_PAGES\.includes\(page\)\)/.test(script) && /const SIDE_PAGES = \['status', 'generate', 'output'\]/.test(script), 'Status, Generate and Output; not Quota');
// Status, tapped again while on it, as the others: a menu of Finished, the log and Quota, each opening its box.
context.statusLink = { ...genLink, dataset: { page: 'status' } };
run('openSideMenu(statusLink)');
assert(['finished', 'log', 'quota'].every(p => els.sideMenu.innerHTML.includes(`data-panel="${p}"`)), 'Finished, Log, Quota');
assert(!script.includes('statusTappedAt') && script.includes("if (choice.dataset.panel) { openPanel(choice.dataset.panel); return; }"), 'no quick double tap; a choice opens its box');
// Output's: a shortcut to what it shows, in a word each; Shorts is Generate's side too.
context.outLink = { ...genLink, dataset: { page: 'output' } };
run("setPipeline('image', false); outputKind = 'both'; openSideMenu(outLink)");
{
  const menu = els.sideMenu.innerHTML;
  assert(['image', 'video', 'shorts'].every(k => menu.includes(`data-output-kind="${k}"`)) && !menu.includes('data-output-kind="both"') && !menu.includes('data-side='),
    'the other three, and no sides');
  assert(/>Images<\/button>/.test(menu) && /<\/span>Videos<\/button>/.test(menu) && /<\/span>Shorts<\/button>/.test(menu), 'one word each');
  assert(menu.indexOf('"shorts"') < menu.indexOf('"video"') && menu.indexOf('"video"') < menu.indexOf('"image"'), 'Shorts on top, then Videos, then Images');
}
run("outputKind = 'image'; openSideMenu(outLink)");
{
  const menu = els.sideMenu.innerHTML;
  assert(menu.indexOf('"video"') < menu.indexOf('"both"') && /data-output-kind="both"><span class="side-dot" style="background:var\(--shared\)"><\/span>Both<\/button>$/.test(menu),
    'Both at the bottom, violet');
  assert(/\.side-menu button\[data-output-kind="both"\] \{ border-color: var\(--shared\); \}/.test(html), 'with a violet border');
}
els.sideMenu.listeners.click({ target: { closest: () => ({ dataset: { outputKind: 'shorts' } }) } });
assert.strictEqual(run('pipeline'), 'shorts', 'Shorts in Output: Generate on Shorts too');
els.sideMenu.listeners.click({ target: { closest: () => ({ dataset: { outputKind: 'video' } }) } });
assert(run('pipeline') === 'image' && run('outputKind') === 'video', 'out of Shorts: back to the side it was on, showing Videos');
run("setPipeline('shorts', false)");
assert(/\.switch button \{[^}]*padding: 4px 12px; font-size: \.78rem;/.test(html), 'the side switch at the top is small now');

// Each workflow's options come back as you last set them, and another workflow's don't spill over.
{
  const stored = {};
  context.localStorage = { getItem: key => stored[key] || null, setItem: (key, value) => { stored[key] = value; } };
  const steps = { name: 'opt_steps', type: 'number', value: '20', disabled: false };
  const upscale = { name: 'opt_up', type: 'checkbox', checked: false, disabled: false };
  const hiddenZero = { name: 'opt_up', type: 'hidden', value: '0' };
  const box = { dataset: { workflow: 'imageOptions|krea.json' }, querySelectorAll: () => [steps, hiddenZero, upscale] };
  context.optBox = box;
  steps.value = '12';
  upscale.checked = true;
  run('rememberOptions(optBox)');
  assert.deepStrictEqual(JSON.parse(stored['comfyui-auto-gen.workflow-options'])['imageOptions|krea.json'], { opt_steps: '12', opt_up: true });
  steps.value = '20';
  upscale.checked = false;
  run('restoreOptions(optBox)');
  assert(steps.value === '12' && upscale.checked === true, 'as you left them');
  box.dataset.workflow = 'imageOptions|qwen.json';
  steps.value = '20';
  run('restoreOptions(optBox)');
  assert.strictEqual(steps.value, '20', "another workflow's settings are its own");
  context.localStorage = { getItem: () => null, setItem() {} };
}
assert(/syncOptions\('imageOptions', 'imageOptionsBox', options\.filter\(.*\), baseImageTakes\(\)\.name\)/.test(script), "Automatic's pick by its name");

// Why Generate was turned down shows beside the footer's button too, where it was pressed.
run("showFormError('This workflow makes images from text alone: leave the image out.')");
assert.strictEqual(els.goError.hidden, false);
assert.strictEqual(els.goError.textContent, els.formError.textContent);
run("showFormError('')");
assert(els.goError.hidden && els.formError.hidden);
assert(/<div class="go-error" id="goError" role="alert" hidden><\/div>/.test(html) && /\.go-error:not\(\[hidden\]\) \+ \.go-eta \{ display: none; \}/.test(html));
// From the tap until the panel has it: the buttons count up, and Status shows it on its way to the queue.
run('showSending(0.45)');
assert.strictEqual(els.goStick.textContent, 'Sending… 45%');
assert.strictEqual(els.queuePending.hidden, false);
assert.strictEqual(els.queuePendingBar.style.width, '45%');
run('showSending(1)');
assert(els.queuePendingText.textContent.endsWith('adding to the queue…'), 'sent, and being taken in');
assert(/if \(!submitting\) \$\('go'\)\.textContent/.test(script), 'a poll meanwhile leaves it saying so');
assert(/xhr\.upload\.onprogress/.test(script) && /<div class="queue-pending" id="queuePending" hidden>/.test(html));

// A film has the same again too, beside Download, while its run is kept.
// Films are laid out as image sets: the poster as the picture, which plays it, and the same icons, the same again second.
const filmRow = run("filmHtml({ name: 'f.mp4', created: 'now', size_mb: 1, run: 'run_1', model: 'wan', loras: ['example'], h3_mode: 'review', h3_creativity: 'bold' })");
assert(filmRow.includes('LoRA: example') && filmRow.includes('OpenH3'), 'film output shows inherited LoRAs and OpenH3 settings');
assert(run("filmHtml({ name: 'f.mp4', model: 'wan', resolution: '864x480', duration: 12, size_mb: 3 })").includes('wan · 864x480 · 0:12 · 3 MB'));
// Pills: what it was made with, on one line under the grey line of resolution, duration and size; those that
// tell it apart from its prompt's other runs first, marked. They replace the metadata lines.
{
  const pilled = run(`filmHtml({ name: 'f.mp4', model: 'wan', resolution: '864x480', duration: 12, size_mb: 3, loras: ['x'], connection: 'chain',
    pills: [{ text: 'Upscaled: <RTX>', kind: 'upscale', diff: true }, { text: 'wan', kind: 'workflow', diff: false }] })`);
  assert(pilled.includes('<div class="meta" title="f.mp4">864x480 · 0:12 · 3 MB</div>'), 'the grey line keeps resolution, duration and size, without the workflow');
  assert(pilled.includes('<div class="album-side"><div class="pills video" data-lines="3" role="button" tabindex="0" title="Tap to show all"><span class="pill diff">Upscaled: &lt;RTX&gt;</span><span class="pill workflow">wan</span></div><div class="image-set-actions">'),
    'pills, escaped, the differing one marked: beside the cover, above the buttons');
  assert(!pilled.includes('LoRA: x') && !pilled.includes('Clips:'), 'the old lines are gone where there are pills');
  const set = run(`imageSetHtml({ id: 'image_1', label: 'S', total: 2, resolutions: ['1024x1024'], size_bytes: 2097152, model: 'krea2', images: [{ position: 1, title: 'a', version: 1 }, { position: 2, title: 'b', version: 1 }],
    pills: [{ text: 'krea2', kind: 'workflow', diff: true }] })`);
  assert(set.includes('<div class="meta">1024x1024 · 2.0 MB · 2 images</div>') && /<div class="album-side">\s*<div class="pills image" data-lines="3"/.test(set), 'a set too: its grey line, its pills in green beside the cover');
  run(`viewerMetadata({ model: 'wan', llm: 'local', pills: [{ text: 'wan', kind: 'workflow', diff: true }] })`);
  assert(els.viewerMetaDetails.innerHTML === '<div class="pills video" data-lines="1" role="button" tabindex="0"><span class="pill workflow diff">wan</span></div>'
    && els.viewerMeta.hidden && !els.viewerMetaDetails.hidden, 'the preview shows its pills in place of the line that opened them: one line, the rest a tap away');
  els.viewerMetaDetails.innerHTML = 'kept';
  run(`viewerMetadata({ model: 'wan', llm: 'local', pills: [{ text: 'wan', kind: 'workflow', diff: true }] })`);
  assert.strictEqual(els.viewerMetaDetails.innerHTML, 'kept', 'the same pills at the next poll are left as they are, opened or not');
  run(`pictureMetadata({ model: 'k', pills: [{ text: 'k', kind: 'workflow', diff: false }, { text: 'Upscaled: x', kind: 'upscale', diff: false }] }, { upscaled: 'SeedVR2' })`);
  assert(els.viewerMetaDetails.innerHTML.includes('Upscaled: SeedVR2') && !els.viewerMetaDetails.innerHTML.includes('Upscaled: x'), "a picture's own upscale, not its set's");
  assert(/\.pills \{ position: relative; display: flex; flex-wrap: wrap; gap: 4px; max-height: 40px; overflow: hidden;/.test(html)
    && /\.pill\.workflow \{[^}]*var\(--pill, var\(--neutral\)\)/.test(html) && /\.viewer-meta-details \.pills \{ width: 96%; max-height: 18px; margin: 2px auto 0; justify-content: center; \}/.test(html) && /\.pills\.open \{ max-height: none;/.test(html)
    && /\.pills\.more:not\(\.open\)::after \{ content: attr\(data-more\);/.test(html), 'three lines in Output, one centred line in the preview; the workflow in its kind\'s colour; a count of the rest, open on a tap');
  assert(/<input type="checkbox" id="pinProgress"><span>Pin the progress bar<small>/.test(html) && script.includes("saveSettings({ pin_progress: $('pinProgress').checked })")
    && script.includes("$('pinProgress').checked = !!SETTINGS.pin_progress;"), 'Pin the progress bar: a setting, saved like the others');
  // Pinned and scrolled away: the bars leave the header for the top of the screen, easing there; not pinned, they stay.
  {
    const moved = [];
    for (const id of ['headStrips', 'topMain']) context.document.getElementById(id);
    context.window.scrollY = 200;
    run("SETTINGS.pin_progress = false; pinnedOut = false; syncPin()");
    assert(!run('pinnedOut'), 'not pinned: stays in the header');
    els.headStrips.getBoundingClientRect = () => (moved.push(1), { top: moved.length === 1 ? 30 : 0, left: 16, width: 200 });
    els.topMain.getBoundingClientRect = () => ({ top: 20, left: 16, width: 300 });
    els.headStrips.animate = frames => { context.pinFrames = frames; return {}; };
    run("SETTINGS.pin_progress = true; syncPin()");
    assert(run('pinnedOut') && run("JSON.stringify(pinFrames[0])") === '{"top":"30px","left":"16px","width":"200px"}', 'out, eased from where it was');
    context.window.scrollY = 0;
    run('syncPin()');
    assert(!run('pinnedOut'), 'back at the top: back in the header');
    run("SETTINGS.pin_progress = false; pinnedOut = false");
    assert(/body\.strips-out \.head-strips \{ position: fixed; top: 0; left: 0; right: 0;/.test(html) && /\.head-strips\.empty \{ opacity: 0;/.test(html), 'along the top, full width; nothing going, nothing there');
    assert(/<div class="options-col" id="optionsCard" data-page="generate">\s*<!--[^>]*-->\s*<div class="switch generate-switch" role="tablist" aria-label="Pipeline">/.test(html)
      && !/<div class="top">[\s\S]*?id="switchShorts"[\s\S]*?<div class="top-icons"/.test(html) && /@media \(min-width: 1000px\) \{ \.generate-switch \{ display: flex;/.test(html),
      'the side switch: not in the header; at the top of Generate on a desktop');
  }
  assert(script.includes("let page = 'status';\n  try { page = sessionStorage.getItem(PAGE_KEY) || page; } catch (e) {}"), 'a first visit opens on Status');
  assert(/<div class="status-loader" aria-hidden="true">(<i[^>]*><\/i>){5}<\/div>\s*<div class="status-main">/.test(html)
    && /<div class="nudge" id="nudge" role="button" tabindex="0"[^>]*hidden><\/div>\s*<div class="progress" id="runProgress"/.test(html)
    && /\.nudge \{[^}]*font-size: 1rem;[^}]*-webkit-background-clip: text;[^}]*animation: nudge-in 1\.4s ease 1s both, nudge-shine 6s ease-in-out 2\.4s infinite; \}/.test(html)
    && /body\.page-loading \.status-loader \{ display: flex; \}/.test(html), "Status's lines drawn faintly until the first answer; the nudge where the run's progress bar would be, a light passing over it");
  {
    context.document.getElementById('nudge');
    run("syncNudge(true)");
    const first = els.nudge.textContent;
    assert(!els.nudge.hidden && run('NUDGES.length') >= 80 && run('NUDGES').includes(first), 'idle: one of the nudges');
    run("syncNudge(true)");
    assert.strictEqual(els.nudge.textContent, first, 'the same while it stays idle');
    // Tapped: Image's Generate, its starred preset, the nudge as the prompt.
    run(`var keptNudge = { setPipeline, applyPreset, backToGenerate, presets };
      var nudgeCalls = []; setPipeline = side => nudgeCalls.push(['side', side]); applyPreset = (side, name) => nudgeCalls.push(['preset', side, name]);
      backToGenerate = side => nudgeCalls.push(['generate', side]); presets = { ...presets, image: [{ name: 'Plain' }, { name: 'Fav', default: true }] }`);
    run('makeFromNudge()');  // Nothing in it waits, so it is done when it returns
    assert.strictEqual(els.imagePrompt.value, first, 'the nudge is the prompt');
    assert.deepStrictEqual(JSON.parse(run('JSON.stringify(nudgeCalls)')).filter(c => c[0] !== 'side' || c[1] === 'image').slice(-2), [['preset', 'image', 'Fav'], ['generate', 'image']], 'with the starred preset, in Generate');
    run('({ setPipeline, applyPreset, backToGenerate, presets } = keptNudge)');
    els.imagePrompt.value = '';
    run("syncNudge(false)");
    assert(els.nudge.hidden && run('nudgeShown') === null, 'something going: none, and a new one next time');
  }
  assert(/<select id="titleSource" aria-labelledby="titlesTitle"><option value="off">[^<]*<\/option><option value="gemini">[^<]*<\/option><option value="gemini_sfw">[^<]*<\/option><option value="local">/.test(html)
    && script.includes("saveSettings({ title_source: $('titleSource').value })")
    && script.includes("$('titleSource').value = SETTINGS.title_source || 'off';"), 'Titles: Off, Gemini with the local model behind it, or the local model only, saved like the others');
  assert(/id="restartComfy"[\s\S]*?<button type="button" id="forceRestartComfy"[^>]*>[\s\S]*?<span>Force restart ComfyUI<\/span><\/button>\s*<a class="button" href="\/logout" id="logout"/.test(html) && !html.includes('settings-force')
    && /\.settings-actions button > span, \.settings-actions a\.button > span \{ position: absolute; width: 1px;/.test(html)
    && script.includes("body: JSON.stringify({ force: true })") && script.includes("confirmTap('forceRestartComfy', 'Force restart ComfyUI', 3)"),
    'Force restart ComfyUI sits left of Log out, in the row of icon-only buttons, asking for three taps, and restarts it whatever is running');
  {
    const taps = JSON.parse(run(`(() => {
      const span = { textContent: 'Force restart ComfyUI' }, shut = { textContent: 'Shut down' }, on = new Set();
      $('forceRestartComfy').querySelector = () => span; $('shutdown').querySelector = () => shut;
      $('forceRestartComfy').classList = { toggle: (name, force) => (force ? on.add(name) : on.delete(name)), add() {}, remove() {}, contains: name => on.has(name) };
      const out = [];
      for (let i = 0; i < 3; i++) { out.push(confirmTap('forceRestartComfy', 'Force restart ComfyUI', 3), span.textContent); }
      out.push(confirmTap('shutdown', 'Shut down'), confirmTap('shutdown', 'Shut down'));
      syncComfyButton({ online: true, listening: true, restarting: true });
      out.push($('forceRestartComfy').classList.contains('restarting'), span.textContent);
      syncComfyButton({ online: true, listening: true, restarting: false });
      out.push($('forceRestartComfy').classList.contains('restarting'));
      return JSON.stringify(out);
    })()`));
    assert.deepStrictEqual(taps, [false, 'Tap 2 more times', false, 'Tap once more', true, 'Force restart ComfyUI', false, true, true, 'Restarting ComfyUI…', false],
      `Force restart takes three taps, and is yellow while ComfyUI restarts: ${JSON.stringify(taps)}`);
  }
  assert(/\.viewer-meta \{ width: 100%;/.test(html), 'the preview line is 90% of the bar, not of its own content');
}
assert(filmRow.includes(run('ICONS.config')), 'film same-again uses the settings slider');
assert(/<div class="image-set film" data-name="f\.mp4">[\s\S]*?<div class="image-set-row album">\s*<a [^>]*class="album-cover film-cover" data-play-film="f\.mp4"/.test(filmRow));
assert(/data-again-film="run_1"[\s\S]*?data-shots="run_1"[\s\S]*?<\/button><button type="button" class="icon-btn del" data-del="f\.mp4"/.test(filmRow), 'the same again, shots, then delete');
assert(!run("filmHtml({ name: 'f.mp4', created: 'now', size_mb: 1 })").includes('data-again-film'), 'not once its run is gone');
// It plays in the viewer, and a swipe goes to the next film.
run(`lastVideos = { output: [], uploaded: [], video: [{ name: 'a.mp4', title: 'A' }, { name: 'b.mp4', title: 'B', model: 'wan', llm: 'local', loras: ['example'], h3_mode: 'review', h3_creativity: 'bold' }] }; folder = 'video'`);
run("openFilm('a.mp4')");
assert(els.viewerVideo.hidden === false && els.viewerImage.hidden === true && els.viewerVideo.src === '/videos/video/a.mp4');
assert.strictEqual(els.viewerTitle.textContent, 'A');
assert.strictEqual(els.viewerCount.textContent, '1 of 2');
assert.strictEqual(run('stepViewer(1)'), true);
assert.strictEqual(els.viewerVideo.src, '/videos/video/b.mp4');
assert.strictEqual(els.viewerMeta.textContent, 'wan · local');
assert(els.viewerMetaDetails.textContent.includes('LoRA: example') && els.viewerMetaDetails.textContent.includes('OpenH3'), 'film preview exposes inherited metadata');
assert.strictEqual(run('stepViewer(1)'), false, 'nothing after the last');
assert.strictEqual(run('stepSet(1)'), false, 'no next video at the end');
assert(/#viewerVideo \{[^}]*touch-action: none;/.test(html), 'video keeps swipe gestures from the browser');
run('zoom.scale = 2');
els.imageViewer.listeners.touchstart({ target: els.viewerVideo, touches: [{ clientX: 20, clientY: 20 }] });
els.imageViewer.listeners.touchend({ changedTouches: [{ clientX: 20, clientY: 100 }] });
assert.strictEqual(els.viewerVideo.src, '/videos/video/a.mp4', 'swipe down opens the previous video even after zooming an image');
els.imageViewer.listeners.touchstart({ target: els.viewerVideo, touches: [{ clientX: 20, clientY: 100 }] });
els.imageViewer.listeners.touchend({ changedTouches: [{ clientX: 20, clientY: 20 }] });
assert.strictEqual(els.viewerVideo.src, '/videos/video/b.mp4', 'swipe up opens the next video');
// Only a swipe on the media turns it; down on the buttons under it closes the preview.
els.imageViewer.listeners.touchstart({ target: { closest: () => null }, touches: [{ clientX: 20, clientY: 100 }] });
els.imageViewer.listeners.touchend({ changedTouches: [{ clientX: 20, clientY: 20 }] });
assert.strictEqual(els.viewerVideo.src, '/videos/video/b.mp4', 'a swipe beside the media turns nothing');
{
  let closed = 0;
  const keptClose = run('closeViewer');
  context.closeSpy = () => { closed++; };
  run('closeViewer = closeSpy');
  els.imageViewer.listeners.touchstart({ target: { closest: sel => (sel === '.viewer-bar' ? {} : null) }, touches: [{ clientX: 20, clientY: 20 }] });
  els.imageViewer.listeners.touchend({ changedTouches: [{ clientX: 22, clientY: 140 }] });
  assert.strictEqual(closed, 1, 'down on the buttons: the preview closes');
  els.imageViewer.listeners.touchstart({ target: { closest: sel => (sel === '.viewer-bar' ? {} : null) }, touches: [{ clientX: 20, clientY: 140 }] });
  els.imageViewer.listeners.touchend({ changedTouches: [{ clientX: 22, clientY: 20 }] });
  assert(closed === 1 && els.viewerVideo.src === '/videos/video/b.mp4', 'up on the buttons: nothing');
  context.keptClose = keptClose;
  run('closeViewer = keptClose');
}
run('resetZoom()');
run('closeViewer()');
run(`folder = 'output'`);

// The viewer never shows both: [hidden] wins over each one's own display.
assert(/#viewerImage\[hidden\], #viewerVideo\[hidden\] \{ display: none !important; \}/.test(html));
assert(/\.viewer-title \{[^}]*white-space: nowrap;[^}]*text-overflow: ellipsis/.test(html), 'a long title stays on one line, cut with an ellipsis');
const titleClasses = new Set();
els.viewerTitle.classList = { add: c => titleClasses.add(c), remove: c => titleClasses.delete(c), contains: c => titleClasses.has(c), toggle() {} };
run("setViewerTitle('A very long title')");
const titleToggle = (c, on) => (on ?? !titleClasses.has(c)) ? titleClasses.add(c) : titleClasses.delete(c);
els.viewerTitle.classList.toggle = titleToggle;
els.viewerTitle.listeners.click();
assert(els.viewerTitle.classList.contains('full'), 'a click shows the whole title');
els.viewerTitle.listeners.click();
assert(!els.viewerTitle.classList.contains('full'), 'and a second click cuts it again');
run("setViewerTitle('Next')");
assert(!els.viewerTitle.classList.contains('full'), 'the next title is cut again');
assert(/#viewerImage, #viewerVideo \{ max-height:/.test(html), 'a portrait film fits like a picture, its buttons in view');
// LoRAs on one line, cut short, the whole of it a tap away.
assert(/class="meta loras" role="button" tabindex="0" title="LoRA: a, b">LoRA: a, b<\/div>/.test(run("lorasLine(['a', 'b'])")));
assert(/\.meta\.loras \{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis;/.test(html) && /\.meta\.loras\.open \{ white-space: normal;/.test(html));

// Discarding a stopped run takes two taps, with no pop-up; deleting a whole set from Output has its own address.
assert(!script.includes('Discard this run? Its') && /else if \(d\.discard\) \{\s*\/\/[^\n]*\n\s*if \(!secondTap\(button\)\) return;/.test(script));
assert(script.includes("stopJob(`/image-runs/${encodeURIComponent(d.deleteSet)}/delete`)"));

// An exact size with nothing in its box falls back on 1:1 at one megapixel.
els.imageAspect.value = 'custom';
els.imageSize.value = '';
run('sizeFallback()');
assert(els.imageAspect.value === '1:1' && els.imageMegapixels.value === '1');
els.imageAspect.value = 'custom';
els.imageSize.value = '1920x1080';
run('sizeFallback()');
assert.strictEqual(els.imageAspect.value, 'custom', 'a size typed in stays');
els.imageAspect.value = 'image';


// The page doesn't zoom, but a picture in the viewer does: around a point, and back to its own size.
run('resetZoom()');
run('zoomAround(2.5, { x: 300, y: 200 }, 1, { x: 0, y: 0 }, { x: 200, y: 200 })');
assert.deepStrictEqual(JSON.parse(run('JSON.stringify(zoom)')), { scale: 2.5, x: -150, y: 0 }, 'the point tapped stays where it was');
run('zoomAround(9, { x: 0, y: 0 }, 1, { x: 0, y: 0 }, { x: 0, y: 0 })');
assert.strictEqual(run('zoom.scale'), 5, 'up to 5x');
run('resetZoom()');
assert.deepStrictEqual(JSON.parse(run('JSON.stringify(zoom)')), { scale: 1, x: 0, y: 0 });
run("viewing = { id: 'image_20261102_120000', position: 1 }; zoom.scale = 2");
els.imageViewer.listeners.touchstart({ touches: [{ clientX: 20, clientY: 20 }] });
assert.strictEqual(run('swipeFrom'), null, 'zoomed in, a finger moves the image rather than turning the page');
run('resetZoom(); viewing = null');

// Output: images and films in one list (Both), or either alone; NSFW only in the other view, and nothing of it elsewhere.
run(`lastVideos = { output: [], uploaded: [], video: [{ name: 'a.mp4', model: 'wan', mtime: 1 }, { name: 'b.mp4', model: 'ltx', mtime: 2 }, { name: 'c.mp4', model: 'wan', mtime: 3 }] }; folder = 'video'; pipeline = 'video'; outputKind = 'both'`);
assert.deepStrictEqual(JSON.parse(run('JSON.stringify(visibleFilms().map(v => v.name))')), ['a.mp4', 'b.mp4', 'c.mp4']);
run(`lastVideos.video.push({ name: 'private.mp4', model: 'wan', mtime: 4, nsfw: true });
  imageSets = [{ id: 'image_private', label: 'Private', model: 'test', size: '1x1', when: '', total: 1, nsfw: true,
    images: [{ position: 1, title: 'Private', version: 1 }] }, { id: 'image_plain', label: 'Plain', model: 'test', size: '1x1', when: '', total: 1, mtime: 2.5,
    images: [{ position: 1, title: 'Plain', version: 1 }] }];
  nsfwView = false; renderVideos(); renderImageSets()`);
assert.deepStrictEqual(JSON.parse(run('JSON.stringify(visibleFilms().map(v => v.name))')), ['a.mp4', 'b.mp4', 'c.mp4']);
assert.strictEqual(run('filtered(imageSets).length'), 1, 'tagged image batches are hidden normally');
{
  const both = els.imageSets.innerHTML, at = s => both.indexOf(s);
  assert(at('data-play-film="c.mp4"') >= 0 && at('data-play-film="c.mp4"') < at('image_plain') && at('image_plain') < at('data-play-film="b.mp4"'), 'Both: films and sets in one list, newest first');
  assert(!both.includes('private.mp4') && !both.includes('image_private'), 'nothing NSFW in Both');
  assert.strictEqual(els.videos.innerHTML, '', 'one list, not a films list above it');
}
run("setOutputKind('image')");
assert(els.imageSets.innerHTML.includes('image_plain') && !els.imageSets.innerHTML.includes('data-play-film'), 'Images: images only');
run("setOutputKind('video')");
assert(!els.imageSets.innerHTML.includes('image_plain') && els.imageSets.innerHTML.includes('data-play-film="a.mp4"'), 'Videos: films only');
run("setOutputKind('both'); setNsfwView(true)");
assert.deepStrictEqual(JSON.parse(run('JSON.stringify(visibleFilms().map(v => v.name))')), ['private.mp4']);
assert(els.imageSets.innerHTML.includes('data-nsfw-image="image_private"') && els.imageSets.innerHTML.includes('Remove NSFW tag'));
assert(els.imageSets.innerHTML.includes('data-nsfw-video="private.mp4"') && els.imageSets.innerHTML.includes('data-film-folder="video"'), 'films are listed with the image sets');
assert(!els.imageSets.innerHTML.includes('image_plain'), 'the other view: only what is tagged');
// Newest first, whatever kind: a set made between two films is listed between them.
run(`imageSets = [imageSets[0]]; lastVideos.video.push({ name: 'older.mp4', model: 'wan', mtime: 1, nsfw: true }); imageSets[0].mtime = 2; renderImageSets()`);
const nsfwOrder = ['data-nsfw-video="private.mp4"', 'data-nsfw-image="image_private"', 'data-nsfw-video="older.mp4"'].map(s => els.imageSets.innerHTML.indexOf(s));
assert(nsfwOrder.every(i => i >= 0) && nsfwOrder[0] < nsfwOrder[1] && nsfwOrder[1] < nsfwOrder[2], 'in the order things were made, not grouped by kind');
assert(/\$\('imageSets'\)\.addEventListener\('click', async e => \{\n  if \(e\.target\.closest && e\.target\.closest\('\.film'\)\) return onFilmClick\(e\);/.test(html), "a film's buttons work among the image sets");
run(`lastVideos.video = lastVideos.video.filter(v => v.name !== 'older.mp4')`);
// In the order they were made, by their run, even when a film's file is newer (stitched again later).
run(`lastVideos.video.push({ name: 'restitched.mp4', model: 'wan', mtime: 9e9, run: 'run_20261108_020000', nsfw: true });
  imageSets = [{ ...imageSets[0], id: 'image_20261108_010000' }, { ...imageSets[0], id: 'image_20261108_030000' }]; renderImageSets()`);
const madeOrder = ['data-nsfw-image="image_20261108_030000"', 'data-nsfw-video="restitched.mp4"', 'data-nsfw-image="image_20261108_010000"'].map(s => els.imageSets.innerHTML.indexOf(s));
assert(madeOrder.every(i => i >= 0) && madeOrder[0] < madeOrder[1] && madeOrder[1] < madeOrder[2], 'image, video, image made in that order stay in that order');
// Swiped up and down, the viewer goes through films and sets in that same order.
assert.deepStrictEqual(JSON.parse(run(`JSON.stringify(outputItems().map(item => item.film ? item.film.name : item.set.id))`)).filter(id => ['image_20261108_030000', 'restitched.mp4', 'image_20261108_010000'].includes(id)),
  ['image_20261108_030000', 'restitched.mp4', 'image_20261108_010000'], 'the viewer steps through them in the order shown');
assert(script.includes("next.film ? openFilm(next.film.name, 'video') : openViewer(next.set.id, next.set.images[0].position)"), 'from a set to a film and back');
// Shorts: its own, and never the other view.
run("setPipeline('shorts', false)");
assert(!run('nsfwView') && els.imageSets.innerHTML === '', 'Shorts: none of the made ones, and not the other view');
run(`lastVideos.video = lastVideos.video.filter(v => v.name !== 'restitched.mp4'); imageSets = [imageSets[0]]`);
run(`renderFinished([], [], []);`);
assert.strictEqual(els.finishedList.innerHTML, '', 'an open Finished list is cleared when nothing remains');
run('imageSets = []');
run(`nsfwView = false; folder = 'output'; pipeline = 'shorts'`);
// The footer's bar says how many more are waiting.
assert(/right: left \+ \(runsQueued \? ` · \+\$\{runsQueued\} queued` : ''\)/.test(script));
// The viewer: more like this one, and upscale it, for an image only.
assert(/<div class="viewer-tools" id="viewerTools">/.test(html));
assert.strictEqual(run('VARIATIONS'), 5, 'selected-image variations default to five');
assert(/if \(shot\) Object\.assign\(s, \{ prompt: shot\.prompt, direct: true, count: VARIATIONS \}\);/.test(script), 'its own prompt, word for word, on new seeds');

// Presets: the picker where the workflow was, the workflow at the top of Generation; "Save as preset" only while what's set isn't one.
assert(/<div class="workflow-top preset-top">\s*<div class="preset-head"><label for="imagePreset">Preset<\/label><span class="preset-head-actions"><button type="button" class="preset-default" data-preset-default="image" aria-pressed="false" hidden><svg[^>]*><path[^>]*\/><\/svg><\/button><button type="button" class="preset-save" data-preset-save="image" hidden>Save as preset<\/button><\/span><\/div>/.test(html));
assert(/<summary class="section-title">Generation<\/summary>\s*<div class="workflow-in">\s*<div class="workflow-head"><label for="imageWorkflow">Workflow<\/label><button type="button" class="use-default" data-defaults="imageOptionsBox" hidden[^>]*>Use default<\/button><\/div>/.test(html), 'the workflow at the top of Generation, Use default at its right');
assert(['shortsOptionsBox', 'videoOptionsBox'].every(box => html.includes(`data-defaults="${box}"`)), 'each side has one');
// Use default: each setting back to how the workflow is saved, and what was remembered for it forgotten.
{
  const field = (name, props) => ({ name, type: props.type || 'number', ...props });
  const fields = { 'opt_steps': field('opt_steps', { value: '30' }), 'opt_lora': field('opt_lora', { type: 'checkbox', checked: true }),
    'opt_lora_k_on': field('opt_lora_k_on', { type: 'checkbox', checked: false }), 'opt_lora_k_strength': field('opt_lora_k_strength', { value: '1' }) };
  context.resetBox = { dataset: { workflow: 'imageOptions|w.json' }, querySelectorAll: () => [],
    querySelector: selector => fields[(/name="([^"]+)"/.exec(selector) || [])[1]] || null,
    optionList: [{ id: 'steps', kind: 'number', default: '8' }, { id: 'lora', kind: 'switch', default: '0' },
      { id: 'lora_k', kind: 'strength', default: '0.8', usual: '1' }] };
  const keptStorage = context.localStorage, store = {};
  context.localStorage = { getItem: key => store[key] ?? null, setItem: (key, value) => { store[key] = String(value); } };
  run(`localStorage.setItem(OPTIONS_KEY, JSON.stringify({ 'imageOptions|w.json': { opt_steps: '30' }, other: { a: 1 } })); useDefaultOptions(resetBox)`);
  assert.deepStrictEqual([fields.opt_steps.value, fields.opt_lora.checked, fields.opt_lora_k_on.checked, fields.opt_lora_k_strength.value], ['8', false, true, '0.8'], 'as saved');
  assert.deepStrictEqual(Object.keys(run('savedOptions()')), ['other'], 'its remembered settings forgotten, no other workflow\'s');
  context.localStorage = keptStorage;
}
assert(run("samePreset({ a: '1', b: true }, { b: true, a: '1' })") === true && run("samePreset({ a: '1' }, { a: '2' })") === false);
assert(run("samePreset({ a: '1' }, { a: '1', transparent: false })") === true, 'a field added since a preset was saved does not unmatch it');
assert(/presetPicked\[side\] = \{ name, values: presetValues\(side\) \};\s*syncPresets\(side\);\s*\}/.test(script), 'the preset picked stays in the box, even where it could not set a field');

// Inpaint: the whole screen, its title quiet at the top, the colour prompts in a box of their own, Close and Save at the bottom.
assert(/id="paintDialogTitle">Inpaint<\/div>/.test(html) && !html.includes('One colour is one change'));
assert(/id="paintPrompts" class="panel-dialog"[\s\S]*?id="paintAreaList"/.test(html), 'the colour prompts open over a blurred painting');
assert(/id="paintCancel">Close<\/button>\s*<button type="button" class="panel-close paint-save" id="paintDone">Save<\/button>\s*<\/div>\s*<\/dialog>/.test(html));
assert(/const PRESET_SKIP = \['prompt', 'narration', 'seed', 'topic', 'output', 'review'\];/.test(script), 'what each run is about stays out of a preset');

// Try one first; add to pending or the top of the queue; no note when something ends.
assert((html.match(/<input type="checkbox" name="try_first" id="previewRun">/g) || []).length === 1, 'one Preview run, in Other, for whichever form it is in');
assert(/<button type="button" class="start-later" id="goLater"[^>]*>Add to pending<\/button>/.test(html) && !html.includes('type="time"'), 'Add to pending: a quiet button, no clock');
assert(/<button type="button" class="start-later" id="goTop"[^>]*>Add to top of queue<\/button>/.test(html) && script.includes("form.append('queue_top', '1')"), 'Add to top of queue: a quiet button that puts it first');
assert(!html.includes('id="toast"') && !script.includes('announceResults'), 'nothing pops up when something ends: Finished has it');
assert(script.includes('} else if (d.runNow) {') && script.includes('fetch(`/queue/run/run-now/${d.runNow}`'), 'its play runs it now');
assert(/<button type="button" class="start-later" id="cancelQueueEdit"[^>]*>Cancel editing<\/button>/.test(html) && /#cancelQueueEdit \{ display: block; margin: 6px auto 0; \}/.test(html), 'Cancel editing sits centred under the button');

// A batch's details start with the time it was made (the day too, once it isn't today); its workflow pill is in its kind's colour; the footer says Output.
assert.strictEqual(run("madeOn(madeAt('image_20261108_043935'))"), '8 Nov 04:39');
assert.strictEqual(run("clock24(new Date(2026, 10, 8, 0, 5))"), '00:05', 'a 24-hour clock, whatever the locale');
assert.strictEqual(run("clock24(new Date(2026, 10, 8, 15, 30))"), '15:30');
assert(/class="guide-link" id="connectGuideLink" data-guide="clip_connection"/.test(html) && /\.guide-link \{[^}]*margin: 5px auto 0[^}]*text-align: center/.test(html), 'the guide links are centred, and How clips connect has one');
assert.strictEqual(run("madeOn(Date.now() / 1000 - 5).length"), 5, 'today: the time alone, hh:mm');
assert(run("imageSetHtml({ id: 'image_20261108_043935', label: 'L', model: 'krea', images: [] })").includes('<div class="meta">8 Nov 04:39'), 'the time first');
assert(/\.pill\.workflow \{ border-color: color-mix\(in srgb, var\(--pill, var\(--neutral\)\)/.test(html) && /\.pills\.video \{ --pill: var\(--c-video\); \}/.test(html), 'the workflow pill by kind');
assert(/id="jumpResults">Output<\/a>/.test(html), 'Output in the footer; Status and Output in violet');
assert(/\.image-set-heading \.nsfw-button \{[^}]*height: 24px; padding: 0; margin: 0 0 -8px;/.test(html), 'the details just under the title');
assert(/classList\.toggle\('restarting', \(comfyOff && !!c\.starting\) \|\| !!c\.restarting\)/.test(script) && /button\.classList\.add\('restarting'\);/.test(script), 'Starting or restarting ComfyUI in yellow, as Restart panel');
assert(/\.output-filter-line \{ position: relative; display: flex; justify-content: center;/.test(html) && /\.view-toggle \{ position: absolute; right: 0;/.test(html), 'the kinds centred, the other view at the right');

assert(/dialog\.viewer::backdrop \{ background: rgba\(0, 0, 0, \.55\);[^}]*backdrop-filter: blur\(6px\)/.test(html), 'the page behind the preview, as behind Quota');

assert(/dialog\.viewer\[open\] \{ display: grid;[^}]*padding: 10px; background: var\(--panel\); border: 1px solid var\(--line\); border-radius: 14px;/.test(html)
  && /dialog\.viewer\[open\] #viewerImage, dialog\.viewer\[open\] #viewerVideo \{ width: 100%;[^}]*object-fit: contain; border-radius: 8px;/.test(html), 'the whole preview in one rounded card');

assert(/\.pipeline-form \.row > div \{ display: flex; flex-direction: column; justify-content: flex-end; \}/.test(html), 'fields side by side line up by their boxes');

assert(/\.stick \{[^}]*transform: translateZ\(0\); will-change: transform;/.test(html), 'the footer on a layer of its own, never half drawn');

// One part of the update failing doesn't stop the rest: the queue updates whatever else throws.
assert(/safely\(\(\) => renderQueue\(\$\('runQueue'\)/.test(script) && /safely\(\(\) => renderPlan\(\)\)/.test(script));
assert(run("(() => { let after = false; safely(() => { throw new Error('x'); }); safely(() => { after = true; }); return after; })()"), 'the next part still runs');
assert(/data-title="Queue"/.test(html) && !script.includes('Now: ${esc(q.current.label)}'), 'called Queue, with no Now line');

assert(html.indexOf('id="statusText"') < html.indexOf('id="currentWork"') && html.indexOf('id="gpuLine"') < html.indexOf('id="currentWork"'), 'running and the GPU above the title');

// Up and down in the viewer: the next or the previous set, from its first picture; none past the ends.
run(`imageSets = [{ id: 'image_a', images: [{ position: 1, title: 'A1', version: 1 }, { position: 2, title: 'A2', version: 1 }] },
  { id: 'image_b', images: [{ position: 3, title: 'B3', version: 1 }] }]; nsfwView = false`);
run("openViewer('image_a', 2)");
assert.strictEqual(run('stepSet(1)'), true);
assert.deepStrictEqual(JSON.parse(run('JSON.stringify(viewing)')), { id: 'image_b', position: 3 }, 'the next set, from its first picture');
assert.strictEqual(run('stepSet(1)'), false, 'nothing after the last');
assert.strictEqual(run('stepSet(-1)'), true);
assert.strictEqual(run('viewing.id'), 'image_a');
run('closeViewer()');
run('imageSets = []');

assert(/<div class="estimate-line"><span id="estimateTotal"><\/span><span id="estimateDetail"><\/span><\/div>/.test(html)
  && script.includes('`Estimate: <b>${fmtEta(plan.total)}</b>`') && !script.includes('Estimated time:'), 'the estimate on one quiet line');

assert(!html.includes('own switches, as it was saved') && !html.includes('Lower renders faster') && !html.includes('Stops after the prompts are written')
  && !html.includes('makes the same set again') && (html.match(/<span>Preview run/g) || []).length === 1, 'fewer hints; Try one first is Preview run');

assert(/addEventListener\(kind, e => \{ if \(e\.target !== \$\(`\$\{side\}Preset`\)\) syncPresets\(side\); \}\)/.test(script), 'picking a preset is not undone by its own input event');

assert(!/\.stick \{[^}]*contain: paint/.test(html), 'nothing clips the menu that grows up out of the footer');

// Prompt settings under their own heading, right below Generation; Shorts' voice with its avatar; no Advanced.
for (const [form, generation, prompt] of [['formImage', 'imageGeneration', 'imagePromptSection'], ['formVideo', 'videoGeneration', 'videoPromptSection'], ['formShorts', 'formTopic', 'shortsPrompt']]) {
  const g = html.indexOf(`id="${generation}"`), p = html.lastIndexOf('<details', html.indexOf(`id="${prompt}"`));
  assert(g > 0 && p > g && html.slice(html.indexOf('</details>', g), p).replace(/<\/details>|\s/g, '') === '', `${form}: Prompt right below Generation`);
}
assert(/id="imagePromptSection">[\s\S]*?id="imagePromptMode"[\s\S]*?id="imageLlm"[\s\S]*?id="clearImagePrompt"[\s\S]*?id="writeImagePrompt"[\s\S]*?id="imagePrompt"/.test(html));
assert(/id="videoPromptSection">[\s\S]*?id="videoPromptMode"[\s\S]*?id="llm"[\s\S]*?id="clearVideoPrompt"[\s\S]*?id="writeVideoPrompt"[\s\S]*?id="prompt"/.test(html));
assert(/<summary class="section-title">Avatar<\/summary>\s*<label for="voice">Narrator<\/label>/.test(html) && !html.includes('id="formVoice"') && !html.includes('id="formAdvanced"') && !html.includes('name="fail_fast"'));
// Video's clip length: a range within the model's; at its full span nothing is chosen.
assert(/<div class="range" id="videoClipRange">/.test(html) && /<input id="videoClipSeconds" name="clip_seconds" hidden>/.test(html));
run(`workflowClips = { 'h3.json': [5, 15, 12] }`);
els.videoWorkflow.value = 'h3.json';
els.videoClipSeconds.value = '';
assert.deepStrictEqual(JSON.parse(run('JSON.stringify(videoClips())')), [5, 15, 12], "the model's own, nothing chosen");
els.videoClipSeconds.value = '6-9';
assert.deepStrictEqual(JSON.parse(run('JSON.stringify(videoClips())')), [6, 9, 8], 'within what was chosen, its middle the usual');
els.videoClipSeconds.value = '2-30';
assert.deepStrictEqual(JSON.parse(run('JSON.stringify(videoClips())')), [5, 15, 10], 'held to what the model makes');
els.videoClipSeconds.value = '';
els.videoWorkflow.value = '';
{
  const box = els.videoClipRange, originalInputs = box.querySelectorAll, originalPart = box.querySelector;
  const low = element('fixed-low'), high = element('fixed-high'), fill = { style: {} };
  low.setAttribute = (name, value) => { low[name] = value; };
  box.querySelectorAll = () => [low, high];
  box.querySelector = () => fill;
  els.videoClipFixedButton.setAttribute = (name, value) => { els.videoClipFixedButton[name] = value; };
  els.videoClipFixed.checked = true;
  els.videoClipSeconds.value = '8-8';
  run('syncVideoClips()');
  assert(high.hidden && high.disabled && low.value == 8);
  assert.strictEqual(els.videoClipFixedButton['aria-pressed'], 'true');
  assert.strictEqual(els.videoClipText.textContent, '8s');
  low.value = '9'; context.movedClip = low; run('syncVideoClips(movedClip)');
  assert.strictEqual(els.videoClipSeconds.value, '9-9');
  els.videoClipFixed.checked = false; els.videoClipSeconds.value = '';
  run('syncVideoClips()');
  assert(!high.hidden && !high.disabled && els.videoClipSeconds.value === '', 'turning fixed off restores the range');
  assert.strictEqual(els.videoClipFixedButton['aria-pressed'], 'false');
  context.testSyncVideoForm = () => run('syncVideoClips()');
  run('var savedSyncVideoForm = syncVideoForm; syncVideoForm = testSyncVideoForm');
  els.videoClipFixedButton.listeners.click();
  assert(els.videoClipFixed.checked && high.hidden && els.videoClipSeconds.value === '8-8', 'toggle selects the model’s usual fixed length');
  els.videoClipFixedButton.listeners.click();
  assert(!els.videoClipFixed.checked && !high.hidden && els.videoClipSeconds.value === '', 'toggle returns to full range');
  run('syncVideoForm = savedSyncVideoForm');
  box.querySelectorAll = originalInputs; box.querySelector = originalPart;
}

// Names, places and defaults (the second batch of form changes).
assert(/<select id="videoPromptMode" name="prompt_mode" data-segmented>/.test(html) && /<select id="imagePromptMode" name="prompt_mode" data-segmented>/.test(html), 'prompt source is a select shown as the Output switch');
{
  // The switch follows the select's value and disabled, set by code or tapped.
  const store = new WeakMap();
  context.HTMLSelectElement = class {};
  for (const name of ['value', 'disabled']) Object.defineProperty(context.HTMLSelectElement.prototype, name, { configurable: true, get() { return (store.get(this) || {})[name]; }, set(v) { store.set(this, { ...(store.get(this) || {}), [name]: v }); } });
  const painted = { classes: {}, props: {} };
  const buttons = ['llm', 'direct'].map(value => ({ dataset: { value }, classList: { toggle(name, on) { painted.classes[value + name] = on; } }, setAttribute() {} }));
  const box = { style: { setProperty(name, v) { painted.props[name] = v; } }, classList: { toggle(name, on) { painted.classes[name] = on; } }, querySelectorAll: () => buttons, addEventListener(name, fn) { box.click = fn; } };
  context.fake = Object.assign(Object.create(context.HTMLSelectElement.prototype), {
    options: [{ value: 'llm', textContent: 'LLM' }, { value: 'direct', textContent: 'Exact prompt' }], nextElementSibling: box, insertAdjacentHTML(where, markup) { painted.markup = markup; },
    addEventListener(name, fn) { this.change = fn; }, dispatchEvent(e) { this.changed = e.type; } });
  context.fake.value = 'llm';
  run('segmentSelect(fake)');
  assert(painted.props['--i'] === 0 && painted.classes.llmactive === true && painted.classes.directactive === false, 'the first choice is lit');
  assert(painted.markup.includes('style="--n:2"') && painted.markup.includes('>Exact prompt</button>'), 'one button per choice');
  context.fake.value = 'direct';
  assert(painted.props['--i'] === 1 && painted.classes.directactive === true, 'code that sets the value moves the switch');
  context.fake.disabled = true;
  assert(painted.classes.off === true, 'a disabled select dims the switch');
  box.click({ target: { closest: () => buttons[0] } });
  assert(context.fake.value === 'direct', 'a disabled switch ignores taps');
  context.fake.disabled = false;
  box.click({ target: { closest: () => buttons[0] } });
  assert(context.fake.value === 'llm' && context.fake.changed === 'change' && painted.props['--i'] === 0, 'a tap sets the value and tells the form');
}
assert(html.includes('<option value="llm">LLM</option>') && html.includes('<option value="direct">Exact prompt</option>'));
assert((html.match(/>Prompt source</g) || []).length === 2 && (html.match(/>Model</g) || []).length >= 2 && !html.includes('What writes the prompts'));
assert(!html.includes('Write prompt uses the text only') && !script.includes('call it '), 'writer and reference naming hints removed');
assert(/<details class="h3-help"><summary>OpenH3-IR<\/summary><div class="hint">Before review/.test(html), 'OpenH3 explanation opens from its heading');
assert(/\.count-stepper \{[^}]*align-items: stretch/.test(html) && /\.count-stepper button \{[^}]*width: 48px;/.test(html), 'stepper buttons are wider and stretch to the input height');
assert(script.includes("const ROLE_LABELS = { image_to_prompt: 'Image to prompt', prompt_enhancer: 'Prompt enhancer' };"));
assert.strictEqual(run("roleLabel({id: 'prompt_enhancer', label: 'Enhance group'})"), 'Prompt enhancer', 'the usual name');
assert.strictEqual(run("roleLabel({id: 'prompt_enhancer', label: 'Prompt enhancer H3', named: true})"), 'Prompt enhancer H3', "one with its own name keeps it");
assert(!script.includes("select.value = 'prompt_enhancer'"), 'a workflow with a prompt enhancer offers it, and never picks it by itself');
assert(!html.includes('id="imageResolution"') && /id="imageGeneration"[\s\S]*?id="imageAspect"[\s\S]*?<\/details>/.test(html), 'Resolution in Generation');
assert(/id="imageHow">[\s\S]*?id="imageReview"[\s\S]*?id="imageSeed"/.test(html) && /id="videoHow">[\s\S]*?id="review"[\s\S]*?id="videoSeed"/.test(html), 'review and seed under Other');
for (const [field, down, up, min, max, step] of [['runs', 'runsDown', 'runsUp', 1, 10, 1], ['imageCount', 'imageCountDown', 'imageCountUp', 1, 20, 1], ['duration', 'durationDown', 'durationUp', 5, 600, 5]]) {
  const input = context.document.getElementById(field), events = [];
  input.value = String(min);
  input.stepDown = n => { input.value = String(Math.max(min, Number(input.value) - n)); };
  input.stepUp = n => { input.value = String(Math.min(max, Number(input.value) + n)); };
  input.dispatchEvent = e => events.push(e.type);
  els[down].listeners.click();
  assert.strictEqual(input.value, String(min));
  els[up].listeners.click();
  assert.strictEqual(input.value, String(min + step));
  input.value = String(max); els[up].listeners.click();
  assert.strictEqual(input.value, String(max));
  assert.deepStrictEqual(events, ['input', 'change', 'input', 'change', 'input', 'change']);
  input.value = '3';
  assert.strictEqual(input.value, '3', 'count remains directly editable');
  if (field === 'duration') {
    input.value = '13'; els[up].listeners.click(); assert.strictEqual(input.value, '18', 'five-second step preserves fine adjustment');
    els[down].listeners.click(); assert.strictEqual(input.value, '13');
  }
}
for (const [field, writer] of [['prompt', 'writeVideoPrompt'], ['imagePrompt', 'writeImagePrompt']]) {
  els[field].value = '  '; els[field].readOnly = false;
  els[field].listeners.input();
  assert(els[writer].disabled, 'empty and whitespace prompts disable the writer');
  els[field].value = 'an idea'; els[field].listeners.input();
  assert(!els[writer].disabled, 'typing enables the writer');
  els[field].readOnly = true; els[field].listeners.input();
  assert(els[writer].disabled, 'writing keeps the writer disabled');
  els[field].readOnly = false; els[field].value = ''; els[field].listeners.input();
}
assert(/<div class="go-under">\s*<button type="button" class="start-later" id="goTop"[^>]*>[^<]*<\/button>\s*<button type="button" class="start-later" id="goLater"/.test(html) && (html.match(/name="try_first"/g) || []).length === 1, 'Add to top of queue under the button, left of Add to pending');
assert(/<details class="section" id="videoHow">[\s\S]*?id="review"[\s\S]*?<label class="check not-shorts" id="previewRunLabel">/.test(html) && script.includes(".after($('previewRunLabel'))"), 'Preview run in Other, moved to whichever form is showing');
assert(/<select id="avatarSize" name="avatar_size">/.test(html), 'Shorts has a resolution');
assert(/<div id="imageToPromptSlot"><\/div>/.test(html) && /imageRole\(\) === 'image_to_prompt' \? \$\('imageToPromptSlot'\)/.test(script), "image to prompt's image right under the choice");
for (const n of [1, 2, 20]) {
  const imageInput = run(`sourceHtml(${n})`), videoInput = run(`imageBoxHtml(${n})`);
  for (const input of [imageInput, videoInput]) {
    assert(input.includes('data-pick="1"') && input.includes(`aria-label="Select image ${n} from Output"`), `image ${n} has an accessible output picker`);
  }
}

// Typing on a phone, the footer steps aside for the keyboard.
assert(!html.includes('body.typing .stick'), 'the footer never steps off the screen');

const base = fs.readFileSync(require('path').join(__dirname, '..', 'panel', 'templates', 'base.html'), 'utf8');
assert(/maximum-scale=1, user-scalable=no/.test(base) && /html \{ overflow-x: clip; touch-action: manipulation; \}/.test(base), 'no zooming the page out from under the footer');
assert(/html \{ overflow-x: clip;/.test(base) && /input, select, textarea \{ max-width: 100%; \}/.test(base) && /\.row > \* \{ flex: 1; min-width: 0; \}/.test(base),
  'nothing makes a phone page wider than its screen, so the footer stays put');
assert(/\.check > span \{ min-width: 0; overflow-wrap: anywhere; \}/.test(html) && /\.option-choice \{[^}]*max-width: 100%/.test(html), 'options wrap rather than widen it');
assert(/JUMPS\.filter\(a => top\(a\) <= line\)\.sort\(/.test(script), 'by position, not the footer order');
// Status comes first, Generate is called just that, and it sits with the options.
assert(html.indexOf('id="runCard"') < html.indexOf('id="optionsCard"'));
assert(/id="go">Generate</.test(html) && script.includes("'Add to queue'"), 'Generate, or Add to queue while something runs');
assert(/<a href="#videosCard" data-page="output" id="jumpResults">Output<\/a>/.test(html) && !html.includes('jumpCount'), 'the footer has no count on Output');
// Each heading holds its section, and the first is called Generation.
assert(!html.includes('What to make'));
assert(/<details class="section" id="formTopic">\s*<summary class="section-title">Generation</.test(html));
assert(/<details class="section" id="videoGeneration">\s*<summary class="section-title">Generation</.test(html));
assert(!/<div class="section-title">(Voice|Publish|How)/.test(html));
// Every heading starts folded, nothing brings back how they were left, and changing side folds them again.
assert(!/<details class="section"[^>]* open/.test(html) && !script.includes('localStorage.setItem(SECTIONS_KEY'));
{
  const section = { open: true };
  const all = context.document.querySelectorAll;
  context.document.querySelectorAll = selector => (selector === 'details.section' ? [section] : []);
  run("setPipeline('shorts', false)");
  assert.strictEqual(section.open, true, 'pressing the side you are on folds nothing');
  run("setPipeline('video', false)");
  assert.strictEqual(section.open, false, 'to Video');
  section.open = true;
  run("setPipeline('shorts', false)");
  assert.strictEqual(section.open, false, 'and back');
  context.document.querySelectorAll = all;
}
// On Generate the footer keeps the button and the estimate.
assert(html.indexOf('id="goStick"') > html.indexOf('id="stick"') && html.indexOf('id="goStick"') < html.indexOf('class="dashboard"'));
assert(html.indexOf('id="stop"') < html.indexOf('id="optionsCard"'), 'Stop stays with what is running');

// Whichever mode is on is marked, for the eye and for screen readers, and the other isn't.
const marks = () => {
  const made = {};
  for (const id of ['switchShorts', 'switchVideo']) {
    const button = context.document.getElementById(id);
    button.active = null;
    button.classList = { toggle: (name, on) => { if (name === 'active') button.active = on; } };
    button.setAttribute = (name, value) => { if (name === 'aria-selected') button.selected = value; };
    made[id] = button;
  }
  return made;
};
const buttons = marks();
run("setPipeline('video', false)");
assert(buttons.switchVideo.active === true && buttons.switchShorts.active === false && buttons.switchVideo.selected === true);
run("setPipeline('shorts', false)");
assert(buttons.switchShorts.active === true && buttons.switchVideo.active === false && buttons.switchShorts.selected === true);
assert(/\.switch button\.active \{[^}]*color: var\(--accent\)/.test(html) && /body\.on-video \{ --side:/.test(html));

// The side switch is Generate's, at its top; the header has no title, only the progress bars and the gear; shut down is in the settings box.
assert(html.indexOf('id="switchShorts"') > html.indexOf('id="optionsCard"') && !/<h1>/.test(html.slice(0, html.indexOf('<script>'))));
assert(/id="settingsBtn"[^>]*aria-label="Settings"/.test(html) && !/Sign out/.test(html));
assert(/<dialog id="settingsDialog"[\s\S]*id="lowPriority"[\s\S]*id="localLlmModel"[\s\S]*id="h3Model"[\s\S]*id="defaultShorts"[\s\S]*id="diskBox"[\s\S]*<div class="settings-actions">[\s\S]*id="restartPanel"[\s\S]*id="restartComfy"[\s\S]*id="forceRestartComfy"[\s\S]*href="\/logout" id="logout"[\s\S]*id="shutdown"[\s\S]*id="settingsClose"/.test(html),
  'settings, then at the foot Restart, Log out left of Shut down; the local LLM above OpenH3-IR');
assert(/\.settings-actions \{ display: flex; gap: 6px; flex: none;/.test(html), 'the buttons stay at the foot, smaller');
assert(/<div class="go-bar" id="goBar" hidden>[\s\S]*?id="goStickTop" aria-label="Add to top of queue"[\s\S]*?id="goStickLater" aria-label="Add to pending"[\s\S]*?id="goStick">/.test(html)
  && script.includes("$('goStickTop').addEventListener('click', () => $('goTop').click());") && script.includes("$('goStickLater').addEventListener('click', () => $('goLater').click());")
  && script.includes("$('goLater').hidden = $('goTop').hidden = $('goStickLater').hidden = $('goStickTop').hidden = queueSaves();")
  && script.includes("fresh: true, continued: null") && script.includes('data.continued.image ? await sameAgain(data.continued.id) : await sameAgainFilm(data.continued.id)'),
  'the footer bar has symbol buttons for top of queue and pending, beside Add to queue; a continued run reopens in full as a new run, with them');
assert(/\.tile-cover::after \{\s*content: ""; position: absolute; inset: 0; z-index: 1; border: 2px dotted var\(--accent\)/.test(html), 'a collection being moved: its outline over the picture');
assert(/<div class="settings-group" id="reserveTitle">Reserve free RAM<\/div>\s*<div class="reserve-row"[^>]*>\s*<button type="button" id="reserveSet" hidden>Set<\/button>\s*<div class="count-stepper"><button type="button" id="reserveDown"/.test(html),
  'free RAM: its heading, then Set left of a stepper as Generate\'s');
run('SETTINGS.reserve_ram_gb = 0; reserveGb = reserveSaved(); showReserve()');
assert.strictEqual(els.reserveRamValue.textContent, '3 GB', '3 GB unless set');
assert.strictEqual(els.reserveSet.hidden, true, 'nothing to set');
run('reserveGb = 6; showReserve()');
assert(els.reserveRamValue.textContent === '6 GB' && els.reserveSet.hidden === false, 'changed: Set shows');
assert(!html.includes('When Local model is chosen under Model') && /<div class="settings-group" id="localLlmTitle">Local LLM model<\/div>\s*<div class="settings-row"><select id="localLlmModel"/.test(html),
  'each model: its heading, the choice under it');
// Queue and log live in Status, the queue first, and the footer no longer goes to them.
const status = html.slice(html.indexOf('id="runCard"'), html.indexOf('id="optionsCard"'));
assert(status.indexOf('id="runQueue"') > 0 && status.indexOf('id="runQueue"') < status.indexOf('id="logBox"') && status.indexOf('id="logBox"') < status.indexOf('id="log"'));
assert(/<details class="log-box" id="logBox">\s*<summary>Log<\/summary>/.test(status) && !/id="logBox" open/.test(html), 'opened by the Log toggle above it');
assert(/<a href="#optionsCard" data-page="generate">Generate<\/a>/.test(html) && !html.includes('href="#queueCard"') && !html.includes('href="#logCard"'));
// The log is folded on a phone. On a desktop it is always open, with no heading to fold it by, beside the run at half the width.
assert.strictEqual(els.logBox.open, false, 'folded on a phone');
wide.matches = true;
run('syncLogBox()');
assert.strictEqual(els.logBox.open, true, 'open on a desktop');
wide.matches = false;
run('syncLogBox()');
assert.strictEqual(els.logBox.open, false, 'and folded again once the window is narrow');
assert(/\.log-box > summary \{ display: none; \}/.test(html));
assert(/\.run-card \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/.test(html));
assert(status.indexOf('id="logBox"') < status.indexOf('id="finished"'), 'on a phone it comes before Finished and More');

// The GPU line is right under the running line, on both.
assert(status.indexOf('id="statusText"') < status.indexOf('id="gpuLine"') && status.indexOf('id="gpuLine"') < status.indexOf('id="runProgress"'));
assert(/\.gpu \{[^}]*padding-bottom: 12px; border-bottom: 1px solid var\(--line\)/.test(html) && /\.gpu:empty, #stageDetail:empty \{ display: none; \}/.test(html), 'the GPU stats have a divider only when shown');
assert(/\.gpu \{ margin: 10px 0 12px;/.test(html), 'GPU stats clear the ComfyUI status icon');

// The clip being rendered is said quietly in ComfyUI's box, which no longer names ComfyUI.
assert(!status.includes('<span>ComfyUI:</span>'));
context.atStage = (detail, comfy) => ({ running: true, pipeline: 'shorts', gpu: null, progress: { stage: [4, 7, 'Avatar clips'], detail },
  comfyui: comfy ? { active: true, connected: true, label: 'Generating video', value: 3, max: 8, elapsed: 65, queue: 1 } : {} });
run(`renderNow(atStage('Clip 2 of 5 - scene 3, 6s lipsync', true))`);
assert.deepStrictEqual(lines(els.comfyMeta), { first: 'scene 3, 6s lipsync', count: 'Clip 2 of 5', time: '1:05', twoLines: true },
  'what it renders and how long; then which one on the left, its time on the right');
run(`renderNow({ ...atStage('Clip 6 of 8: The Descent to Knees, 5s', true), pipeline: 'video', progress: { stage: [2, 3, 'Clips'], detail: 'Clip 6 of 8: The Descent to Knees, 5s', action: 'Rendering clip' } })`);
assert.strictEqual(lines(els.comfyMeta).first, 'Rendering clip - The Descent to Knees, 5s', 'action - title, duration');
assert.strictEqual(lines(els.comfyMeta).count, 'Clip 6 of 8');
assert.strictEqual(els.comfySteps.textContent, 'Step 3 of 8', 'steps start with a capital');
assert.strictEqual(els.stageDetail.innerHTML, '', 'and not said again above it');
run(`renderNow(atStage('Clip 2 of 5 - scene 3, 6s lipsync', false))`);
run(`renderNow({ ...atStage('Clip 1 of 2: Clip 1, 10s', false), pipeline: 'video', progress: { stage: [2, 3, 'Clips'], detail: 'Clip 1 of 2: Clip 1, 10s', action: 'Enhancing prompt', action_elapsed: 292 } })`);
assert.deepStrictEqual(lines(els.stageDetail), { first: 'Enhancing prompt - Clip 1, 10s', count: 'Clip 1 of 2', time: '4:52', twoLines: true }, 'a long step says how long it has been at it');
run(`renderNow(atStage('Clip 2 of 5 - scene 3, 6s lipsync', false))`);
assert.deepStrictEqual(lines(els.stageDetail), { first: 'scene 3, 6s lipsync', count: 'Clip 2 of 5', time: '', twoLines: true }, 'no box up yet: it still says it');
run(`renderNow(atStage('Scene 4 of 9', true))`);
assert.strictEqual(lines(els.stageDetail).count, 'Scene 4 of 9', 'only a clip goes in the box');
assert.deepStrictEqual(lines(els.comfyMeta), { first: '', count: '', time: '1:05', twoLines: false }, 'no clip: one line, the time on its right');
assert(!els.stepper.hidden, 'a job with stages shows its stepper');
// An upscale has no stages of its own: ComfyUI's box and bar still show, without an empty stepper.
run(`renderNow({ ...atStage('', true), pipeline: 'image', progress: { action: 'Upscaling' } })`);
assert(els.stepper.hidden && els.stageDetail.hidden && els.comfyBar.style.width === '38%' && els.comfySteps.textContent === 'Step 3 of 8', 'no stage: the box and its bar alone');
assert(/\$\('now'\)\.classList\.toggle\('hidden', !show && !comfyBusy\)/.test(script), 'the box shows whenever ComfyUI works');
assert.deepStrictEqual(lines({ innerHTML: run(`statusHtml('Stitching', '', '0:42')`) }), { first: 'Stitching', count: '', time: '0:42', twoLines: false },
  'not two lines: the time at the right of the first');
assert.strictEqual(run(`statusHtml('Generating prompts')`), '<div class="status-foot"><span class="status-first">Generating prompts</span></div>');
assert(/\.status-foot > \.status-first:only-child \{ flex: 1; text-align: center; \}/.test(html), 'a status that is only text is centred');

// The header's bars show while Status's own are out of sight: on another page, or on Status scrolled past them.
run('stripActive.run = true; stripActive.upload = false; syncStrips()');
assert.strictEqual(els.runStrip.hidden, true, "Status's bar in sight");
for (const id of ['runProgress', 'uploadProgress']) context.document.getElementById(id).getBoundingClientRect = () => ({ top: 5000, bottom: 5100 });
run('syncStrips()');
assert.strictEqual(els.runStrip.hidden, false, "scrolled past Status's bar");
assert(script.includes('$(`${job}Strip`).hidden = !stripActive[job] || inView(`${job}Progress`);'), 'by its own bar on Status, not the whole card');
for (const id of ['runProgress', 'uploadProgress']) context.document.getElementById(id).getBoundingClientRect = () => ({ top: 0, bottom: 100 });
run('stripActive.run = false; syncStrips()');

// The switch: each side only shows what applies to it, and a job on the other still shows.
assert(/class="[^"]*only-shorts[^"]*" id="uploadQueue"/.test(html) && /class="[^"]*only-shorts[^"]*" id="uploadLog"/.test(html));
assert(/class="only-shorts" id="uploadAll"/.test(html) && /class="tabs only-shorts"/.test(html));
assert(/id="formVideo"/.test(html) && !/name="upload"[^>]*>[\s\S]*id="formVideo"[\s\S]*name="upload"/.test(html), 'Video has no upload option');

// Queue: held jobs offer Resume, and every item can be removed.
const queue = element('q');
queue.dataset.title = 'Queue';
context.queue = queue;
run(`renderQueue(queue, { items: [{ id: 3, label: 'a <film>', detail: 'd', estimate: 600 }], results: [], held: true, current: null }, 0)`);
assert(queue.innerHTML.includes('<b>Queue (1)</b>'));
assert(queue.innerHTML.includes('<span class="when">On hold</span>'), 'held queue has a concise hint');
assert(queue.innerHTML.includes('data-resume') && queue.innerHTML.includes('data-remove="3"') && queue.innerHTML.includes('a &lt;film&gt;'));
assert(queue.innerHTML.indexOf('data-resume') > queue.innerHTML.indexOf('data-remove="3"'), 'Resume sits under what it lets go');
assert(!queue.innerHTML.includes('selected'), 'one job alone cannot be reordered');
run(`renderQueue(queue, { items: [], results: [{ label: 'x', outcome: 'done', at: '17:00' }, { label: 'y', outcome: 'done', at: '17:01' }], held: false, current: null }, 0)`);
assert.strictEqual(queue.hidden, true, 'what finished is under Finished, not in the queue');
assert.strictEqual(queue.innerHTML, '', 'and nothing stale, with its Resume, is left in it');
run(`renderQueue(queue, { items: [{ id: 3, label: 'a', detail: 'd' }, { id: 4, label: 'b', detail: 'd' }], results: [], held: false, current: null }, 0)`);
assert(!queue.innerHTML.includes('data-grip') && !queue.innerHTML.includes('queue-item selected'), 'no drag handle or selection initially');
run('dragQueue(queue)');
const selectedRow = { dataset: { id: '3' }, querySelector: () => ({}) };
const selectedTarget = { closest: selector => selector === '.queue-item' ? selectedRow : null };
queue.listeners.click({ target: selectedTarget });
assert(queue.innerHTML.includes('class="queue-item selected" data-id="3"'), 'selecting an entry outlines it');
const otherRow = { dataset: { id: '4' }, querySelector: () => ({}) };
queue.listeners.click({ target: { closest: selector => selector === '.queue-item' ? otherRow : null } });
assert(queue.innerHTML.includes('class="queue-item selected" data-id="4"') && !queue.innerHTML.includes('class="queue-item selected" data-id="3"'), 'selecting another entry moves the outline');
queue.listeners.click({ target: selectedTarget });
queue.listeners.click({ target: selectedTarget });
assert(!queue.innerHTML.includes('queue-item selected'), 'selecting it again clears the outline');
queue.listeners.click({ target: selectedTarget });
run(`queue._dragging = true; renderQueue(queue, { items: [{ id: 4, label: 'b', detail: 'd' }], results: [], held: false, current: null }, 0); queue._dragging = false`);
assert(queue.innerHTML.includes('class="queue-item selected" data-id="3"'), 'nothing is drawn over a job being dragged');
run(`renderQueue(queue, { items: [{ id: 4, label: 'b', detail: 'd' }, { id: 5, label: 'c', detail: 'd' }], held: false, current: null }, 0)`);
assert.strictEqual(queue._selected, null, 'a departed selected entry cannot leave another selected');
queue.dataset.lane = 'run';
run(`renderQueue(queue, { items: [], held: false, running: true, pipeline: 'image', stopAfter: false }, 0)`);
assert(!queue.hidden && queue.innerHTML.includes('aria-label="Pause after current"'), 'a running batch can be paused even with an empty queue');
run(`renderQueue(queue, { items: [{ id: 3, label: 'a', detail: 'd' }], held: true, running: true, pipeline: 'image', stopAfter: true }, 0)`);
assert(queue.innerHTML.includes('aria-label="Resume queue"') && !queue.innerHTML.includes('data-resume'), 'play is in the queue header, not a second Resume button');
run(`renderQueue(queue, { items: [{ id: 4, label: 'continue', detail: 'd', pipeline: 'video', resume: 'run_1' }], held: true }, 0)`);
assert(queue.innerHTML.includes('data-shots="run_1"'), 'continued jobs in the queue expose their prompts');
assert(queue.innerHTML.includes(`data-shots="run_1" aria-label="Prompts" title="View prompts">${run('ICONS.enhanced')}</button>`), 'queued prompts use the star');
assert(/class="queue-item run-card"[^>]*>[\s\S]*class="queue-item-top"[\s\S]*class="what"[\s\S]*class="hint"[\s\S]*<\/div><\/div><div class="queue-item-actions">\s*<span class="acts-side">[\s\S]*data-pause="4"[\s\S]*<\/span><span class="when">[^<]*<\/span><span class="acts-side acts-end">[\s\S]*data-shots="run_1"[\s\S]*data-edit="4"[\s\S]*data-remove="4"/.test(queue.innerHTML), 'run details and actions occupy separate rows in a card: Pending on the left, the time in the middle, the rest on the right');
assert(/\.queue-item\.run-card \{[^}]*background: var\(--panel-2\); border: 1px solid var\(--line\); border-radius: 10px/.test(html) && /\.stopped-actions, \.queue-item\.run-card \.queue-item-actions \{ display: grid; grid-template-columns: minmax\(max-content, 1fr\) auto minmax\(max-content, 1fr\);/.test(html)
  && /\.acts-side \{ display: flex; flex-wrap: nowrap;/.test(html), 'run cards match Pending: the time centred, each side on one line');
// Under the running job's title: its workflow on the left, its size on the right.
assert(/<div class="current-work-size" id="currentWorkSize" hidden><span id="currentWorkflow"><\/span><span id="currentResolution"><\/span><\/div>/.test(html)
  && /#currentWorkSize \{ display: flex; justify-content: space-between;/.test(html), 'workflow left, resolution right');
assert(script.includes("$('currentWorkflow').textContent = facts.workflow || '';") && script.includes("$('currentResolution').textContent = facts.resolution || '';"));
assert(!/\.status-head #dot \{ display: none; \}/.test(html) && /\.switch button \.dot \{ display: none; \}/.test(html), 'the status light is in Status, not on the side switch');
assert(/\.status-head #statusText:empty \{ display: none; \}/.test(html) && /\.status-head \.status \+ \.status-times \{ margin-left: -4px; \}/.test(html), 'the timers sit close to the light');
assert(script.includes("function transitionViewer(media, direction, open, target = media) {") && script.includes("$(next.film ? 'viewerVideo' : 'viewerImage'));"),
  'between a film and a set, the swipe waits on what shows next, not on what showed before');
assert(/#runActions::after \{ bottom: -10px; border: 1px solid var\(--line\); border-top: 0;/.test(html)
  && /#runActions::before \{[^}]*border-left: 1px dotted var\(--line\); border-right: 1px dotted var\(--line\);[^}]*mask-image: linear-gradient\(to top, #000 15%, transparent\);/.test(html),
  'the running part ends in the queue box\'s line: solid along the bottom and corners, dotted and fading up both sides alike');
assert(/#runCard \{ --accent: var\(--shared\); \}/.test(html) && /#runCard \.bar > div \{ background: var\(--job, var\(--shared\)\); \}/.test(html) && /#runStrip \.bar > div \{ background: var\(--shared\); \}/.test(html)
  && /#runCard \.step\.now \{ border-color: var\(--job, var\(--shared\)\); \}/.test(html), 'Status is violet, its bars the colour of the job; the header bar violet whichever job');
assert(script.includes("document.documentElement.style.setProperty('--job', running && SIDE_COLOURS[data.pipeline] || '');"), 'the job colour follows what is generating, and goes when idle');
assert(/#runCard \.ln-more \{ color: var\(--job, var\(--side-accent\)\); \}/.test(html) && /\.jump a\.run\.active \{ border-color: var\(--shared\); \}/.test(html),
  'the log\'s highlights keep the type colour; Status in the bottom bar always violet');
assert(/\.ln\.stage \.x \{ color: var\(--neutral\); \}/.test(html) && /\.settings-group \{[^}]*color: var\(--neutral\);/.test(html), 'the log\'s and settings\' headers are silver, as Status\'s');
assert(!html.includes('id="logWorkflow"') && /\.log-tools #logComfy \{ margin-left: auto; \}/.test(html), 'no Workflow in the log; ComfyUI and Errors on the right');
// Titles in the queues: two lines and "…", with no tap to open them.
assert(queue.innerHTML.includes('<span class="queue-title" data-title-key="queue-4"><span class="queue-pos">1.</span> Video: continue</span>'), 'a queue title is cut to two lines, titled as the running one, its place greyed');
assert(/\.queue-pos \{ color: var\(--muted\);/.test(html), 'the place in the queue is grey');
run(`renderQueue(queue, { items: [{ id: 5, label: '1 video: a storm', detail: 'd', pipeline: 'video' }, { id: 6, label: '3 images: cats', detail: 'd', pipeline: 'image', facts: { count: 3 } }], held: true }, 0)`);
assert(queue.innerHTML.includes('<span class="queue-pos">1.</span> Video: a storm</span>') && queue.innerHTML.includes('<span class="queue-pos">2.</span> Image(3): cats</span>'),
  '"1 video" is just Video:, three images are Image(3):');
assert(/\.queue-title \{ display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2;/.test(html) && !html.includes('.queue-title.expanded') && !html.includes('openTitles'), 'a title is cut to two lines, with no tap to open it');
run(`renderQueue(queue, { items: [{ id: 4, label: 'continue', detail: 'd', pipeline: 'video', resume: 'run_1' }], held: true }, 0)`);
assert(/\.queue \.queue-item-actions button, \.queue \.stopped-actions button \{\s*flex: none; width: 34px; height: 28px; padding: 0;/.test(html), 'queue and pending action buttons use the same remove-button dimensions');
assert(queue.innerHTML.includes('class="icon-btn" data-pause="4"') && queue.innerHTML.includes('class="icon-btn" data-remove="4"'), 'queue pause feedback and delete confirmation fit the fixed-size buttons');
assert(queue.innerHTML.includes(`data-remove="4" aria-label="Remove from the queue" title="Remove from the queue (tap twice)">${run('ICONS.trash')}</button>`), 'queue removal uses the shared trash icon');
run(`renderQueue(queue, { items: [{ id: 1, label: 'new', detail: '', pipeline: 'image', continuation: false },
  { id: 2, label: 'continue', detail: '', pipeline: 'image', resume: 'image_1', continuation: true }], held: true }, 0, false, true)`);
assert(queue.innerHTML.includes('class="run-item" data-run="1"') && queue.innerHTML.includes('class="run-item continue-item" data-run="2"'), 'only the continued queued job has a green play control');
assert(queue.innerHTML.indexOf('data-run="2"') < queue.innerHTML.indexOf('data-shots="image_1"'), 'queued play precedes prompts');
assert(/\.queue \.run-item \{[^}]*color: var\(--text\)/.test(html) && /\.queue \.queue-item-actions \.continue-item \{ color: var\(--ok\)/.test(html), 'new jobs use the ordinary button colour and continuations use green');
assert(!/class="queue-item run-card"/.test(written), 'Pending remains separate from the queue');
assert(!/id="stopAfter"/.test(html), 'pause moved out of the run actions');
assert(!script.includes('ComfyUI is making each image.'), 'the redundant image stage hint is not shown');
assert(queue.innerHTML.includes('data-fold-queue="1" aria-expanded="true"') && queue.innerHTML.includes('class="queue-list" tabindex="0"'), 'run queue has a separate collapsible scrollable list');
assert(/class="queue-head run-queue-head"[\s\S]*class="queue-fold-toggle queue-fold-title"[\s\S]*data-queue-toggle="1"[\s\S]*class="queue-fold-toggle queue-fold-arrow" data-fold-queue="1" aria-expanded="true" aria-label="Collapse queue"/.test(queue.innerHTML), 'queue-wide control stays on the right');
assert(/\.queue-head\.run-queue-head \{ display: grid; grid-template-columns: minmax\(0, 1fr\) auto 26px 20px; \}/.test(html) && /\.run-queue-head \[data-queue-toggle\] \{ grid-column: 3; \}/.test(html), 'queue-wide control and chevron stay right of the title');
assert(/\.queue \.queue-head button\[data-queue-toggle\] \{ width: 26px; height: 26px; padding: 0; display: inline-flex; align-items: center;/.test(html), 'the queue play is small, its icon centred');
assert(/\.queue-head \.queue-fold-arrow \{[^}]*justify-content: flex-end/.test(html) && /\.queue-fold-toggle \.chev \{[^}]*transition: transform \.25s ease; margin-right: 4px/.test(html), 'queue chevron aligns and turns like Pending and Failed');
queue._open = false;
run(`renderQueue(queue, { items: [{ id: 1, label: 'new', detail: '', pipeline: 'image' }] }, 0)`);
assert(queue.innerHTML.includes('aria-expanded="false"') && queue.innerHTML.includes('class="queue-list" tabindex="0" hidden'), 'collapsed queue stays collapsed through redraws');
assert(queue.innerHTML.includes('aria-label="Expand queue"'), 'the chevron reflects the collapsed state');
{
  const liveQueue = els.runQueue;
  const attrs = [{}, {}];
  const controls = attrs.map((attr, i) => ({
    classList: { contains: name => i === 1 && name === 'queue-fold-arrow' },
    setAttribute: (name, value) => { attr[name] = value; },
  }));
  const list = { hidden: false, scrollTop: 0, style: { setProperty() {} }, querySelectorAll: () => [] };
  liveQueue._open = true;
  liveQueue.dataset.html = '<button aria-expanded="true"></button><button aria-expanded="true" aria-label="Collapse queue"></button><div class="queue-list" tabindex="0"></div>';
  liveQueue.querySelector = selector => selector === '.queue-list' ? list : null;
  liveQueue.querySelectorAll = selector => selector === 'button[data-fold-queue]' ? controls : [];
  liveQueue.listeners.click({ target: { closest: selector => selector === 'button[data-fold-queue]' ? controls[0] : null } });
  assert(list.hidden && attrs.every(a => a['aria-expanded'] === 'false') && attrs[1]['aria-label'] === 'Expand queue', 'clicking the title updates the chevron and its accessible state');
  assert(liveQueue.dataset.html.includes('aria-label="Expand queue"') && liveQueue.dataset.html.includes('tabindex="0" hidden'), 'polling retains the animated controls instead of replacing them');
  let reveal;
  liveQueue.scrollIntoView = options => { reveal = options; };
  liveQueue.listeners.click({ target: { closest: selector => selector === 'button[data-fold-queue]' ? controls[0] : null } });
  assert(reveal && reveal.behavior === 'smooth', 'opening the queue reveals it smoothly');
  for (const id of ['stoppedRuns', 'failedRuns']) {
    let options;
    els[id]._open = false;
    const fold = { open: true, matches: selector => selector === '.stopped-fold', scrollIntoView: value => { options = value; } };
    els[id].listeners.toggle({ target: fold });
    assert(options && options.behavior === 'smooth', `${id} scrolls into view when opened`);
    options = null;
    els[id].listeners.toggle({ target: fold });
    assert.strictEqual(options, null, `${id} does not scroll again after a redraw`);
  }
}
{
  const rows = [0, 60, 170, 265].map((top, index) => ({ offsetTop: top, offsetHeight: [54, 104, 89, 80][index], getClientRects: () => [1] }));
  const properties = {};
  const list = { scrollTop: 0, style: { setProperty: (key, value) => { properties[key] = value; } }, querySelectorAll: () => rows };
  context.measuredSection = { querySelector: () => list };
  run("setupQueueScroll(measuredSection, '.queue-list', '.queue-item', 40)");
  assert.strictEqual(properties['--three-rows'], '259px', 'the cap fits exactly the first three variable-height cards');
  assert.strictEqual(list.scrollTop, 40, 'redraw restores the scroll position');
}
assert(html.includes('.queue-list, .stopped-body') && html.includes('max-height: min(var(--three-rows, 55dvh), 55dvh)'), 'queue, pending and failed scroll rather than growing past the viewport');
assert(!/\.queue-list, \.stopped-body \{[^}]*overscroll-behavior:\s*contain/.test(html), 'scrolling at a list boundary can continue on the page');

// ComfyUI's status, a tap on its icon away: one that's up but doesn't answer, on a PC out of memory, says why.
run(`renderComfy({ online: false, listening: true, can_start: true, ram: { free: 2.1, total: 31.9 }, gpu: { util: 7, mem_used: 5.8, mem_total: 12, power: 26, temp: 40 } })`);
assert(els.comfyFacts.innerHTML.includes('not answering') && els.comfyFacts.innerHTML.includes('29.8/31.9GB used · 2.1GB free'));
assert(!els.comfyAdvice.hidden && els.comfyAdvice.textContent.includes('paging'));
run(`renderComfy({ online: true, active: true, label: 'Generating the image', value: 3, max: 8, queue: 1, ram: { free: 20, total: 32 } })`);
assert(els.comfyFacts.innerHTML.includes('Generating the image · 3/8') && els.comfyAdvice.hidden, 'nothing to advise when all is well');

// The status recovers by itself.
(async () => {
  {
    const section = element('drag-test'), order = [], sent = [], frames = [];
    section.dataset.lane = 'run';
    section._selected = '1';
    section.setPointerCapture = id => { section.captured = id; };
    section.querySelectorAll = selector => selector === '.queue-item[data-id]' ? order : [];
    section._last = [{ items: [] }, 0];
    const list = { classList: { contains: name => name === 'queue-list' }, scrollTop: 50, scrollHeight: 300, clientHeight: 200,
      getBoundingClientRect: () => ({ top: 0, bottom: 200, height: 200 }),
      appendChild(row) { order.splice(order.indexOf(row), 1); order.push(row); } };
    for (let i = 1; i <= 3; i++) {
      const active = new Set();
      const row = { dataset: { id: String(i) }, parentElement: list, style: {}, animations: 0,
        classList: { add: c => active.add(c), remove: c => active.delete(c), contains: c => active.has(c) },
        getBoundingClientRect() { const top = order.indexOf(this) * 100 - list.scrollTop + (parseFloat(this.style.transform?.match(/-?[\d.]+/)?.[0]) || 0); return { top, height: 100 }; },
        animate() { this.animations++; },
        before(node) { order.splice(order.indexOf(node), 1); order.splice(order.indexOf(this), 0, node); },
        after(node) { order.splice(order.indexOf(node), 1); order.splice(order.indexOf(this) + 1, 0, node); },
      };
      Object.defineProperty(row, 'nextElementSibling', { get() { return order[order.indexOf(this) + 1] || null; } });
      Object.defineProperty(row, 'previousElementSibling', { get() { return order[order.indexOf(this) - 1] || null; } });
      row.classList.contains = c => c === 'queue-item' || active.has(c);
      order.push(row);
    }
    const target = { closest: selector => selector === '.queue-item' ? order.find(row => row.dataset.id === '1') : null };
    context.dragTest = section;
    const oldRaf = context.requestAnimationFrame, oldCancel = context.cancelAnimationFrame;
    context.requestAnimationFrame = fn => { frames.push(fn); return frames.length; };
    context.cancelAnimationFrame = () => {};
    run('var savedSendOrder = sendOrder; sendOrder = el => { testSent.push(queueOrder(el)); }; dragQueue(dragTest)');
    context.testSent = sent;
    section.listeners.pointerdown({ target, button: 0, pointerId: 7, clientX: 0, clientY: 0, preventDefault() {} });
    section.listeners.pointermove({ pointerId: 7, clientX: 0, clientY: 210 });
    assert.deepStrictEqual(order.map(row => row.dataset.id), ['2', '3', '1'], 'dragging pushes crossed items upward');
    assert(order[2].classList.contains('dragging'), 'held from the press, it takes each place it is dragged to');
    assert(/\.queue-item\.dragging \{[^}]*outline-style: solid;/.test(html) && !/\.queue-item\.dragging \{[^}]*0 0 0 1px var\(--accent\)/.test(html), 'held, the dotted outline turns solid, with no second line');
    assert(order[0].animations > 0, 'displaced items animate');
    frames.shift()(16);
    assert(list.scrollTop > 50, 'holding near the bottom scrolls the list');
    section.listeners.pointerup({ type: 'pointerup', pointerId: 7 });
    assert.strictEqual(section._selected, null, 'released, it is let go');
    assert.deepStrictEqual(Array.from(sent[0]), [2, 3, 1], 'drop sends the new order');
    frames.length = 0;
    list.scrollTop = 50;
    section._selected = '1';
    section.listeners.pointerdown({ target, button: 0, pointerId: 8, clientX: 0, clientY: 160, preventDefault() {} });
    section.listeners.pointermove({ pointerId: 8, clientX: 0, clientY: -10 });
    assert.deepStrictEqual(order.map(row => row.dataset.id), ['1', '2', '3'], 'dragging upward pushes crossed items down');
    frames.shift()(16);
    assert(list.scrollTop < 50 + 8, 'holding near the top scrolls upward');
    section.listeners.pointercancel({ type: 'pointercancel', pointerId: 8 });
    assert.deepStrictEqual(order.map(row => row.dataset.id), ['2', '3', '1'], 'cancel restores the original order');
    assert.strictEqual(sent.length, 1, 'cancel does not submit an order');
    // Held at the list's top, the list scrolls up, faster the longer it is held; at its end it stops, and the page stays.
    {
      const savedWindow = { scrollBy: context.window.scrollBy, scrollY: context.window.scrollY };
      let listTop = 20000;
      Object.defineProperty(list, 'scrollTop', { configurable: true, get: () => listTop, set: v => { listTop = Math.min(30000, Math.max(0, v)); } });
      list.scrollHeight = 30200;
      context.window.scrollY = 5000;
      context.window.scrollBy = (x, y) => { context.window.scrollY += y; };
      frames.length = 0;
      section._selected = '1';
      section.listeners.pointerdown({ target, button: 0, pointerId: 9, clientX: 0, clientY: 160, preventDefault() {} });
      section.listeners.pointermove({ pointerId: 9, clientX: 0, clientY: 5 });
      const steps = [];
      for (let t = 16, last = listTop; t <= 16 * 4000 && frames.length; t += 16) {
        frames.shift()(t);
        steps.push(last - listTop);
        last = listTop;
      }
      const moving = steps.filter(step => step > 0);
      assert(moving[60] > moving[1] * 1.5, 'the list speeds up the longer it is held');
      assert.strictEqual(listTop, 0, 'it scrolls to its own top');
      assert.strictEqual(context.window.scrollY, 5000, 'and stops there: the page does not carry on');
      assert.strictEqual(frames.length, 0, 'nothing more is scheduled');
      section.listeners.pointercancel({ type: 'pointercancel', pointerId: 9 });
      delete list.scrollTop;
      list.scrollTop = 50;
      list.scrollHeight = 300;
      Object.assign(context.window, savedWindow);
    }
    // A tap on the selected job, without dragging, lets it go.
    section._selected = '1';
    section.listeners.pointerdown({ target, button: 0, pointerId: 10, clientX: 0, clientY: 50, preventDefault() {} });
    section.listeners.pointerup({ type: 'pointerup', pointerId: 10 });
    assert.strictEqual(section._selected, null, 'a tap without dragging lets it go');
    list.scrollHeight = 300;
    section.listeners.pointercancel({ type: 'pointercancel', pointerId: 9 });
    section._selected = '1';
    const title = { closest: selector => selector === '.queue-item' ? order[2] : null, focus() {} };
    section.listeners.keydown({ key: 'ArrowUp', target: { closest: selector => selector === '.what[role="button"]' ? title : null }, preventDefault() {} });
    assert.deepStrictEqual(order.map(row => row.dataset.id), ['2', '1', '3'], 'keyboard arrows reorder the selected entry');
    assert.deepStrictEqual(Array.from(sent[1]), [2, 1, 3], 'keyboard reorder is submitted');
    run('sendOrder = savedSendOrder');
    context.requestAnimationFrame = oldRaf; context.cancelAnimationFrame = oldCancel;
  }
  {
    // Saving a collection's edit: the new name, then its picture (Automatic being none chosen).
    const savedFetch = context.fetch, savedPoll = run('poll'), asked = [];
    context.fetch = async (url, init) => { asked.push([url, JSON.parse(init.body)]); return { ok: true, json: async () => ({ ok: true }) }; };
    run(`allImageSets = [{ id: 'image_1', label: 'S', images: [{ position: 1, file: 'a.png', title: 'a', version: 1 }, { position: 2, file: 'b.png', title: 'b', version: 1 }] }];
         collections = [{ id: 'c_1', name: 'Mine', items: [{ kind: 'image', set: 'image_1', file: 'a.png' }, { kind: 'image', set: 'image_1', file: 'b.png' }], cover: { kind: 'image', set: 'image_1', file: 'b.png' } }];
         $('collectionEdit').showModal = () => {}; $('collectionEdit').close = () => {}; poll = () => {}; openCollectionEdit('c_1')`);
    els.collectionEditPicker.listeners.click({ target: { closest: () => ({ dataset: { pick: 'auto' } }) } });
    els.collectionEditName.value = ' Renamed ';
    await els.collectionEditSave.listeners.click();
    assert.strictEqual(JSON.stringify(asked), '[["/api/collections/c_1/rename",{"name":"Renamed"}],["/api/collections/c_1/cover",{"item":null}]]', 'saved: the name, then no chosen picture');
    asked.length = 0;
    run("openCollectionEdit('c_1')");
    els.collectionEditPicker.listeners.click({ target: { closest: () => ({ dataset: { pick: '0' } }) } });
    await els.collectionEditSave.listeners.click();
    assert.strictEqual(JSON.stringify(asked), '[["/api/collections/c_1/cover",{"item":{"kind":"image","run":"image_1","file":"a.png"}}]]', 'a picture of its own chosen: only that is sent');
    run("collections = []; allImageSets = []");
    context.savedCollectionPoll = savedPoll;
    run('poll = savedCollectionPoll');
    context.fetch = savedFetch;
  }
  {
    const savedFetch = context.fetch, savedAlert = context.alert;
    let message = '';
    context.alert = text => { message = text; };
    context.fetch = async () => ({ json: async () => ({ ok: true }) });
    run(`queueEdit = { id: 7, token: 'token', pipeline: 'video', ready: true }; queueEditLabel()`);
    await run("removeQueued('run', '8')");
    assert(run('queueEdit !== null'), 'removing another job keeps the active edit');
    await run("removeQueued('run', '7')");
    assert(run('queueEdit === null') && els.cancelQueueEdit.hidden && !els.goLater.hidden, 'removing the edited job releases the form');
    run(`queueEdit = { id: 9, token: 'token', pipeline: 'video', ready: true }; queueEditLabel()`);
    context.fetch = async () => ({ json: async () => ({ ok: false }) });
    await run("removeQueued('run', '9')");
    assert(run('queueEdit !== null') && message, 'failed removal retains the edit and reports an error');
    run(`const staleEdit = queueEdit; queueEdit = { id: 10, token: 'new', pipeline: 'image', ready: true };
         reconcileQueueEdits({ items: [] }, staleEdit, null)`);
    assert(run('queueEdit.id === 10'), 'a stale status cannot close a newer edit');
    run(`reconcileQueueEdits({ items: [{ id: 10, editing: true }] }, queueEdit, null)`);
    assert(run('queueEdit.id === 10'), 'an active edit survives status reconciliation');
    run(`reconcileQueueEdits({ items: [] }, queueEdit, null)`);
    assert(run('queueEdit === null'), 'removal in another tab releases the form');
    run(`queueUpscaleEdit = { id: 12, token: 'token', kind: 'video_upscale' }; $('upscaleSettings').showModal();
         reconcileQueueEdits({ items: [] }, null, queueUpscaleEdit)`);
    assert(run('queueUpscaleEdit === null') && !els.upscaleSettings.open, 'removal closes an upscale edit');
    let finishFile;
    context.savedEditQueueRequest = run('queueRequest');
    context.savedEditPoll = run('poll');
    context.testQueuedEdit = { id: 13, token: 'token', pipeline: 'video', files: ['image'], filenames: { image: 'image.png' } };
    run('queueRequest = async () => testQueuedEdit; poll = () => {}');
    context.fetch = async url => String(url).includes('/file/')
      ? { ok: true, blob: () => new Promise(resolve => { finishFile = resolve; }) }
      : { json: async () => ({ ok: true }) };
    const opening = run("editQueued('13', {})");
    await new Promise(resolve => setImmediate(resolve));
    await run("removeQueued('run', '13')");
    finishFile({});
    await opening;
    assert(run('queueEdit === null'), 'an in-flight file restore cannot resurrect a removed edit');
    run('queueRequest = savedEditQueueRequest; poll = savedEditPoll');
    context.fetch = savedFetch; context.alert = savedAlert;
  }
  {
    const savedFetch = context.fetch;
    const savedInterval = context.setInterval, savedClear = context.clearInterval, savedNow = context.performance.now;
    let resolve, update, now = 0, cleared = false, started;
    const postStarted = new Promise(done => { started = done; });
    context.performance.now = () => now;
    context.setInterval = fn => { update = fn; return 42; };
    context.clearInterval = id => { if (id === 42) cleared = true; };
    context.fetch = (url, options) => {
      if (url.startsWith('/api/write-prompt?')) return Promise.resolve({ ok: true, json: async () => ({ ok: true, seconds: 100, model: 'gemma-4-12b' }) });
      assert.strictEqual(url, '/api/write-prompt');
      assert.strictEqual(JSON.parse(options.body).pipeline, 'video');
      assert.strictEqual(JSON.parse(options.body).model, 'gemma-4-12b');
      started();
      return new Promise(done => { resolve = done; });
    };
    els.prompt.value = 'a harbour';
    els.videoPromptMode.value = 'llm';
    const writing = run("writePrompt('video')");
    assert(els.prompt.readOnly && els.writeVideoPrompt.disabled, 'prompt locked while writing');
    await postStarted;
    assert(!els.videoPromptEta.hidden && els.videoPromptEta.textContent.includes('left'), 'estimated time shown during writing');
    assert.strictEqual(els.videoPromptProgress.style.width, '0%');
    now = 50000; update();
    assert.strictEqual(els.videoPromptProgress.style.width, '50%');
    now = 100000; update();
    assert.strictEqual(els.videoPromptProgress.style.width, '95%');
    assert.strictEqual(els.videoPromptEta.textContent, 'Taking longer than estimated');
    now = 150000; update();
    assert.strictEqual(els.videoPromptProgress.style.width, '95%', 'progress stays capped while overdue');
    resolve({ ok: true, json: async () => ({ ok: true, prompt: 'A cinematic harbour.' }) });
    await writing;
    assert.strictEqual(els.prompt.value, 'A cinematic harbour.');
    assert.strictEqual(els.videoPromptMode.value, 'llm', 'writing a video brief keeps LLM planning selected');
    assert(!els.prompt.readOnly && !els.writeVideoPrompt.disabled);
    assert(cleared && els.videoPromptEta.hidden && els.videoPromptProgress.hidden, 'progress timer and UI are cleared');
    context.fetch = async url => String(url).includes('?') ? { ok: true, json: async () => ({ ok: true, seconds: 100, model: 'gemma-4-12b' }) }
      : { ok: true, json: async () => ({ ok: true, prompt: 'A rewritten prompt.' }) };
    els.videoPromptMode.value = 'direct';
    await run("writePrompt('video')");
    assert.strictEqual(els.videoPromptMode.value, 'direct', 'writing an exact video prompt keeps exact mode');
    context.fetch = async url => String(url).includes('?') ? { ok: true, json: async () => ({ ok: true, seconds: 100, model: 'gemma-4-12b' }) }
      : { ok: false, json: async () => ({ ok: false, error: 'model failed' }) };
    els.imagePrompt.value = 'a tree';
    await run("writePrompt('image')");
    assert.strictEqual(els.imagePrompt.value, 'a tree', 'failure preserves the input');
    assert.strictEqual(els.imagePromptWriteError.textContent, 'model failed');
    assert(!els.imagePromptWriteError.hidden && !els.imagePrompt.readOnly);
    context.fetch = savedFetch;
    context.setInterval = savedInterval; context.clearInterval = savedClear; context.performance.now = savedNow;
  }
  {
    const savedNavigator = context.navigator, savedCreateElement = context.document.createElement;
    const savedExec = context.document.execCommand, savedAlert = context.alert;
    context.imageRun.shots[0].enhanced_prompt = 'A <b>bright</b> lighthouse\nSecond line';
    run('shotsRun = imageRun; shotsDirty = true');
    els.shotsDialog.open = true;
    const target = { dataset: { enhanced: '1' }, closest: () => null };
    await els.shotsBody.listenersAll.click[0]({ target });
    assert(els.promptDetail.open && els.promptDetailText.textContent === context.imageRun.shots[0].enhanced_prompt, 'the detailed text opens safely without disturbing the editor');
    assert(!els.promptDetailYours.hidden, 'your own prompt a tap away');
    els.promptDetailYours.getAttribute = () => 'false';
    els.promptDetailYours.listeners.click();
    assert.strictEqual(els.promptDetailText.textContent, 'b', 'it shows what you wrote');
    run("showPromptDetail('detailed')");
    assert(run('shotsDirty') && els.shotsDialog.open, 'opening preserves unsaved edits and the editor');
    let copied = '';
    context.navigator = { clipboard: { writeText: async text => { copied = text; } } };
    await els.promptDetailCopy.listeners.click();
    assert.strictEqual(copied, context.imageRun.shots[0].enhanced_prompt, 'copy retains exact text');
    assert.strictEqual(els.promptDetailCopy.innerHTML, run('ICONS.check'), 'copy shows feedback');
    els.promptDetailClose.listeners.click();
    assert(!els.promptDetail.open && els.shotsDialog.open && run('shotsDirty'), 'closing returns to the same editor');
    await els.shotsBody.listenersAll.click[0]({ target });
    assert.strictEqual(els.promptDetailCopy.innerHTML, run('ICONS.copy'), 'reopening resets copy feedback');
    let appended, message = '';
    context.navigator = {};
    context.document.createElement = () => ({ style: {}, setAttribute() {}, select() {}, remove() {} });
    els.promptDetail.appendChild = el => { appended = el; };
    context.document.execCommand = () => true;
    await els.promptDetailCopy.listeners.click();
    assert.strictEqual(appended.value, context.imageRun.shots[0].enhanced_prompt, 'HTTP fallback copies from the topmost dialog');
    context.document.execCommand = () => false;
    context.alert = text => { message = text; };
    await els.promptDetailCopy.listeners.click();
    assert.strictEqual(message, 'Could not copy it.', 'copy errors are surfaced');
    els.promptDetailClose.listeners.click();
    delete context.imageRun.shots[0].enhanced_prompt;
    context.navigator = savedNavigator; context.document.createElement = savedCreateElement;
    context.document.execCommand = savedExec; context.alert = savedAlert;
    run('shotsDirty = false');
    els.shotsDialog.open = false;
  }
  run("imageSets = []; lastVideos = {output: [], uploaded: [], video: []}; pipeline = 'image'; nsfwView = true; document.body.dataset.page = 'status'; showPage('output')");
  assert.strictEqual(run('nsfwView'), false, 'entering Output resets even the NSFW view');
  run("nsfwView = true; showPage('output')");
  assert.strictEqual(run('nsfwView'), true, 'remaining on Output preserves the chosen view');
  run("nsfwView = false; showPage('status')");
  {
    const savedFetch = context.fetch, savedPoll = run('poll');
    let calls = [];
    context.fetch = async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => ({ ok: true }) };
    };
    run('poll = () => {}');
    for (const [kind, nsfw] of [['image', true], ['video', false]]) {
      const button = { dataset: {}, innerHTML: 'dots', style: {}, disabled: false, classList: classes(),
        getBoundingClientRect: () => ({ width: 34, height: 28 }) };
      button.classList.add('icon-btn');
      context.nsfwButtonTest = button;
      context.nsfwKind = kind;
      context.nsfwValue = nsfw;
      const previous = calls.length;
      await run("tagOutput(nsfwKind, 'item', nsfwValue, nsfwButtonTest)");
      assert.strictEqual(calls.length, previous, 'first tap only arms the NSFW action');
      assert(button.classList.contains('armed') && button.innerHTML.includes('<svg'), 'first tap shows confirmation');
      await run("tagOutput(nsfwKind, 'item', nsfwValue, nsfwButtonTest)");
      assert.strictEqual(calls.length, previous + 1, 'second tap sends the action');
      assert.deepStrictEqual(calls[previous], { url: '/api/output/nsfw', body: { kind, id: 'item', nsfw } });
      assert(!button.classList.contains('armed') && button.innerHTML === 'dots', 'the button is restored');
    }
    assert.strictEqual(run("nsfwButton('image', 'a', false).match(/<svg[\\s\\S]*<\\/svg>/)[0]"),
      run("nsfwButton('image', 'a', true).match(/<svg[\\s\\S]*<\\/svg>/)[0]"), 'the icon is neutral and the same in both states');
    context.fetch = savedFetch;
    context.savedNsfwPoll = savedPoll;
    run('poll = savedNsfwPoll');
  }
  {
    const savedPoll = run('poll');
    const savedFetch = context.fetch;
    const savedClasses = els.viewerDelete.classList;
    els.viewerDelete.classList = classes();
    run('poll = () => {}');
    const image = (position, title) => ({ position, title, version: title });
    const prepare = () => {
      context.deleteSet = { id: 'image_delete', label: 'Batch', total: 3, size: '1x1', when: '', images: [
        image(1, 'First'), image(2, 'Second'), image(3, 'Third')] };
      run("imageSets = [deleteSet]; nsfwView = false; pipeline = 'image'");
    };
    const remove = async (position, remaining) => {
      context.fetch = async url => {
        assert.strictEqual(url, `/image-runs/image_delete/delete/${position}`);
        return { json: async () => ({ ok: true, images: remaining }) };
      };
      await els.viewerDelete.listeners.click();
      await els.viewerDelete.listeners.click();
    };
    prepare();
    run("openViewer('image_delete', 2)");
    await remove(2, [image(1, 'First'), image(2, 'Third')]);
    assert(els.imageViewer.open && els.viewerTitle.textContent === 'Third' && els.viewerCount.textContent === '2 of 2', 'deletion opens the renumbered next image');
    assert(els.viewerDownload.href.includes('/files/2?v=Third'), 'download points to the surviving image');
    await remove(2, [image(1, 'First')]);
    assert(els.imageViewer.open && els.viewerTitle.textContent === 'First', 'deleting the last visible image opens the previous one');
    await remove(1, []);
    assert(!els.imageViewer.open, 'deleting the only remaining image closes the preview');
    prepare();
    run("openViewer('image_delete', 1)");
    let finishDelete;
    context.fetch = () => new Promise(resolve => { finishDelete = resolve; });
    await els.viewerDelete.listeners.click();
    const pendingDelete = els.viewerDelete.listeners.click();
    assert(els.viewerDelete.disabled, 'deletion cannot be submitted twice while in flight');
    run('stepViewer(1)');
    finishDelete({ json: async () => ({ ok: true, images: [image(1, 'Second'), image(2, 'Third')] }) });
    await pendingDelete;
    assert(els.imageViewer.open && els.viewerTitle.textContent === 'Second' && els.viewerCount.textContent === '1 of 2', 'navigation during deletion keeps the selected image after renumbering');
    let error = '';
    const savedAlert = context.alert;
    context.alert = text => { error = text; };
    context.fetch = async () => ({ json: async () => ({ ok: false, error: 'Run is busy' }) });
    await els.viewerDelete.listeners.click();
    await els.viewerDelete.listeners.click();
    assert(els.imageViewer.open && els.viewerTitle.textContent === 'Second' && els.viewerCount.textContent === '1 of 2' && error === 'Run is busy', 'a failed deletion leaves the preview intact and reports the error');
    context.alert = savedAlert;
    context.fetch = savedFetch;
    context.savedPoll = savedPoll;
    run('poll = savedPoll; closeViewer(); imageSets = []');
    els.viewerDelete.classList = savedClasses;
  }
  const feedback = context.feedback = { innerHTML: 'Add to queue', textContent: '', disabled: false,
    classList: classes(), attrs: {}, getAttribute(name) { return this.attrs[name] ?? null; },
    setAttribute(name, value) { this.attrs[name] = value; }, removeAttribute(name) { delete this.attrs[name]; } };
  let finishRequest;
  context.feedbackRequest = () => new Promise(resolve => { finishRequest = resolve; });
  const feedbackResult = run('queueRequest(feedback, feedbackRequest)');
  assert(feedback.disabled && feedback.textContent === 'Adding…' && feedback.attrs['aria-busy'] === 'true');
  context.setTimeout = fn => { fn(); return 0; };
  finishRequest({ ok: true, queued: true });
  assert((await feedbackResult).ok && !feedback.disabled && feedback.innerHTML === 'Add to queue', 'feedback restores the button after success');
  run("setPipeline('image', false); showPage('generate')");
  let promptEvents = 0;
  els.imagePrompt.dispatchEvent = event => { if (event.type === 'input' && event.bubbles) promptEvents++; };
  els.imagePrompt.value = 'a lighthouse';
  els.imageCount.value = '4';
  let prevented = false, stopped = false;
  els.clearImagePrompt.listeners.click({ preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } });
  assert(prevented && stopped && els.imagePrompt.value === '' && els.imageCount.value === '4' && promptEvents === 1, 'clear affects only the prompt and updates the form without toggling its heading');
  els.imagePrompt.value = 'variant';
  run("showPage('generate')");
  assert.strictEqual(els.imagePrompt.value, 'variant', 'remaining on Generate preserves a prompt');
  run("showPage('output')");
  assert.strictEqual(els.imagePrompt.value, 'variant', 'leaving Generate keeps its prompt');
  els.imagePrompt.value = 'another variant';
  run("setPipeline('video', false)");
  assert.strictEqual(els.imagePrompt.value, '', 'switching sides clears the old prompt');
  els.prompt.value = 'video prompt';
  run("setPipeline('video', false)");
  assert.strictEqual(els.prompt.value, 'video prompt', 'selecting the same side keeps its prompt');
  run("setPipeline('shorts', false); showPage('generate')");
  els.topic.value = 'short topic';
  run("showPage('status')");
  assert.strictEqual(els.topic.value, 'short topic', 'leaving Generate on Shorts keeps its topic');
  const savedJumps = run('JUMPS.slice()');
  const jump = hash => ({ hash, classList: classes() });
  context.testJumps = [jump('#runCard'), jump('#optionsCard'), jump('#videosCard')];
  run('JUMPS.splice(0, JUMPS.length, ...testJumps)');
  let desktopTop = { runCard: -500, optionsCard: 0, videosCard: 500 };
  for (const id of Object.keys(desktopTop)) context.document.getElementById(id).getBoundingClientRect = () => ({ top: desktopTop[id], bottom: desktopTop[id] + 300 });
  wide.matches = true;
  run('markJump()');
  els.topic.value = 'desktop topic';
  desktopTop = { runCard: -900, optionsCard: -500, videosCard: 0 };
  run('markJump()');
  assert.strictEqual(els.topic.value, 'desktop topic', 'scrolling away from Generate on desktop keeps the prompt');
  wide.matches = false;
  context.savedJumps = savedJumps;
  run('JUMPS.splice(0, JUMPS.length, ...savedJumps); desktopGenerateActive = false');
  const savedFetch = context.fetch;
  run('var pickerRefreshPlan = refreshPlan; refreshPlan = async () => {}');
  context.File = class { constructor(chunks, name, options) { this.name = name; this.type = options.type; } };
  context.DataTransfer = class { constructor() { this.files = []; this.items = { add: file => this.files.push(file) }; } };
  context.fetch = async url => String(url).includes('/files/')
    ? { ok: true, blob: async () => ({ type: 'image/png' }) }
    : { ok: true, json: async () => ({ ok: true, shots: [{ used_seed: 123 }] }) };
  run("imageSets = []; nsfwView = false; setPipeline('video', false); showPage('generate'); imagesShown = 2; syncImageInput()");
  els.prompt.value = 'keep this video prompt';
  boxes[1].parts.select.value = 'place';
  run("outputKind = 'both'; chooseFromOutput(imageBoxes()[1], \"video\")");
  assert(run('pipeline') === 'video' && run('outputKind') === 'image', 'Generate stays on its side; Output shows images only');
  assert.strictEqual(context.document.body.dataset.page, 'output');
  assert.strictEqual(els.prompt.value, 'keep this video prompt');
  await run("chooseThis('a set', 1)");
  assert(run('pipeline') === 'video' && run('outputKind') === 'both', 'back, Output as it was');
  assert.strictEqual(context.document.body.dataset.page, 'generate');
  assert.strictEqual(boxes[1].parts.input.files[0].name, 'image_1.png');
  assert.strictEqual(boxes[1].parts.select.value, 'place');
  assert.strictEqual(boxes[1].parts.select.disabled, false);
  assert.strictEqual(els.prompt.value, 'keep this video prompt');
  const pickButton = { dataset: { pick: '1' }, closest: () => boxes[0] };
  els.imageBoxes.listeners.click({ target: { closest: () => pickButton } });
  assert(run('choosingFor') && run('outputKind') === 'image', 'the image box gallery control opens the picker');
  els.chooseCancel.listeners.click();
  assert.strictEqual(run('pipeline'), 'video');
  assert.strictEqual(els.prompt.value, 'keep this video prompt', 'cancelling preserves the originating form');
  const previous = boxes[0].parts.input.files[0];
  context.fetch = async () => ({ ok: false });
  run('chooseFromOutput(imageBoxes()[0], "video")');
  await run("chooseThis('missing', 1)");
  assert.strictEqual(boxes[0].parts.input.files[0], previous, 'a failed download leaves the existing image alone');
  assert(els.formError.textContent.includes('Could not fetch'), 'a failed download is visible');
  context.fetch = async url => String(url).includes('/files/')
    ? { ok: true, blob: async () => ({ type: 'image/png' }) }
    : { ok: true, json: async () => ({ ok: true, shots: [{ used_seed: 123 }] }) };
  const source = imageBox(1), seed = { value: '' };
  const sourceQuery = source.querySelector;
  source.querySelector = selector => selector === '.source-seed' ? seed : sourceQuery(selector);
  els.imageSources.querySelectorAll = () => [source];
  run("setPipeline('image', false); showPage('generate')");
  els.imagePrompt.value = 'keep this image prompt';
  run('chooseFromOutput(sourceBoxes()[0])');
  await run("chooseThis('set', 1)");
  assert.strictEqual(source.parts.input.files[0].name, 'image_1.png');
  assert.strictEqual(seed.value, '123', 'image edits keep the selected output seed');
  assert.strictEqual(els.imagePrompt.value, 'keep this image prompt');
  const source2 = imageBox(2), seed2 = { value: '' }, source2Query = source2.querySelector;
  source2.querySelector = selector => selector === '.source-seed' ? seed2 : source2Query(selector);
  els.imageSources.querySelectorAll = () => [source, source2];
  run(`imageWorkflows = { multi: { min_images: 1, max_images: 2, options: [] },
    text: { min_images: 0, max_images: 0, options: [{ id: 'image_to_prompt', takes: { min_images: 1, max_images: 1 } }] } };
    $('imageWorkflow').value = 'multi'; sourcesShown = 2; syncImageSources()`);
  assert(!source.hidden && !source2.hidden && !source2.parts.input.disabled, 'a multi-image workflow exposes both image boxes');
  run('chooseFromOutput(sourceBoxes()[1])');
  await run("chooseThis('set', 1)");
  assert.strictEqual(source2.parts.input.files[0].name, 'image_1.png', 'a second image workflow input accepts output');
  assert.strictEqual(seed2.value, '123');
  run(`$('imageWorkflow').value = 'text'; $('imagePromptMode').value = 'llm'; $('imageLlm').value = 'image_to_prompt'; syncImageSources()`);
  assert(!source.hidden && source2.hidden, 'image-to-prompt exposes its image even when the base workflow takes none');
  run('chooseFromOutput(sourceBoxes()[0])');
  assert.strictEqual(run('choosingFor.side'), 'image', 'image-to-prompt can use the picker');
  els.chooseCancel.listeners.click();
  run(`imageWorkflows = {}; $('imageWorkflow').value = ''; $('imageLlm').value = ''; sourcesShown = 1`);
  els.imageSources.querySelectorAll = () => [source];
  let releaseImage;
  context.fetch = () => new Promise(resolve => { releaseImage = resolve; });
  run('chooseFromOutput(sourceBoxes()[0])');
  const pendingImage = run("chooseThis('set', 1)");
  source.parts.input.disabled = true;
  releaseImage({ ok: true, blob: async () => ({ type: 'image/png' }) });
  context.fetch = async () => ({ ok: true, json: async () => ({ ok: true, shots: [{ used_seed: 123 }] }) });
  await pendingImage;
  assert(els.formError.textContent.includes('box changed'), 'a disabled box does not receive a late selection');
  source.parts.input.disabled = false;
  els.imageSources.querySelectorAll = () => [];
  run("setPipeline('video', false); showPage('generate'); JUMPS.splice(0, JUMPS.length, ...testJumps)");
  els.prompt.value = 'desktop video prompt';
  els.videosCard.scrollIntoView = els.optionsCard.scrollIntoView = () => {};
  wide.matches = true;
  desktopTop = { runCard: -500, optionsCard: 0, videosCard: 500 };
  run('markJump(); chooseFromOutput(imageBoxes()[0], "video")');
  desktopTop = { runCard: -900, optionsCard: -500, videosCard: 0 };
  run('markJump()');
  els.chooseCancel.listeners.click();
  desktopTop = { runCard: -500, optionsCard: 0, videosCard: 500 };
  run('markJump()');
  assert.strictEqual(els.prompt.value, 'desktop video prompt', 'desktop picker navigation preserves the prompt');
  wide.matches = false;
  run('JUMPS.splice(0, JUMPS.length, ...savedJumps); desktopGenerateActive = false');
  context.fetch = savedFetch;
  run('refreshPlan = pickerRefreshPlan');
  for (const id of ['stop', 'skip']) {
    const button = els[id];
    button.classList = classes();
    button.innerHTML = id === 'stop' ? 'Stop' : 'Cancel';
    button.attrs = {};
    button.getAttribute = name => button.attrs[name] ?? null;
    button.setAttribute = (name, value) => { button.attrs[name] = value; };
    button.removeAttribute = name => { delete button.attrs[name]; };
  }
  const requests = [];
  context.confirm = () => { throw new Error('run actions must not show a confirmation popup'); };
  context.fetch = async url => { requests.push(url); return { json: async () => ({ ok: true }) }; };
  run('var originalPoll = poll; poll = async () => {}');
  context.setTimeout = () => 0;
  await els.skip.listeners.click();
  assert(els.skip.classList.contains('armed') && requests.length === 0, 'first cancel tap only arms it');
  await els.stop.listeners.click();
  assert(!els.skip.classList.contains('armed') && els.stop.classList.contains('armed'), 'switching action cancels the previous confirmation');
  context.setTimeout = fn => { fn(); return 0; };
  await els.stop.listeners.click();
  assert.deepStrictEqual(requests, ['/stop'], 'second stop tap sends the stop request');
  context.setTimeout = () => 0;
  await els.skip.listeners.click();
  assert.strictEqual(requests.length, 1, 'first cancel tap does not stop the run');
  context.setTimeout = fn => { fn(); return 0; };
  await els.skip.listeners.click();
  assert.deepStrictEqual(requests, ['/stop', '/skip'], 'second cancel tap sends the cancel request');
  run('poll = originalPoll');
  context.confirm = () => true;
  assert.strictEqual(run(`queueDetail({detail: 'film · renders straight away', facts: {resolution: '1280x736'}})`), 'film · 1280x736');
  run(`var oldViewer = openViewer, oldFilm = openFilm, oldClosePanel = closePanel, oldGoOutput = goToOutput;
    var navigated = []; openViewer = (id, position) => navigated.push(['image', id, position]);
    openFilm = name => navigated.push(['film', name]); closePanel = () => {};
    goToOutput = (side, tab) => navigated.push(['output', side, tab]);
    imageSets = [{id:'image_1', images:[{position: 1}, {position: 2}]}];
    lastVideos = { video:[{name:'film.mp4', run:'run_1'}], output:[], uploaded:[] }`);
  const clickResult = dataset => els.finishedList.listeners.click({ target: { closest: sel => (sel === '[data-goto]' ? { dataset } : null) } });
  clickResult({ goto: 'image', runId: 'image_1', position: '2' });
  clickResult({ goto: 'video', runId: 'run_1' });
  assert.deepStrictEqual(JSON.parse(run('JSON.stringify(navigated)')), [['image', 'image_1', 2], ['output', 'video', null], ['film', 'film.mp4']]);
  const failedRow = { dataset: {runId: 'image_1'}, classList: classes(), scrollIntoView() { this.scrolled = true; } };
  const failedFold = { open: false };
  els.failedRuns.querySelector = () => failedFold;
  els.failedRuns.querySelectorAll = () => [failedRow];
  context.setTimeout = () => 0;
  clickResult({ goto: 'image', runId: 'image_1', failed: '1' });
  assert(failedFold.open && failedRow.scrolled && failedRow.classList.contains('highlight'), 'failed result opens and highlights its saved entry, not its preview');
  assert.strictEqual(run('navigated.length'), 3);
  failedRow.dataset = {jobId: '7'};
  failedRow.classList.remove('highlight');
  clickResult({ goto: 'image', jobId: '7', failed: '1' });
  assert(failedRow.classList.contains('highlight'), 'a failure without a saved run still highlights its Failed entry');
  run('openViewer = oldViewer; openFilm = oldFilm; closePanel = oldClosePanel; goToOutput = oldGoOutput');
  context.setTimeout = fn => { fn(); return 0; };
  // A queued SeedVR2 upscale, edited in the viewer's own box: 3x and a denoise go as the viewer sends them.
  run(`queueUpscaleEdit = { id: 8, token: 'edit-token', kind: 'image_upscale', size: [640, 368] }; upscaleMethod = 'seedvr2'`);
  for (const id of ['viewerUpscaleSize', 'viewerUpscaleDenoise', 'viewerUpscaleStrength', 'upscaleCancel', 'upscaleGo']) context.document.getElementById(id);
  els.viewerUpscaleSize.value = 'x3';
  els.viewerUpscaleDenoise.value = '0.1';
  els.viewerUpscaleStrength.value = '1';
  let savedUpscale;
  context.fetch = async (url, options) => {
    savedUpscale = { url, body: JSON.parse(options.body) };
    return { json: async () => ({ ok: true }) };
  };
  await run('saveQueueUpscale')(feedback);
  assert.strictEqual(savedUpscale.url, '/queue/run/edit/8/upscale');
  assert.deepStrictEqual([savedUpscale.body.method, savedUpscale.body.times, savedUpscale.body.denoise, savedUpscale.body.token], ['seedvr2', '3', '0.1', 'edit-token']);
  assert.strictEqual(run('queueUpscaleEdit'), null, 'saving closes the queued upscale editor');
  context.setTimeout = () => 0;
  const quiet = { ...idle, lines: [], queue: { items: [], results: [], held: false, current: null }, stopped_runs: [], videos: { output: [], uploaded: [], video: [] },
    comfyui: { online: true }, quota: { groups: [], resets_in: 100 }, gpu: null, upload: { lines: [], running: false, elapsed: 0, queue: { items: [], results: [], held: false, current: null } } };
  // Status for the polls; the workflow lists ComfyUI coming online has the page fetch again, as the server has them.
  const answer = (body, extra = {}) => async url => ({ json: async () => (String(url).startsWith('/api/workflows') ? { online: true, workflows: [] } : body),
    redirected: false, ...extra });

  // Polls started above with stub timers never time out, as a browser's would after POLL_TIMEOUT: start afresh.
  run('polling = false; pollAgain = false; workflowsFor = true');  // And ComfyUI already seen online, so no lists to fetch
  // A poll that never answers is given up on, and the next one still gets through.
  // As a browser's: one given up on fails, even if that was before it was sent.
  context.fetch = (url, options) => new Promise((_, reject) => {
    if (options.signal.aborted) reject(new Error('aborted'));
    options.signal.addEventListener('abort', () => reject(new Error('aborted')));
  });
  context.setTimeout = fn => { fn(); return 0; };
  await run('poll()');
  context.setTimeout = () => 0;
  context.fetch = answer({ ...quiet, server_started: 1, returncode: 0 });
  await run('poll()');
  assert.strictEqual(els.statusText.textContent, 'Idle', 'it works again straight after a stuck one, and a finished run leaves it idle');
  assert.strictEqual(els.go.textContent, 'Generate');
  context.fetch = answer({ ...quiet, server_started: 1, queue: { ...quiet.queue, items: [{ id: 1, label: 'x', estimate: 60 }] } });
  await run('poll()');
  assert.strictEqual(els.go.textContent, 'Add to queue');
  assert.strictEqual(els.goStick.textContent, 'Add to queue');
  // Paused with nothing running, it starts at once.
  context.fetch = answer({ ...quiet, server_started: 1, queue: { ...quiet.queue, held: true, items: [{ id: 1, label: 'x', estimate: 60 }] } });
  await run('poll()');
  assert.strictEqual(els.go.textContent, 'Generate');
  assert.strictEqual(els.goStick.textContent, 'Generate');

  // Signed out: the page goes to the login rather than sit there stale.
  context.fetch = answer({}, { redirected: true });
  await run('poll()');
  assert.strictEqual(context.reloads, 1);

  // Asked again while one is still out, as Resume does: one at a time, and the answer after it is the one shown.
  let release;
  context.fetch = url => String(url).startsWith('/api/workflows') ? answer({})(url)
    : new Promise(resolve => { release = () => resolve({ json: async () => ({ ...quiet, server_started: 1 }), redirected: false }); });
  const first = run('poll()');
  run('poll()');  // Waits for the first instead of making it count for nothing
  context.fetch = answer({ ...quiet, server_started: 1, running: true, started_at: '13:12:59', elapsed: 3, pipeline: 'shorts', progress: {} });
  release();
  await first;
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert(!els.statusTimes.hidden, 'the poll asked for while one was out runs after it, and is shown');
  assert.strictEqual(els.statusStarted.textContent, '13:12');
  assert.strictEqual(els.statusDuration.textContent, run('fmt(3)'), 'running duration is shown separately');
  assert.strictEqual(els.statusText.textContent, '', 'running label is not displayed');
  run('wasRunning = false');  // Or the next idle answer reads as that run ending, and asks the stub for an estimate

  // A restored tab must not wait for a request whose timeout was suspended in the background.
  let releaseOld, oldSignal;
  context.fetch = (url, options) => {
    oldSignal = options.signal;
    return new Promise(resolve => { releaseOld = resolve; });
  };
  const stale = run('poll()');
  context.fetch = answer({ ...quiet, server_started: 1, running: true, started_at: '13:12', elapsed: 3, pipeline: 'shorts', progress: {} });
  windowListeners.focus.forEach(fn => fn());
  await new Promise(resolve => setImmediate(resolve));
  assert(oldSignal.aborted, 'focus aborts the old status request');
  assert(!els.statusTimes.hidden, 'focus starts a fresh status request immediately');
  releaseOld({ redirected: false, json: async () => ({ ...quiet, server_started: 1 }) });
  await stale;
  assert(!els.statusTimes.hidden, 'a late stale response cannot overwrite the fresh status');
  run('wasRunning = false');
  assert(windowListeners.pageshow.length && windowListeners.online.length && documentListeners.visibilitychange.length, 'restored, reconnected and visible tabs refresh');

  // A new server means new code, unless that would lose what is being typed: a prompt is kept for the tab as it is
  // typed, so only one set without being kept (or a narration) holds the reload off.
  for (const id of ['prompt', 'imagePrompt', 'narration']) context.document.getElementById(id).value = '';
  context.reloads = 0;
  const tabStore = {};
  context.sessionStorage = { getItem: key => (key in tabStore ? tabStore[key] : null), setItem: (key, value) => { tabStore[key] = String(value); } };
  context.document.getElementById('narration').value = 'Half written';
  context.fetch = answer({ ...quiet, server_started: 2 });
  await run('poll()');
  assert.strictEqual(context.reloads, 0, 'a narration being written is not lost');
  context.document.getElementById('narration').value = '';
  context.document.getElementById('topic').value = 'Half typed';
  await run('poll()');
  assert.strictEqual(context.reloads, 1, 'a deferred reload happens once editing is no longer in progress');
  assert.strictEqual(run('keptPrompts().shorts'), 'Half typed', 'and a prompt is kept for the tab, to come back after it');

  // Reopening an output brings back the settings it was made with, its prompt model included.
  run(`pipeline = 'video'; loadVideoWorkflows = async () => { $('llm').value = 'gemini'; }; syncVideoForm = () => {};
       syncSize = () => {}; syncImageInput = () => {}; syncMediaInput = () => {};
       syncPromptWriter = () => {}; saveVideoForm = () => {}; applyOptions = () => {};
       showFormError = () => {}; showPage = () => {}; reopened = () => {}`);
  context.document.getElementById('llm').value = 'local';
  els.llm.options = [{ value: 'local' }, { value: 'gemini' }];
  els.videoWorkflow.options = [];
  context.fetch = async () => ({ json: async () => ({ ok: true, settings: {
    prompt: 'old', llm: 'gemini', start: 'image', size: '864x480', seconds: 10,
    images: 0, references: [], options: {}, track: false
  } }) });
  await run("sameAgainFilm('old')");
  assert.strictEqual(els.llm.value, 'gemini', 'reopening a film restores the prompt model it was made with');
  run(`pipeline = 'image'; loadImageWorkflows = async () => { $('imageLlm').value = 'gemini'; }; syncImageForm = () => {};
       syncImageSources = () => {}; saveImageForm = () => {}; imageTakes = () => ({ options: [] })`);
  els.imageLlm.value = 'local';
  els.imageLlm.options = [{ value: 'local' }, { value: 'gemini' }];
  els.imageWorkflow.options = [];
  context.fetch = async () => ({ json: async () => ({ ok: true, shots: [], settings: {
    prompt: 'old', llm: 'gemini', size: '1024x1024', count: 1, inputs: 0, options: {}
  } }) });
  await run("sameAgain('old')");
  assert.strictEqual(els.imageLlm.value, 'gemini', 'reopening images restores the prompt model they were made with');

  // A shot's seed: its icon opens the seed dialog; Save writes it back for saving and rendering again.
  {
    ['seedDialog', 'seedDialogSave', 'seedDialogError', 'seedDialogValue'].forEach(id => context.document.getElementById(id));
    Object.assign(els.seedDialog, { showModal() { this.open = true; }, close() { this.open = false; } });
    context.document.getElementById('seed_1').value = '';
    const classes = new Set(), button = { dataset: { seedOpen: '1', what: 'shot' }, title: '', setAttribute() {},
      classList: { toggle: (c, on) => on ? classes.add(c) : classes.delete(c) } };
    run('shotsDirty = false');
    context.seedIcon = button;
    run('openSeedDialog(seedIcon)');
    assert(els.seedDialog.open && !els.seedDialogSave.hidden, 'the seed dialog opens with Save');
    els.seedDialogValue.value = 'abc';
    run('saveSeedDialog()');
    assert(els.seedDialog.open && !els.seedDialogError.hidden, 'a seed that is not a number is refused');
    els.seedDialogValue.value = '1234';
    run('saveSeedDialog()');
    assert.strictEqual(els.seed_1.value, '1234', 'Save writes the seed back');
    assert(run('shotsDirty') && classes.has('pinned') && !els.seedDialog.open, 'marked as changed, its icon lit');
  }

  // A Generate seed shows in Other options: shuffle picks one to keep, ✕ goes back to random.
  {
    const field = context.document.getElementById('videoSeed'), sent = [];
    Object.assign(field, { value: '', dispatchEvent: e => sent.push(e.type) });
    for (const fn of documentListeners.click) fn({ target: { closest: sel => sel.includes('data-seed-pick') ? { dataset: { seedPick: 'videoSeed' } } : null } });
    assert(/^\d+$/.test(String(field.value)) && sent.includes('change'), 'shuffle picks a seed to keep');
    for (const fn of documentListeners.click) fn({ target: { closest: sel => sel.includes('data-seed-pick') ? { dataset: { seedClear: 'videoSeed' } } : null } });
    assert.strictEqual(field.value, '', '✕ goes back to random');
  }

  // The prompt editor: two lines on the page, all of it in the editor; Cancel keeps what was there, Save writes it back.
  {
    const field = els.prompt, events = [];
    const lookup = context.document.querySelector;
    context.document.querySelector = selector => selector === 'label[for="prompt"]' ? { textContent: 'Prompt' } : lookup ? lookup(selector) : null;
    Object.assign(field, { value: 'old idea', readOnly: false, disabled: false, placeholder: '', maxLength: -1,
      closest: () => null, dispatchEvent: e => events.push(e.type) });
    Object.assign(els.promptEditorText, { focus() {}, setSelectionRange() {} });
    Object.assign(els.promptEditor, { showModal() { this.open = true; }, close() { this.open = false; } });
    run("openPromptEditor($('prompt'))");
    assert.strictEqual(els.promptEditorText.value, 'old idea', 'the editor opens with the whole prompt');
    assert(!els.promptEditorEnhance.hidden && !els.promptEditorSave.hidden, 'the video prompt can be saved, or written by the LLM');
    els.promptEditorText.value = 'new idea';
    run('closePromptEditor(false)');
    assert.strictEqual(field.value, 'old idea', 'Cancel keeps the prompt as it was');
    assert(!events.length, 'and tells nothing it changed');
    run("openPromptEditor($('prompt'))");
    els.promptEditorText.value = 'new idea';
    run('closePromptEditor(true)');
    assert.strictEqual(field.value, 'new idea', 'Save writes the prompt back');
    assert(events.includes('input') && events.includes('change'), 'as if typed, so the estimate and saved form hear of it');
    // The LLM writes in the editor, the same in the prompts view: its prompt waits in the box for Save.
    {
      const shotBox = { value: 'a shot idea', readOnly: false, disabled: false, placeholder: '', maxLength: -1, getAttribute: () => 'Prompt for shot 1',
        closest: sel => sel === '#shotsBody' ? {} : null, dispatchEvent() {}, classList: { toggle() {} } };
      context.shotBox = shotBox;
      run('shotsRun = { is_image: false, shots: [] }');
      run('openPromptEditor(shotBox)');
      assert(!els.promptEditorEnhance.hidden, 'the prompts view has the LLM button too');
      const savedFetch = context.fetch;
      context.fetch = async (url, options) => ({ ok: true, json: async () => options ? { ok: true, prompt: 'A full prompt' } : { ok: true, seconds: 30, model: 'm' } });
      await run('enhanceInEditor()');
      assert.strictEqual(els.promptEditorText.value, 'A full prompt', 'what it writes goes in the editor');
      assert.strictEqual(shotBox.value, 'a shot idea', 'and the prompt stays as it was until Save');
      run('closePromptEditor(true)');
      assert.strictEqual(shotBox.value, 'A full prompt', 'Save keeps it');
      context.fetch = savedFetch;
    }
    field.readOnly = true;
    run("openPromptEditor($('prompt'))");
    assert(els.promptEditorSave.hidden && els.promptEditorEnhance.hidden && els.promptEditorText.readOnly, 'a locked prompt can be read and copied, not changed');
    run('closePromptEditor(false)');
    field.readOnly = false;
  }

  console.log('all page checks passed');
})().catch(e => { console.error(e); process.exit(1); });

// Reopened from something made or a queued job, a form is its own: the starred preset isn't put over it, and the picker
// isn't left naming the preset picked before.
for (const fn of ['sameAgain', 'sameAgainFilm', 'sameAgainShorts', 'editQueued', 'openEditor']) {
  const body = script.slice(script.indexOf(`async function ${fn}(`), script.indexOf('\n}\n', script.indexOf(`async function ${fn}(`)));
  assert(/reopening\(/.test(body) && body.indexOf('reopening(') < body.indexOf('Workflows()'), `${fn}: the default preset stays off it`);
  assert(/reopened\(/.test(body), `${fn}: the preset picker is checked against the form`);
}

// With an upscale on, the stepper sets where it ends and the size it's made at follows: a quarter of the pixels, within
// what the upscale starts from on a 12 GB card.
{
  els.imageUpscaleBox.hidden = false;
  els.imageUpscaleBox.limits = { UltraSharp: { base: 2, final: 16 } };
  els.imageUpscale.disabled = false;
  els.imageUpscale.value = 'UltraSharp';
  els.imageAspect.value = '16:9';
  run('sourceSize = null');
  els.imageUpscaleMp.value = '4';
  run('syncMegapixels()');
  // Resolution shows the size it is made at, Upscale the size it ends at.
  const made = els.imagePixelSize.textContent.split('×').map(Number), ends = els.imageUpscaleSize.textContent.split('×').map(Number);
  assert(Math.abs(made[0] * made[1] - 1048576) < 0.08e6, `made at a quarter: ${els.imagePixelSize.textContent}`);
  assert(Math.abs(ends[0] * ends[1] - 4 * 1048576) < 0.2e6, `ends where the stepper says: ${els.imageUpscaleSize.textContent}`);
  assert.strictEqual(els.imageMegapixels.value, '1.00', 'the size it is made at is what goes');
  els.imageUpscaleMp.value = '14';
  run('syncMegapixels()');
  assert.strictEqual(els.imageMegapixels.value, '2.00', 'held to the 2 MP the upscale starts from');
  els.imageUpscaleMp.value = '40';
  run('syncMegapixels()');
  assert.strictEqual(els.imageUpscaleMp.value, '16.0', 'and held to where it may end');
  assert(!els.imageResNote.hidden && /run out of memory/.test(els.imageResNote.textContent), 'saying why');
  els.imageAspect.value = '3840x2160';
  els.imageUpscaleMp.value = '';
  run('syncMegapixels()');
  assert.strictEqual(els.imageUpscaleSize.textContent, '3840×2160', 'a screen picked is where it ends');
  const madeAt = els.imagePixelSize.textContent;
  // Upscale off: back to the size it was being made at, in its shape.
  els.imageUpscale.value = 'Off';
  els.imageUpscale.listeners.change();
  assert.strictEqual(els.imagePixelSize.textContent, madeAt, `dropped back to what it was made at: ${els.imagePixelSize.textContent}`);
  const twice = madeAt.split('×').map(side => side * 2).join('×');
  assert.strictEqual(els.imageUpscaleSize.innerHTML, `<span class="would-tag">2×</span>${twice}`, 'and what 2× would come to, marked 2×, in its place');
  assert(/2× upscale would make/.test(els.imageUpscaleSize.title), 'said to be only a would-be');
  // Video's latent upscale shows the same: its end when on, a marked 2× when off.
  run("showVideoStepper(0.4, 0.1, 2, [832, 480], null, '', false)");
  assert.strictEqual(els.videoLatentSize.innerHTML, '<span class="would-tag">2×</span>1664×960', 'video, off: what 2× would come to');
  run("showVideoStepper(1.6, 0.1, 2, [832, 480], [1664, 960], '', true)");
  assert.strictEqual(els.videoLatentSize.textContent, '1664×960', 'video, on: where it ends');
  assert.strictEqual(els.videoLatentSize.title, '', 'and no longer a would-be');
  els.imageUpscaleBox.hidden = true;
  els.imageAspect.value = '1:1';
  run('imageStep = null');
}

// Without an upscale, the stepper steps the resolution: a number, never NaN.
{
  els.imageUpscaleBox.hidden = true;
  els.imageAspect.value = '16:9';
  els.imageMegapixels.value = 'image';
  run('imageStep = null; sourceSize = null; syncMegapixels()');
  run('stepMegapixels(MP_STEP)');
  assert.strictEqual(run('imageStep'), 1.1, 'one step up from 1 MP');
  assert(!/NaN/.test(els.imageMegapixelsValue.innerHTML) && !/NaN/.test(els.imagePixelSize.textContent), `no NaN: ${els.imageMegapixelsValue.innerHTML}`);
  run('stepMegapixels(-MP_STEP); stepMegapixels(-MP_STEP)');
  assert.strictEqual(run('imageStep'), 0.9);
  run('imageStep = null');
}

// A model's own default size on coming to it; a screen above its limit is made at its shape within it.
{
  els.imageUpscaleBox.hidden = true;
  els.imageAspect.value = '1:1';
  els.imageMegapixels.value = 'image';
  const steps = JSON.parse(run(`(() => {
    const was = imageTakes, found = {};
    sourceSize = null; imageStep = null; imageDefaulted = false; imageLeastModel = null;
    $('imageMegapixels').value = 'image'; $('imageMegapixels').dataset.sent = 'image';
    imageTakes = () => ({ model: 'krea2', size: true, options: [] }); syncImageSize();
    for (const model of ['moss_image', 'qwen_image_edit', 'minimax_h3_image', 'krea2', 'fibo2']) { imageTakes = () => ({ model, size: true, options: [] }); syncImageSize(); found[model] = imageStep; }
    imageTakes = () => ({ model: 'fibo2', options: [] }); $('imageAspect').value = '1272x2772'; imageStep = null;
    const r = imageResolution(), mp = r.sides[0] * r.sides[1] / MEGAPIXEL;
    imageStep = 0.9; const stepped = imageResolution().note; imageStep = null;
    imageTakes = () => ({ model: 'minimax_h3_image', options: [] }); $('imageAspect').value = '1080x2400';
    const low = imageResolution(); const lowNote = low.note, lowSend = low.send;
    $('imageAspect').value = '1:1'; const plain = imageResolution().note;
    imageTakes = () => ({ model: 'moss_image', options: [] }); $('imageAspect').value = '1272x2772'; imageLeastModel = null; startAtLeast(imageModel()); found.screen = imageStep;
    imageTakes = was; $('imageAspect').value = '1:1'; imageStep = null; imageDefaulted = false;
    return JSON.stringify({ ...found, stepped, lowNote, lowSend, plain, send: r.send, mp, note: r.note, ratio: r.sides[0] / r.sides[1] });
  })()`));
  assert.deepStrictEqual([steps.moss_image, steps.qwen_image_edit, steps.minimax_h3_image], [2, 1, 16], 'each model starts at its own default');
  assert.deepStrictEqual([steps.krea2, steps.fibo2], [null, null], 'one with none goes back to the size as picked');
  assert(steps.mp <= 1.1 && steps.send === '1.1' && steps.note === 'Rescaled to 1.1 MP' && Math.abs(steps.ratio - 1272 / 2772) < 0.02, `a phone past the limit is made at its shape within it, and says so: ${JSON.stringify(steps)}`);
  assert.strictEqual(steps.stepped, '', 'stepping it clears the note');
  assert.strictEqual(steps.lowNote, 'Rescaled to 4.0 MP', 'a preset under the least is raised to it');
  assert.strictEqual(steps.lowSend, '4.0');
  assert.strictEqual(steps.plain, '', 'an aspect ratio has nothing to say');
  assert.strictEqual(steps.screen, null, 'a screen is not stepped to the default');
}

// Typed with Upscale on: the box is the size it is made at, and where it ends follows it (four times the pixels).
{
  els.imageUpscaleBox.hidden = false;
  els.imageUpscaleBox.limits = { 'Ultimate SD': { base: 2, final: 16 } };
  els.imageUpscale.disabled = false;
  els.imageUpscale.value = 'Ultimate SD';
  els.imageAspect.value = 'custom';
  els.imageSize.value = '784x1392';
  els.imageUpscaleMp.value = '';
  run('syncMegapixels()');
  assert.strictEqual(els.imagePixelSize.textContent, '784×1392', 'made at the size typed');
  const [ew, eh] = els.imageUpscaleSize.textContent.split('×').map(Number);
  assert(Math.abs(ew / 784 - 2) < 0.05 && Math.abs(eh / 1392 - 2) < 0.05, `ends twice as big each way: ${els.imageUpscaleSize.textContent}`);
  run('stepMegapixels(MP_STEP)');
  assert.notStrictEqual(els.imageSize.value, '784x1392', 'stepping the end moves the size it is made at, in the box');
  assert.strictEqual(els.imageSize.value, els.imagePixelSize.textContent.replace('×', 'x'));
  els.imageUpscaleBox.hidden = true;
  els.imageUpscale.value = 'Off';
  els.imageAspect.value = '1:1';
  run('imageStep = null; imageMadeAt = null');
}

// Upscale starts off on each page load, whatever was chosen last time; its box is as dark as the queue's.
assert(/was = first \? 'Off' : \$\('imageUpscale'\)\.value/.test(script) && /was = first \? 'Off' : \$\('videoLatentUpscale'\)\.value/.test(script), 'upscale defaults to off');
assert(/\.res-block \{[^}]*background: var\(--bg\)/.test(html), 'the block is dark like the queue');

// Only what goes with the upscale chosen shows: SeedVR2's factor and denoise; a hidden row stays hidden.
assert(/\.pipeline-form \.option-row\[hidden\] \{ display: none; \}/.test(html), 'a hidden option row is hidden');
{
  els.imageUpscaleBox.hidden = false;
  els.imageUpscale.disabled = false;
  els.imageUpscaleBox.limits = { SeedVR2: { base: 4, final: 8.3, shorter: 2160 }, 'Ultimate SD': { base: 2, final: 16 } };
  for (const [method, denoise, factor] of [['Off', true, true], ['UltraSharp', true, true], ['SeedVR2', false, false]]) {
    els.imageUpscale.value = method;
    run('showImageUpscale()');
    assert.strictEqual(els.imageUpscaleDenoiseRow.hidden, denoise, `${method}: denoise`);
    assert.strictEqual(els.imageUpscaleFactorRow.hidden, factor, `${method}: factor`);
  }
  // SeedVR2 at 3x: made at a ninth of the pixels it ends with.
  els.imageAspect.value = '1:1';
  els.imageUpscaleFactor.value = '3';
  els.imageUpscaleMp.value = '4.5';
  run('sourceSize = null; syncMegapixels()');
  const made = els.imagePixelSize.textContent.split('×').map(Number), ends = els.imageUpscaleSize.textContent.split('×').map(Number);
  assert(Math.abs(ends[0] / made[0] - 3) < 0.1, `three times each way: ${els.imagePixelSize.textContent} → ${els.imageUpscaleSize.textContent}`);
  els.imageUpscaleBox.hidden = true;
  els.imageUpscale.value = 'Off';
  els.imageUpscaleFactor.value = '2';
  run('imageStep = null; imageMadeAt = null');
}

// A typed size, stepped without an upscale (as after turning one off): the box follows the stepper.
{
  els.imageUpscaleBox.hidden = true;
  els.imageUpscale.value = 'Off';
  els.imageAspect.value = 'custom';
  els.imageSize.value = '784x1392';
  run('imageStep = null; imageMadeAt = null; syncImageSize()');
  run('stepMegapixels(MP_STEP)');
  assert.notStrictEqual(els.imageSize.value, '784x1392', 'the box moves with the stepper');
  assert.strictEqual(els.imageSize.value, els.imagePixelSize.textContent.replace('×', 'x'), 'and agrees with Resolution');
  assert.strictEqual(els.imageMegapixels.value, 'image', 'the box goes as it is');
  const once = els.imageSize.value;
  run('stepMegapixels(MP_STEP)');
  assert.notStrictEqual(els.imageSize.value, once, 'and keeps moving');
  els.imageAspect.value = '1:1';
}

// Upscale on starts from the resolution there is now, not where an earlier upscale ended; off drops back to it.
{
  els.imageUpscaleBox.hidden = false;
  els.imageUpscaleBox.limits = { UltraSharp: { base: 2, final: 16 } };
  els.imageUpscale.disabled = false;
  els.imageAspect.value = 'custom';
  els.imageSize.value = '784x1392';
  els.imageUpscale.value = 'Off';
  els.imageUpscaleMp.value = '9.0';  // left from an earlier upscale
  run("imageStep = null; imageMadeAt = null; imageUpscaleWas = 'Off'; syncImageSize()");
  els.imageUpscale.value = 'UltraSharp';
  els.imageUpscale.listeners.change();
  assert.strictEqual(els.imageSize.value, '784x1392', `the box keeps the resolution it had: ${els.imageSize.value}`);
  assert.strictEqual(els.imagePixelSize.textContent, '784×1392');
  const ends = els.imageUpscaleSize.textContent.split('×').map(Number);
  assert(Math.abs(ends[0] / 784 - 2) < 0.05, `ends twice as big each way: ${els.imageUpscaleSize.textContent}`);
  els.imageUpscale.value = 'Off';
  els.imageUpscale.listeners.change();
  assert.strictEqual(els.imageSize.value, '784x1392', 'and off drops back to it');
  run('stepMegapixels(MP_STEP)');
  assert.notStrictEqual(els.imageSize.value, '784x1392', 'where the stepper moves it again');
  els.imageUpscaleBox.hidden = true;
  els.imageAspect.value = '1:1';
  run("imageStep = null; imageMadeAt = null");
}

// Switching to Exact size: the box takes the size it was being made at, so nothing jumps.
{
  els.imageUpscaleBox.hidden = true;
  els.imageUpscale.value = 'Off';
  els.imageAspect.value = '16:9';
  els.imageSize.value = '111x222';
  run('imageStep = null; sourceSize = null; syncImageSize()');
  const shown = els.imagePixelSize.textContent;
  els.imageAspect.value = 'custom';
  for (const fn of els.imageAspect.listenersAll.change || []) fn({ target: els.imageAspect });
  run('syncImageSize()');
  assert.strictEqual(els.imageSize.value, shown.replace('×', 'x'), `the box starts at the size there was: ${els.imageSize.value}`);
  assert.strictEqual(els.imagePixelSize.textContent, shown);
  els.imageAspect.value = '1:1';
}

// From a workflow without latent upscale back to one with it: its presets are there again, not only Off.
{
  const withIt = [{ id: 'latent_upscale', kind: 'choice', choices: ['Off', 'Clean', 'Hires fix', 'Heavy', 'Custom'], default: 'Off' },
    { id: 'latent_upscale_mp', kind: 'number', min: 0.5, max: 4, default: '1' }];
  run("workflowH3 = { 'r2v.json': true, 'director.json': true }; workflowMultishot = { 'r2v.json': true }; workflowDirector = { 'director.json': true }");
  els.start.hidden = false;
  els.start.value = 'image';
  els.videoLatentUpscale.innerHTML = '';
  els.videoLatentBox.dataset.key = '';
  for (const [workflow, options] of [['r2v.json', withIt], ['director.json', []], ['r2v.json', withIt]]) {
    els.videoWorkflow.value = workflow;
    context.latentOptions = options;
    run('syncVideoLatent(latentOptions)');
  }
  assert(/Hires fix/.test(els.videoLatentUpscale.innerHTML), `presets back: ${els.videoLatentUpscale.innerHTML}`);
  assert(!els.videoLatentUpscale.disabled, 'and it can be picked');
  run("workflowH3 = {}; workflowMultishot = {}; workflowDirector = {}");
  els.videoWorkflow.value = '';
}

// Picking a preset starts again: the prompt goes with the old one. None leaves it.
{
  els.imagePrompt.value = 'kept until a preset is picked';
  els.imagePreset.value = '';
  els.imagePreset.listeners.change({ target: els.imagePreset });
  assert.strictEqual(els.imagePrompt.value, 'kept until a preset is picked', 'None keeps it');
  run("presets.image = [{ name: 'Portrait', values: {} }]; var realApplyPreset = applyPreset; applyPreset = () => {}");
  els.imagePreset.value = 'Portrait';
  els.imagePreset.listeners.change({ target: els.imagePreset });
  assert.strictEqual(els.imagePrompt.value, '', 'a preset picked clears it');
  run('presets.image = []; applyPreset = realApplyPreset');
}

// Latent upscale may end past what the workflow makes a clip at: memory, pixels times frames, is what holds it.
{
  run("workflowClips = { 'r2v.json': [3, 10, 5] }");
  els.videoWorkflow.value = 'r2v.json';
  els.videoClipSeconds.value = '3-5';
  assert.strictEqual(run('latentTop(960 * 544)'), 1.5, '5 s clips: half again the known fit, spread over 5 s');
  els.videoClipSeconds.value = '3-10';
  assert.strictEqual(run('latentTop(960 * 544)'), 0.7, '10 s clips: less');
  els.videoClipSeconds.value = '3-3';
  assert.strictEqual(run('latentTop(960 * 544)'), 2.6);
  run("workflowClips = { 'r2v.json': [1, 30, 5] }");
  els.videoClipSeconds.value = '1-1';
  assert.strictEqual(run('latentTop(960 * 544)'), 4, 'never past the 4 MP the upscaler takes');
  run('workflowClips = {}');
  els.videoClipSeconds.value = '';
  els.videoWorkflow.value = '';
}
