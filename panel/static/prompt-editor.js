// --- The prompt editor: a prompt box shows two lines, and a tap opens all of it here to change, copy, save or drop ---
let promptField = null, promptEditorEnhanced = false, promptEditorOriginal = null, promptEditorModel = null, promptWriting = null;
const promptEditorWriterSelected = { image: null, video: null };
let promptThinkingTimer = null, promptThinkingIndex = -1;
const PROMPT_THOUGHTS = ['Prompting…', 'Thinking…', 'Shaping the details…', 'Finding the right words…', 'Polishing…'];
function promptSide(field) {
  if (!field) return null;
  const generate = Object.entries(PROMPT_FIELDS).find(([side, id]) => side !== 'shorts' && $(id) === field);
  if (generate) return generate[0];
  if (field.closest && field.closest('#shotsBody') && shotsRun) return shotsRun.is_image ? 'image' : 'video';
  return null;
}
function promptLabel(field) {
  const label = field.id && document.querySelector(`label[for="${field.id}"]`);
  return (label && label.textContent.trim()) || field.getAttribute('aria-label') || 'Prompt';
}
// A box with more than two lines fades out at the bottom, so it is plain there is more.
function syncPromptBox(field) {
  if (field && field.classList) field.classList.toggle('more', field.scrollHeight > field.clientHeight + 2);
}
// The box being edited: the one prompt, or the page shown of a run's generated prompts.
let generatedEdit = null;
function promptPage() {
  const pages = $('promptEditorPages');
  return Math.min(generatedEdit ? generatedEdit.shots.length - 1 : 0, Math.max(0, Math.round(pages.scrollLeft / Math.max(pages.clientWidth, 1))));
}
function editorText() {
  return generatedEdit ? $('promptEditorPages').querySelectorAll('textarea')[promptPage()] : $('promptEditorText');
}
function countPrompt() {
  const text = editorText().value, words = text.trim() ? text.trim().split(/\s+/).length : 0;
  if (!generatedEdit) {
    $('promptEditorCount').textContent = `${words} ${words === 1 ? 'word' : 'words'} · ${text.length} characters`;
    return;
  }
  const where = generatedEdit.shots.length > 1 ? `${promptPage() + 1} of ${generatedEdit.shots.length} · ` : '';
  $('promptEditorCount').textContent = `${where}${words} ${words === 1 ? 'word' : 'words'}`;
  $('promptEditorPrev').disabled = promptPage() === 0;
  $('promptEditorNext').disabled = promptPage() === generatedEdit.shots.length - 1;
}
// A queued run's generated prompts, one to a page: swipe, the arrows, or Ctrl+arrow keys turn them.
async function openGeneratedPrompts() {
  const epoch = workspaceEpoch;
  const run = queueEdit && queueEdit.continued;
  if (!run) return;
  let data;
  try {
    data = await (await fetch(runUrl(run.id))).json();
  } catch (e) {
    data = { error: 'Could not reach the panel. Try again.' };
  }
  if (epoch !== workspaceEpoch) return;
  if (!data.ok) { alert(data.error || 'Could not open the generated prompts.'); return; }
  generatedEdit = { id: data.id, shots: data.shots, dirty: false };
  promptField = null;
  promptWriting = null;
  const pages = $('promptEditorPages');
  pages.innerHTML = data.shots.map((shot, i) => `<div class="prompt-page">
    <div class="prompt-page-title">${esc(shot.title || `${data.is_image ? 'Image' : 'Shot'} ${i + 1}`)}</div>
    <textarea spellcheck="true" aria-label="Prompt ${i + 1}">${esc(shot.prompt || '')}</textarea></div>`).join('');
  $('promptEditorText').hidden = true;
  pages.hidden = false;
  $('promptEditorTurn').hidden = data.shots.length < 2;
  $('promptEditorTitle').textContent = 'Generated prompts';
  $('promptEditorSave').hidden = $('promptEditorClear').hidden = false;
  $('promptEditorEnhance').hidden = true;
  $('promptEditorReset').hidden = true;
  closePromptWriterMenu();
  $('promptEditorCancel').textContent = 'Cancel';
  setPromptEditorBusy(false);
  $('promptEditor').showModal();
  fitPromptEditor();
  pages.scrollLeft = 0;
  countPrompt();
}
function turnPrompt(by) {
  const pages = $('promptEditorPages');
  pages.scrollTo({ left: (promptPage() + by) * pages.clientWidth });
}
$('promptEditorPrev').addEventListener('click', () => turnPrompt(-1));
$('promptEditorNext').addEventListener('click', () => turnPrompt(1));
$('promptEditorPages').addEventListener('scroll', countPrompt, { passive: true });
$('promptEditorPages').addEventListener('input', () => { if (generatedEdit) { generatedEdit.dirty = true; countPrompt(); } });
$('promptEditorPages').addEventListener('keydown', e => {
  if (!generatedEdit || !(e.ctrlKey || e.metaKey) || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
  e.preventDefault();
  turnPrompt(e.key === 'ArrowRight' ? 1 : -1);
});
function closeGeneratedPrompts() {
  generatedEdit = null;
  $('promptEditorPages').hidden = true;
  $('promptEditorPages').innerHTML = '';
  $('promptEditorText').hidden = false;
  $('promptEditorTurn').hidden = true;
  $('promptEditor').close();
}
async function saveGeneratedPrompts() {
  const edit = generatedEdit;
  if (!edit) return;
  if (!edit.dirty) { closeGeneratedPrompts(); return; }
  const prompts = [...$('promptEditorPages').querySelectorAll('textarea')].map(t => t.value);
  if (prompts.some(prompt => !prompt.trim())) { $('promptEditorCount').textContent = 'Every prompt needs some text.'; return; }
  // Their seeds go back as they are: without them, every one would be random.
  const seeds = edit.shots.map(shot => shot.seed == null ? null : String(shot.seed));
  $('promptEditorSave').disabled = true;
  let data;
  try {
    data = await (await fetch(`${runUrl(edit.id)}/shots`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompts, seeds }),
    })).json();
  } catch (e) {
    data = { error: 'Could not reach the panel. Try again.' };
  }
  $('promptEditorSave').disabled = false;
  if (generatedEdit !== edit) return;
  if (!data.ok) { $('promptEditorCount').textContent = data.error || 'Could not save the prompts.'; return; }
  if (queueEdit && queueEdit.continued) queueEdit.continued.prompts = prompts;
  closeGeneratedPrompts();
}
document.addEventListener('click', e => {
  if (e.target && e.target.closest && e.target.closest('[data-generated-prompts]')) openGeneratedPrompts();
});
// Sized to what the keyboard leaves visible, so Save and Cancel stay above it on a phone.
function fitPromptEditor() {
  const view = window.visualViewport, box = $('promptEditor');
  if (!box.open || !view) return;
  box.style.top = `${Math.round(view.offsetTop + 8)}px`;
  box.style.height = `${Math.round(view.height - 16)}px`;
}
function openPromptEditor(field) {
  // While an LLM writes into it, the box is busy: it opens when the writing is done.
  if (!field || field.disabled || field.closest('.prompt-writing.busy')) return;
  promptField = field;
  promptEditorEnhanced = false;
  promptEditorOriginal = null;
  promptEditorModel = null;
  promptWriting = null;
  const locked = field.readOnly, text = $('promptEditorText');
  $('promptEditorTitle').textContent = promptLabel(field);
  text.value = field.value;
  text.readOnly = locked;
  text.placeholder = field.placeholder || '';
  text.maxLength = field.maxLength > 0 ? field.maxLength : 100000;
  $('promptEditorSave').hidden = locked;
  setPromptEditorBusy(false);
  // The Video and Image prompts can be written from the idea in them, from here as from beside the box.
  const side = promptSide(field);
  $('promptEditorEnhance').hidden = locked || !side;
  syncPromptWriterHighlight(side);
  $('promptEditorReset').hidden = true;
  closePromptWriterMenu();
  $('promptEditorClear').hidden = locked;
  $('promptEditorCancel').textContent = locked ? 'Close' : 'Cancel';
  countPrompt();
  $('promptEditor').showModal();
  fitPromptEditor();
  if (!locked) {
    text.focus();
    text.setSelectionRange(text.value.length, text.value.length);
  }
}
function closePromptEditor(save) {
  const field = promptField;
  promptWriting = null;  // A reply still on its way is dropped
  setPromptEditorBusy(false);
  const side = promptSide(field);
  if (save && promptEditorEnhanced && side && field === $(PROMPT_FIELDS[side])) {
    $(side + 'PromptWriterModel').value = promptEditorModel || '';
    const model = $(side + 'LocalModel');
    if (promptEditorModel && [...model.options].some(option => option.value === promptEditorModel)) model.value = promptEditorModel;
    SIDE_SAVE[side]();
  }
  // Generate's image prompt, written by the LLM, is used word for word from then on, as the prompt writer always did.
  if (save && promptEditorEnhanced && field === $(PROMPT_FIELDS.image)) {
    const mode = $('imagePromptMode');
    if (!mode.disabled && mode.value !== 'direct') { mode.value = 'direct'; mode.dispatchEvent(new Event('change', { bubbles: true })); }
  }
  if (save && field && !field.readOnly && field.value !== $('promptEditorText').value) {
    field.value = $('promptEditorText').value;
    // As if typed, so everything that listens to the box (the estimate, presets, saved forms) hears of it.
    field.dispatchEvent(new Event('input', { bubbles: true }));
    field.dispatchEvent(new Event('change', { bubbles: true }));
  }
  promptField = null;
  $('promptEditor').close();
  syncPromptBox(field);
}
document.addEventListener('click', e => {
  const field = e.target && e.target.closest && e.target.closest('textarea[data-prompt]');
  if (field) openPromptEditor(field);
});
// A prompt box isn't typed in: a key, Enter or a paste opens the editor instead. Tab still moves on.
document.addEventListener('keydown', e => {
  const field = e.target && e.target.matches && e.target.matches('textarea[data-prompt]') ? e.target : null;
  if (!field || e.key === 'Tab' || e.key === 'Shift' || e.ctrlKey && e.key === 'c' || e.metaKey && e.key === 'c') return;
  e.preventDefault();
  openPromptEditor(field);
});
document.addEventListener('paste', e => {
  if (e.target && e.target.matches && e.target.matches('textarea[data-prompt]')) { e.preventDefault(); openPromptEditor(e.target); }
});
document.addEventListener('input', e => { if (e.target && e.target.matches && e.target.matches('textarea[data-prompt]')) syncPromptBox(e.target); });
$('promptEditorText').addEventListener('input', countPrompt);
function closePromptWriterMenu() {
  const menu = $('promptEditorWriterMenu');
  if (!menu) return;
  menu.hidden = true;
  $('promptEditorEnhance').setAttribute('aria-expanded', 'false');
}
function promptWriterKey(writer) { return `${writer.id}:${writer.model || ''}`; }
function syncPromptWriterHighlight(side) {
  $('promptEditorWriterWrap').classList.toggle('has-selection', !!(side && promptEditorWriterSelected[side]));
}
function promptWriterChoices(side) {
  const select = $(side === 'image' ? 'imageLlm' : 'llm');
  const enabled = value => [...select.options].some(option => option.value === value && !option.disabled);
  const choices = [];
  if (enabled('gemini')) choices.push({ id: 'gemini', label: 'Gemini' });
  if (enabled('local')) choices.push(...LOCAL_MODELS.map(model => ({
    id: 'local', model: model.id, label: localModelLabel(model), title: model.label,
  })));
  if (side === 'image' && enabled('prompt_enhancer')) choices.push({ id: 'prompt_enhancer', label: 'Prompt enhancer' });
  return choices;
}
async function openPromptWriterMenu() {
  const epoch = workspaceEpoch;
  const side = promptSide(promptField);
  if (!side) return;
  if (side === 'image') await loadImageWorkflows();
  try { await refreshLocalModels(); } catch (e) { $('promptEditorCount').textContent = e.message || 'Could not load local models.'; return; }
  if (epoch !== workspaceEpoch) return;
  const menu = $('promptEditorWriterMenu');
  const writers = promptWriterChoices(side);
  const selected = promptEditorWriterSelected[side];
  syncPromptWriterHighlight(side);
  const viewportTop = window.visualViewport ? window.visualViewport.offsetTop : 0;
  menu.style.maxHeight = `${Math.max(0, Math.min(198, $('promptEditorEnhance').getBoundingClientRect().top - viewportTop - 8))}px`;
  menu.innerHTML = writers.map(writer => {
    const active = selected === promptWriterKey(writer);
    return `<button type="button" role="menuitemradio" aria-checked="${active}" class="${active ? 'selected' : ''}" data-writer="${writer.id}"${writer.model ? ` data-model="${esc(writer.model)}"` : ''}${writer.title ? ` title="${esc(writer.title)}"` : ''}>${esc(writer.label)}</button>`;
  }).join('');
  menu.hidden = false;
  $('promptEditorEnhance').setAttribute('aria-expanded', 'true');
}
$('promptEditorEnhance').addEventListener('click', () => {
  if (!$('promptEditorWriterMenu').hidden) { closePromptWriterMenu(); return; }
  openPromptWriterMenu();
});
// Do not move focus off the textarea until a writer is chosen: the mobile keyboard stays put.
for (const id of ['promptEditorEnhance', 'promptEditorWriterMenu']) $(id).addEventListener('pointerdown', e => {
  const writerButton = e.target && e.target.closest && e.target.closest('[data-writer]');
  if (document.activeElement === $('promptEditorText') && (id !== 'promptEditorWriterMenu' || (writerButton && e.pointerType !== 'touch'))) e.preventDefault();
});
$('promptEditorWriterMenu').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('[data-writer]');
  if (!button) return;
  const writer = { id: button.dataset.writer, model: button.dataset.model || null };
  const side = promptSide(promptField);
  if (side) promptEditorWriterSelected[side] = promptWriterKey(writer);
  syncPromptWriterHighlight(side);
  closePromptWriterMenu();
  $('promptEditorText').blur();
  enhanceInEditor(writer);
});
document.addEventListener('click', e => {
  if (!$('promptEditorWriterMenu').hidden && !e.target.closest('.prompt-writer-wrap')) closePromptWriterMenu();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('promptEditorWriterMenu').hidden) {
    e.preventDefault();
    e.stopPropagation();
    closePromptWriterMenu();
    $('promptEditorEnhance').focus();
  }
});
$('promptEditorReset').addEventListener('click', () => {
  if (promptEditorOriginal === null) return;
  $('promptEditorText').value = promptEditorOriginal;
  promptEditorOriginal = null;
  promptEditorEnhanced = false;
  $('promptEditorReset').hidden = true;
  countPrompt();
  $('promptEditorText').focus();
});
// Ctrl or Cmd + Enter saves, as in most editors.
$('promptEditorText').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !$('promptEditorSave').hidden) { e.preventDefault(); closePromptEditor(true); }
});
$('promptEditorSave').addEventListener('click', () => generatedEdit ? saveGeneratedPrompts() : closePromptEditor(true));
// Clear empties the editor only: Save keeps it empty, Cancel brings the prompt back.
$('promptEditorClear').addEventListener('click', () => {
  const text = editorText();
  text.value = '';
  if (generatedEdit) generatedEdit.dirty = true;
  countPrompt();
  text.focus();
});
// The selected writer fills this box, wherever the editor is opened: its prompt waits here for Save or Cancel.
function setPromptEditorBusy(busy) {
  $('promptEditorText').readOnly = busy || !!(promptField && promptField.readOnly);
  for (const id of ['promptEditorEnhance', 'promptEditorReset', 'promptEditorClear', 'promptEditorSave']) $(id).disabled = busy;
  $('promptEditorTitle').hidden = busy;
  $('promptEditorReset').hidden = busy || promptEditorOriginal === null;
  if (busy) closePromptWriterMenu();
  $('promptEditorEnhance').classList.toggle('working', busy);
  $('promptEditorEnhance').setAttribute('aria-busy', String(busy));
  syncPromptThinking(busy);
  const bar = $('promptEditorProgress');
  bar.hidden = !busy;
  if (!busy) bar.style.width = '0%';
}
function setPromptThinkingPhrase(phrase) {
  const previous = $('promptEditorThinkingPrevious'), current = $('promptEditorThinkingCurrent');
  previous.textContent = current.textContent;
  previous.className = 'prompt-thinking-line';
  if (previous.textContent) {
    void previous.offsetWidth;
    previous.className = 'prompt-thinking-line exiting';
  }
  current.innerHTML = [...phrase].map((letter, index) =>
    `<span class="prompt-thinking-letter" style="animation-delay:${Math.min(index * 16, 320)}ms">${letter === ' ' ? '&nbsp;' : esc(letter)}</span>`).join('');
  current.className = 'prompt-thinking-line';
  void current.offsetWidth;
  current.className = 'prompt-thinking-line entering';
}
function syncPromptThinking(busy) {
  const box = $('promptEditorThinking');
  if (promptThinkingTimer !== null) {
    clearInterval(promptThinkingTimer);
    promptThinkingTimer = null;
  }
  if (!busy) {
    box.hidden = true;
    $('promptEditorThinkingPrevious').textContent = '';
    $('promptEditorThinkingCurrent').textContent = '';
    return;
  }
  box.hidden = false;
  promptThinkingIndex = -1;
  const advance = () => {
    promptThinkingIndex = (promptThinkingIndex + 1) % PROMPT_THOUGHTS.length;
    setPromptThinkingPhrase(PROMPT_THOUGHTS[promptThinkingIndex]);
  };
  advance();
  promptThinkingTimer = setInterval(advance, 2200);
}
async function enhanceInEditor(writer) {
  const side = promptSide(promptField), text = $('promptEditorText'), idea = text.value;
  if (!side || !writer) return;
  if (!idea.trim()) { $('promptEditorCount').textContent = 'Enter an idea first.'; return; }
  const originalBeforeRun = promptEditorOriginal;
  if (promptEditorOriginal === null) promptEditorOriginal = idea;
  const writing = promptWriting = {};
  setPromptEditorBusy(true);
  $('promptEditorCount').textContent = 'Estimating…';
  let timer;
  try {
    const model = writer.model ? `&model=${encodeURIComponent(writer.model)}` : '';
    const estimateResponse = await fetch(`/api/write-prompt?pipeline=${encodeURIComponent(side)}&writer=${encodeURIComponent(writer.id)}${model}`);
    const estimate = await estimateResponse.json();
    if (promptWriting !== writing) return;
    if (!estimateResponse.ok || !estimate.ok || !Number.isFinite(estimate.seconds) || estimate.seconds <= 0) throw new Error(estimate.error || 'Could not estimate prompt writing.');
    const start = performance.now();
    const update = () => {
      if (promptWriting !== writing) return;
      const elapsed = (performance.now() - start) / 1000, remaining = estimate.seconds - elapsed;
      // Up to 95% on the estimate: the last of it is when the prompt is in.
      $('promptEditorProgress').style.width = `${Math.min(95, Math.max(0, elapsed / estimate.seconds * 100))}%`;
      const speed = writer.id === 'local' ? promptWriterSpeed() : '';
      $('promptEditorCount').textContent = ['Writing', speed, remaining > 0 ? `${fmtEta(remaining)} left` : 'taking longer than estimated'].filter(Boolean).join(' · ');
    };
    update();
    timer = setInterval(update, 1000);
    const form = new FormData($(side === 'image' ? 'formImage' : 'formVideo'));
    form.set('pipeline', side);
    form.set('prompt', idea);
    form.set('writer', writer.id);
    if (writer.model) form.set('model', writer.model);
    const response = await fetch('/api/write-prompt', { method: 'POST', body: form });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Could not write the prompt.');
    if (promptWriting !== writing) return;  // Closed or written again meanwhile
    text.value = result.prompt;
    promptEditorEnhanced = true;
    promptEditorModel = writer.id === 'local' ? writer.model : null;
    countPrompt();
  } catch (e) {
    if (promptWriting === writing) {
      $('promptEditorCount').textContent = e.message || 'Could not write the prompt.';
      if (!promptEditorEnhanced && originalBeforeRun === null) {
        promptEditorOriginal = null;
        $('promptEditorReset').hidden = true;
      }
    }
  } finally {
    clearInterval(timer);
    if (promptWriting === writing) { promptWriting = null; setPromptEditorBusy(false); }
  }
}
$('promptEditorCancel').addEventListener('click', () => {
  if (!generatedEdit) { closePromptEditor(false); return; }
  if (generatedEdit.dirty && !confirm('Close without saving your changes to the prompts?')) return;
  closeGeneratedPrompts();
});
// Escape drops nothing typed: with changes, it asks for Save or Cancel instead of closing.
$('promptEditor').addEventListener('cancel', e => {
  if (generatedEdit) {
    e.preventDefault();
    if (generatedEdit.dirty) $('promptEditorCount').textContent = 'Unsaved changes: Save or Cancel.';
    else closeGeneratedPrompts();
    return;
  }
  if (promptField && !promptField.readOnly && promptField.value !== $('promptEditorText').value) {
    e.preventDefault();
    $('promptEditorCount').textContent = 'Unsaved changes: Save or Cancel.';
  } else closePromptEditor(false);
});
$('promptEditorCopy').addEventListener('click', async () => {
  const text = editorText(), button = $('promptEditorCopy');
  try { await navigator.clipboard.writeText(text.value); } catch (e) {
    text.select();
    try { document.execCommand('copy'); } catch (e2) {}
  }
  button.classList.add('copied');
  button.setAttribute('aria-label', 'Copied');
  button.title = 'Copied';
  setTimeout(() => { button.classList.remove('copied'); button.setAttribute('aria-label', 'Copy'); button.title = 'Copy'; }, 1500);
});
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', fitPromptEditor);
  window.visualViewport.addEventListener('scroll', fitPromptEditor);
}
