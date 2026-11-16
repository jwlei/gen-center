const fs = require('fs');
const assert = require('assert');
const vm = require('vm');

// The page as Flask rendered it, which loads settings.js; the theme picker's part of that script runs on a stub DOM.
const html = fs.readFileSync(process.argv[2], 'utf8');
assert(/<script(?: defer)? src="\/static\/settings\.js/.test(html), 'the page loads settings.js');
const source = fs.readFileSync(require('path').join(__dirname, '..', 'panel', 'static', 'settings.js'), 'utf8');
const script = source.slice(source.indexOf("const settingsDialog = $('settingsDialog');"), source.indexOf('function formatBytes(n)'));
assert(script.includes('function syncTheme()'));
function element() {
  return {
    dataset: {}, style: {}, listeners: {},
    addEventListener(name, fn) { this.listeners[name] = fn; },
    setAttribute(name, value) { this[name] = value; },
    showModal() { this.open = true; }, close() { this.open = false; },
  };
}
const choices = ['standard', 'nord'].map(id => {
  const choice = element();
  choice.dataset.theme = id;
  choice.querySelector = () => ({ textContent: id === 'nord' ? 'Nord' : 'Standard' });
  return choice;
});
const els = Object.fromEntries(['settingsDialog', 'settingsNote', 'themeDialog', 'themeNote', 'themePicker', 'themeClose'].map(id => [id, element()]));
els.themeDialog.querySelectorAll = () => choices;
const context = { SETTINGS: { theme: 'standard' }, $: id => els[id], document: { documentElement: { dataset: {} } } };
vm.createContext(context);
vm.runInContext(script, context);

(async () => {
  assert.strictEqual(els.themePicker.textContent, 'Standard');
  els.themePicker.listeners.click();
  assert(els.themeDialog.open);
  context.fetch = async () => ({ json: async () => ({ ok: false, error: 'save failed' }) });
  await els.themeDialog.listeners.click({ target: { closest: () => choices[1] } });
  assert.strictEqual(context.document.documentElement.dataset.theme, 'standard');
  assert.strictEqual(els.themeNote.textContent, 'save failed');
  assert(els.themeDialog.open && !choices[1].disabled);
  context.fetch = async () => ({ json: async () => ({ ok: true, settings: { theme: 'nord' } }) });
  await els.themeDialog.listeners.click({ target: { closest: () => choices[1] } });
  assert.strictEqual(context.document.documentElement.dataset.theme, 'nord');
  assert.strictEqual(els.themePicker.textContent, 'Nord');
  assert.strictEqual(choices[1]['aria-pressed'], 'true');
  assert(!els.themeDialog.open);
})().catch(error => { console.error(error); process.exitCode = 1; });
