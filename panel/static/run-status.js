// --- What is happening right now ---
const STAGES = { shorts: ['Topic & script', 'Voice', 'Stock footage', 'Avatar clips', 'Rendering scenes', 'Stitching', 'Upload'], video: PANEL_CONFIG.stages, image: PANEL_CONFIG.image_stages };
const SIDE_NAMES = { shorts: 'Shorts', video: 'Video', image: 'Image' };
const SIDE_FORMS = { shorts: 'formShorts', video: 'formVideo', image: 'formImage' };
const STAGE_HINTS = {
  'Plan': 'The LLM is writing each shot.',
  'Clips': 'ComfyUI is rendering each clip.',
  'Prompts': 'The LLM is writing a prompt per image.',
  'Topic & script': 'Gemini is writing the scenes.',
  'Voice': 'Gemini is reading the script.',
  'Stock footage': 'Downloading stock clips.',
  'Avatar clips': 'Picking her scenes, then ComfyUI renders each clip.',
  'Rendering scenes': 'Combining footage and voice.',
  'Stitching': 'Joining the scenes.',
  'Upload': 'Uploading to YouTube.',
};
function fmt(sec) {
  sec = Math.max(0, sec | 0);
  const m = Math.floor(sec / 60), s = sec % 60;
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(s).padStart(2, '0')}`;
}
// An estimate, so rounded: exact seconds would promise more than it knows.
function fmtEta(sec) {
  if (sec < 60) return `~${Math.max(5, Math.round(sec / 5) * 5)}s`;
  const m = Math.round(sec / 60);
  return m >= 60 ? `~${Math.floor(m / 60)}h ${m % 60}m` : `~${m} min`;
}
function stepEta(step) {
  if (!step) return '';
  if (step.state === 'kept') return 'kept';
  if (step.state === 'done') return fmt(step.seconds);
  if (step.state === 'next') return fmtEta(step.seconds);
  return step.seconds > 0 ? `${fmtEta(step.seconds)} left` : 'any moment';
}
// Every time on the page is 24-hour, 00:00 to 23:59, whatever the device's locale says.
function clock24(date) {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}
function clockIn(sec) {
  return clock24(new Date(Date.now() + sec * 1000));
}
// What moved the ETA, with its effect: '+6 min', or nothing for a change that costs no time.
function etaChange(change) {
  const sign = change.seconds > 0 ? '+' : '-';
  const effect = change.seconds ? `${sign}${fmtEta(Math.abs(change.seconds)).slice(1)} · ` : '';
  return `<div>${effect}${esc(change.text)}</div>`;
}
// How far the estimate has moved from the first one, as "+2 min" or "-1 min"; nothing under half a minute.
function etaShift(eta) {
  const moved = eta ? eta.adjusted_total - eta.original_total : 0;
  return eta && (eta.changes || []).length && Math.abs(moved) >= 30 ? `${moved > 0 ? '+' : '-'}${fmtEta(Math.abs(moved)).slice(1)}` : '';
}
// The time left says how far it moved, "(+2 min)" after it; a tap on it shows the first estimate, and why, under it.
let etaOpen = false;
function renderEtaDetail(eta) {
  const box = $('etaDetail'), shift = etaShift(eta);
  $('runProgressRight').classList.toggle('eta-moved', !!shift);
  $('runProgressRight').setAttribute('aria-expanded', String(!!shift && etaOpen));
  box.hidden = !shift || !etaOpen;
  if (box.hidden) return;
  const html = `<div class="eta-first">Original estimate: ${fmtEta(eta.original_total)} (${shift})</div>`
    // What made it move; the rest of the gap ("Running faster than estimated") goes unsaid: the shift above says it.
    + `<div class="changes">${(eta.changes || []).filter(change => !/^Running (slower|faster) than estimated$/.test(change.text)).map(etaChange).join('')}</div>`;
  if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
}
$('runProgressRight').addEventListener('click', () => {
  if (!$('runProgressRight').classList.contains('eta-moved')) return;
  etaOpen = !etaOpen;
  renderEtaDetail(lastStatus && lastStatus.running ? (lastStatus.progress || {}).eta : null);
});

// --- Estimate before a run, from the form's current options ---
let plan = null, planRequest = 0, planTimer = 0;
// Seconds of work ahead of a new run; null while the queue is on hold, when nobody can say.
let queueAhead = 0;
function renderPlan() {
  showPlan();
  $('goBarEta').innerHTML = $('estimateTotal').innerHTML;
  $('goBarEta').title = [$('estimateDetail').textContent, $('estimateDetail').title].filter(Boolean).join('\n');
}
function showPlan() {
  if (!plan) return;
  if (!plan.ok) {
    $('estimateTotal').innerHTML = `<span class="err">${esc(plan.error)}</span>`;
    $('estimateDetail').textContent = '';
    return;
  }
  const review = pipeline === 'video' ? $('review').checked
    : pipeline === 'image' && $('imagePromptMode').value === 'llm' && $('imageReview').checked;
  $('estimateContinues').hidden = !plan.continues;
  if (plan.continues) $('estimateContinues').textContent = `Generate continues this stopped video, so nothing is paid for twice: ${plan.continues}`;
  $('estimateTotal').innerHTML = `Estimate: <b>${fmtEta(plan.total)}</b>`;
  if (pipeline === 'image') {
    const images = `${plan.images} ${plan.images === 1 ? 'image' : 'images'}, ${fmtEta(plan.image_render)} each`;
    $('estimateDetail').textContent = review ? 'only the prompts now' : images;
    $('estimateDetail').title = plan.steps.map(s => `${s.name}: ${fmtEta(s.seconds)}`).join('\n');
    return;
  }
  if (pipeline === 'video') {
    const clips = `${clipCount(plan.clips)}, ${fmtEta(plan.clip_render)} each`;
    $('estimateDetail').textContent = review ? 'only the prompts now' : clips;
    $('estimateDetail').title = plan.steps.map(s => `${s.name}: ${fmtEta(s.seconds)}`).join('\n');
    return;
  }
  const parts = [];
  if (plan.videos > 1) parts.push(`${plan.videos} videos, ${fmtEta(plan.video)} each`);
  parts.push(plan.clips
    ? `${plan.clips} ${plan.clips === 1 ? 'clip' : 'clips'} per video, ${fmtEta(plan.clip_render)} each${plan.model ? ` on ${plan.model}` : ''}${plan.model && !plan.model_timed ? ' (not timed yet)' : ''}`
    : 'No avatar clips');
  $('estimateDetail').textContent = parts.join(' · ');
  $('estimateDetail').title = plan.steps.map(s => `${s.name}: ${fmtEta(s.seconds)}`).join('\n');
}
function withoutImages(form) {
  for (const box of [...imageBoxes(), ...mediaBoxes()]) form.delete(box.querySelector('input').name);
  form.delete('audio_file');
  return form;
}
function optionsOnly() {
  // The estimate only needs the options, so it doesn't send the whole images on every change.
  const body = withoutImages(new FormData($('formVideo')));
  body.delete('prompt');
  body.delete('audio_file');
  return body;
}
async function refreshPlan() {
  const request = ++planRequest;
  let data;
  try {
    data = await (await fetch(`/api/estimate/${pipeline}`, { method: 'POST', body: pipeline === 'video' ? optionsOnly() : pipeline === 'image' ? imageOptionsOnly() : new FormData($('formShorts')) })).json();
  } catch (e) {
    return; // transient; the next change retries
  }
  if (request !== planRequest) return;  // A newer answer is on its way
  plan = data;
  renderPlan();
}
function queuePlan() {
  clearTimeout(planTimer);
  planTimer = setTimeout(refreshPlan, 150);
}
for (const id of Object.values(SIDE_FORMS)) {
  $(id).addEventListener('input', queuePlan);
  $(id).addEventListener('change', queuePlan);
  $(id).addEventListener('submit', e => { e.preventDefault(); $('go').click(); });
}
function renderNow(data) {
  const current = data.queue && data.queue.current;
  const privacy = data.running && current ? workPrivacy(current, 'job', current.id) : '';
  const privacySlot = $('currentWorkPrivacy');
  if (!privacySlot.querySelectorAll('.armed, button:disabled').length && privacySlot.innerHTML !== privacy) privacySlot.innerHTML = privacy;
  const p = data.progress || {};
  const c = data.comfyui || {};
  const show = data.running && p.stage;
  const comfyBusy = c.active && c.connected;
  // The clip being rendered is said in ComfyUI's box, so it isn't said twice.
  const detail = nowDetail(data);
  const clip = comfyBusy && /^(Clip|Image) \d/.test(detail) ? detail : '';
  // ComfyUI's box shows whenever it works, even for a job with no stages of its own, such as an upscale.
  $('now').classList.toggle('hidden', !show && !comfyBusy);
  $('stepper').hidden = $('stageDetail').hidden = !show;
  if (show) {
    const [n, total, name] = p.stage;
    const names = STAGES[data.pipeline || pipeline].slice(0, total);
    const steps = p.eta ? p.eta.steps : [];
    $('stepper').innerHTML = names.map((s, i) =>
      `<div class="step ${i + 1 < n ? 'done' : i + 1 === n ? 'now' : ''}">${esc(s)}<span class="eta">${stepEta(steps[i])}</span></div>`).join('');
    // What it is doing now, in shorthand, then what it is working on unless ComfyUI's box already says so.
    // One line says what is happening: under ComfyUI's bar while it renders, else here.
    // The clip being rendered goes in ComfyUI's box, with the action; anything else, such as a scene, stays here.
    const [count, what] = splitCount(comfyBusy && clip ? '' : detail);
    const tokens = !comfyBusy && p.tokens ? `${p.tokens.per_second.toFixed(1)} tok/s · ${p.tokens.total} total tok` : '';
    const first = comfyBusy ? what : [p.action, what, tokens].filter(Boolean).join(' - ') || (count ? '' : STAGE_HINTS[name] || '');
    // How long it has been at this, on the right, unless ComfyUI's box already times it.
    $('stageDetail').innerHTML = statusHtml(first, count, !comfyBusy && first && p.action_elapsed != null ? fmt(p.action_elapsed) : '',
      'How long it has been at this');
    // On to the next stage: what it says now eases in, rather than swapping in place.
    const stage = `${data.pipeline}:${n}`;
    if (stage !== lastStage) {
      if (lastStage !== null) for (const id of ['stageDetail', 'comfyNow']) replay($(id), 'stage-in');
      lastStage = stage;
    }
  } else lastStage = null;

  // ComfyUI's own progress: which part of the workflow, and sampling steps.
  $('comfyNow').classList.toggle('hidden', !comfyBusy);
  if (comfyBusy) {
    $('comfyLabel').textContent = c.label || 'Working';
    const hasSteps = c.max && c.value != null;
    $('comfySteps').textContent = hasSteps ? `Step ${c.value} of ${c.max}` : '';
    $('comfyBar').style.width = hasSteps ? `${Math.round(100 * c.value / c.max)}%` : '0';
    const [counter, what] = splitCount(clip);
    const queued = c.queue > 1 ? `${counter ? ' · ' : ''}${c.queue - 1} more queued` : '';
    $('comfyMeta').innerHTML = statusHtml([show && p.action, what].filter(Boolean).join(' - '), counter + queued,
      fmt(c.elapsed || 0), `This ${data.pipeline === 'image' ? 'image' : 'clip'} so far`);
  }

  const g = data.gpu;
  const icon = (title, paths) => `<svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><title>${title}</title>${paths}</svg>`;
  const vramIcon = icon('VRAM', '<rect x="2" y="7" width="20" height="10" rx="1.5"/><circle cx="8" cy="12" r="2.5"/><path d="M14 10h5M14 14h5M5 17v3"/>');
  const ramIcon = icon('RAM', '<rect x="2" y="8" width="20" height="8" rx="1"/><path d="M6 8v8M10 8v8M14 8v8M18 8v8M4 16v2.5M8 16v2.5M12 16v2.5M16 16v2.5M20 16v2.5"/>');
  const parts = [];
  if (g) parts.push(`GPU ${g.util}%`, `${vramIcon}${g.mem_used}/${g.mem_total}GB`);
  if (c.ram) parts.push(`${ramIcon}${+(c.ram.total - c.ram.free).toFixed(1)}/${c.ram.total}GB`);
  if (g) parts.push(`${g.power}W`, `${g.temp}°C`);
  $('gpuLine').innerHTML = parts.join(' · ');
}

// --- Quota ---
function quotaRow(r) {
  const share = r.limit ? Math.min(r.used / r.limit, 1) : 0;
  const state = r.out ? 'out' : share >= .8 ? 'low' : '';
  const period = r.period ? ` ${r.period}` : '';
  const value = r.limit ? `${r.used.toLocaleString()} / ${r.limit.toLocaleString()}${period}`
    : r.out ? 'limit hit' : `${r.used.toLocaleString()} used${period}`;
  const bar = r.limit ? `<div class="q-bar"><div style="width:${Math.round(share * 100)}%"></div></div>` : '';
  return `<div class="q-row ${state}"><span class="q-name" title="${esc(r.name)}">${esc(r.name)}</span>
    <span class="q-val">${value}${r.out && r.limit ? ' · limit hit' : ''}</span>${bar}</div>`;
}
let lastQuota = '';
function renderQuota(q) {
  const key = JSON.stringify(q.groups);
  if (key !== lastQuota) {
    $('quota').innerHTML = q.groups.map(g =>
      `<div class="q-group">${esc(g.title)}</div>${g.rows.map(quotaRow).join('')}`).join('');
    lastQuota = key;
  }
  const at = clockIn(q.resets_in);
  $('quotaReset').textContent = `Resets in ${fmtEta(q.resets_in)} (${at}).`;
}

// --- Log ---
function lineKind(text) {
  const s = text.trim();
  if (/^▶ Stage|^=====/.test(s)) return 'stage';
  if (/^❌|^🚨|Error\b|Traceback/.test(s)) return 'err';
  if (/^⚠️|^🛑/.test(s)) return 'warn';
  if (/^✅|^✨|^📦/.test(s)) return 'ok';
  if (/^Deleted:|^🧹/.test(s)) return 'dim';
  return '';
}
// Shown without emoji, and to the minute: the lines keep both as printed, for what reads them.
const LOG_EMOJI = /[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{200D}\u{20E3}]\s*/gu;
function plain(text) { return String(text).replace(LOG_EMOJI, ''); }
function logMinute(t) { return /^\d+:\d+:\d+$/.test(t || '') ? t.slice(0, -3) : (t || ''); }
function logWriter(el, follow) {
  let first = null, last = 0;
  const row = l => `<div class="ln ${l.k ?? lineKind(l.text)}"><span class="t">${logMinute(l.t)}</span><span class="x">${esc(plain(l.text))}</span></div>`;
  return lines => {
    // A new run, or old lines trimmed off the top: redraw. Otherwise append what is new.
    if (first !== null && lines[0].n > first && lines[0].n <= last) {
      const before = el.scrollHeight, kept = lines.filter(l => l.n <= last).length;
      while (el.children.length > kept) el.firstElementChild.remove();
      if (!follow()) el.scrollTop -= before - el.scrollHeight;
      first = lines[0].n;
      const fresh = lines.filter(l => l.n > last);
      if (fresh.length) el.insertAdjacentHTML('beforeend', fresh.map(row).join(''));
    } else if (lines[0].n !== first) {
      el.innerHTML = lines.map(row).join('');
      first = lines[0].n;
    } else {
      const fresh = lines.filter(l => l.n > last);
      if (fresh.length) el.insertAdjacentHTML('beforeend', fresh.map(row).join(''));
    }
    last = lines[lines.length - 1].n;
    if (follow()) el.scrollTop = el.scrollHeight;
  };
}
// --- The generation log: sections per stage ---
// Summary puts each image or clip, each written prompt, the local model starting and the stock footage on a line of
// its own that opens to show the rest: the seed, the full prompt, the render's details. An image or clip says how
// long it took against what it was expected to take. Detailed leaves every line as it was printed. A warning or a
// failure is never folded away: it stays on show, even in a stage that is closed.
const LOG_STAGE = /^▶ Stage (\d+)\/(\d+): (.+)$/;
const LOG_CLIP = /^🎬 Clip (\d+)\/(\d+) · (.+)$/;
const LOG_IMAGE = /^(?:🖼️?\s*)?Image (\d+)\/(\d+) · (.+)$/u;
const LOG_PROMPT = /^(\d+)\. (.+)$/;
const LOG_PROMPT_TITLE = 70;
const LOG_TELEMETRY = /^Local LLM: (?:[\d.]+ tok\/s|idle|telemetry unavailable)/;
const LOG_WRITTEN = /^Local LLM complete: (?:([\d.]+) tok\/s \| )?(\d+) total tok/;
const LOG_MODEL_START = /^(?:Waiting for ComfyUI to finish clearing|🧠 Starting the local)/u;
const LOG_MODEL_READY = /^🧠 Local model ready/u;
// Within this much of its ETA, it finished on time.
const LOG_ON_TIME = eta => Math.max(5, eta * 0.1);
const LOG_KEPT = /^♻️ (?:Clip|Image) (\d+)(?:\/| of )(\d+)\b.*kept from earlier/u;
const LOG_AVATAR_FAILED = /^❌ Scene (\d+) avatar failed: (.*)$/;
const LOG_AVATAR_GAVE_UP = /^❌ Scene (\d+) avatar clip not made; using stock footage\.?$/;
const LOG_FELL_BACK = /^[❌⚠️]+\s*Scene (\d+) (.+?)\s*(?:;|—)\s*using stock footage\.?$/u;
const LOG_PREVIEW_AT = 220;
const LOG_PREVIEW = 160;
const logOpened = new Map();   // What was opened or closed by hand, by key; the rest follows the defaults
let logDetailed = false;
let logLines = [];
let logShown = '';

function logClock(t) {
  const m = /^(\d+):(\d+):(\d+)$/.exec(t || '');
  return m ? (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]) : null;
}
function logTook(from, to) {
  if (from === null || to === null) return '';
  const sec = to >= from ? to - from : to + 86400 - from;
  const m = Math.floor(sec / 60);
  return sec < 60 ? `${sec}s` : m < 60 ? `${m}m ${sec % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}
function logSeconds(sec) {
  const m = Math.floor(sec / 60);
  return sec < 60 ? `${sec}s` : m < 60 ? (sec % 60 ? `${m}m ${sec % 60}s` : `${m}m`) : `${Math.floor(m / 60)}h ${m % 60}m`;
}
// "48s · on ETA", "48s · 12s sooner than its 60s ETA", or while it renders, "ETA 60s".
function logAgainstEta(took, eta) {
  if (took === null) return eta ? ` · ETA ${logSeconds(eta)}` : '';
  if (!eta) return ` · ${logSeconds(took)}`;
  const off = took - eta;
  if (Math.abs(off) <= LOG_ON_TIME(eta)) return ` · ${logSeconds(took)} · on ETA`;
  return ` · ${logSeconds(took)} · ${logSeconds(Math.abs(off))} ${off < 0 ? 'sooner' : 'later'} than its ${logSeconds(eta)} ETA`;
}
function logClipTitle(c) {
  const avatar = /^scene (\d+): (\d+s)\s*(.*)$/i.exec(c.rest);
  const what = c.kind === 'Image' ? c.rest
    : avatar ? `Scene ${avatar[1]} · ${avatar[2]}${avatar[3] ? ` · ${avatar[3]}` : ''}` : c.rest;
  const took = c.secs || (c.saved && c.from !== null && c.to !== null ? (c.to >= c.from ? c.to - c.from : c.to + 86400 - c.from) : null);
  return `${c.kind} ${c.number}/${c.total} · ${plain(what)}`
    + (c.failed ? ' · failed' : c.saved ? logAgainstEta(took, c.eta) : c.running ? logAgainstEta(null, c.eta) : '');
}
function logPromptTitle(number, text) {
  const words = plain(text).trim();
  if (words.length <= LOG_PROMPT_TITLE) return `Prompt ${number} · ${words}`;
  const cut = words.slice(0, LOG_PROMPT_TITLE), space = cut.lastIndexOf(' ');
  return `Prompt ${number} · ${(space > LOG_PROMPT_TITLE / 2 ? cut.slice(0, space) : cut).trimEnd()}…`;
}
function logTokens(stage) {
  if (!stage.tokens) return '';
  const rate = stage.writeSeconds ? stage.rated / stage.writeSeconds : null;
  return `${stage.tokens.toLocaleString('en-US')} tokens` + (rate ? ` · ${rate.toFixed(1)} tok/s` : '');
}
function logStockTitle(g) {
  const total = g.scenes || g.ready.size + g.failed.size;
  const list = set => [...set].sort((a, b) => a - b).join(', ');
  return `Stock footage: ${g.ready.size}/${total} scene${total === 1 ? '' : 's'} ready`
    + (g.fallback.size ? ` · scene${g.fallback.size === 1 ? '' : 's'} ${list(g.fallback)} using fallback` : '')
    + (g.failed.size ? ` · scene${g.failed.size === 1 ? '' : 's'} ${list(g.failed)} failed` : '');
}

// Turns the lines into stages, each with its entries: a line, or a group that stands for several.
function buildLog(lines, detailed) {
  const blocks = [];
  let stage = null, current = null, inClip = false, stock = null, held = null, scenes = 0, prompt = null, model = null;
  const emit = entry => {
    (stage ? stage.entries : blocks).push(entry);
    if (stage && entry.k === 'err') stage.err++;
    else if (stage && entry.k === 'warn') stage.warn++;
    return entry;
  };
  const flush = () => { if (held) { emit(held.entry); held = null; } };
  const group = (entry, children, text) => ({ ...entry, text, children });
  for (const l of lines) {
    const text = l.text, trimmed = text.trim(), k = l.k ?? lineKind(text);
    const entry = { n: l.n, t: l.t, k, text, ...(l.eta !== undefined ? { eta: l.eta } : {}) };
    const total = /(?:narration|Generation) for (\d+) scenes/.exec(trimmed);
    if (total) scenes = +total[1];

    const begins = LOG_STAGE.exec(trimmed);
    if (begins) {
      flush();
      current = stock = prompt = model = null;
      inClip = false;
      stage = { n: l.n, t: l.t, idx: +begins[1], total: +begins[2], name: begins[3], entries: [], warn: 0, err: 0,
        from: logClock(l.t), to: logClock(l.t), clips: [], stocks: [], tokens: 0, rated: 0, writeSeconds: 0 };
      blocks.push(stage);
      continue;
    }
    if (/^=====/.test(trimmed)) {
      flush();
      current = stock = prompt = model = null;
      inClip = false;
      stage = null;
      blocks.push({ ...entry, k: 'stage' });
      continue;
    }
    if (stage) stage.to = logClock(l.t) ?? stage.to;

    // What it says about the clip being made, whichever way the lines are shown.
    const problem = k === 'err' || k === 'warn';
    const detail = k === 'comfy' || (/^\s{3,}/.test(text) && !problem);
    const clipLine = LOG_CLIP.exec(trimmed) || LOG_IMAGE.exec(trimmed);
    if (clipLine && stage) {
      current = { n: l.n, kind: LOG_CLIP.test(trimmed) ? 'Clip' : 'Image', number: +clipLine[1], total: +clipLine[2], rest: clipLine[3],
        scene: (/^scene (\d+):/i.exec(clipLine[3]) || [])[1], saved: false, failed: false, kept: false, secs: 0,
        eta: l.eta ?? null, from: logClock(l.t), to: null };
      stage.clips.push(current);
    } else if (stage && LOG_KEPT.test(trimmed)) {
      stage.clips.push({ n: l.n, kept: true, kind: /Image/.test(trimmed) ? 'Image' : 'Clip', total: +LOG_KEPT.exec(trimmed)[2] });
    } else if (current) {
      if (/^✅ (?:Saved |Done\b)/u.test(trimmed)) { current.saved = true; current.to = logClock(l.t); }
      const took = /Rendered in (\d+)s/.exec(trimmed);
      if (took) current.secs += +took[1];
    }
    const failedClip = /^❌ (?:Clip|Image) (\d+) failed/u.exec(trimmed);
    const failedScene = /^[❌⚠️]+\s*Scene (\d+) .*(?:avatar failed|avatar clip not made|never passed)/u.exec(trimmed);
    if (stage && (failedClip || failedScene)) {
      const hit = stage.clips.find(c => failedClip ? c.number === +failedClip[1] : c.scene === failedScene[1]);
      if (hit) hit.failed = true;
    }
    if (clipLine) inClip = true;
    else if (!problem && !detail) inClip = false;

    const written = LOG_WRITTEN.exec(trimmed);
    if (written && stage) {
      stage.tokens += +written[2];
      if (written[1] && +written[1] > 0) { stage.rated += +written[2]; stage.writeSeconds += +written[2] / +written[1]; }
    }

    if (detailed) { emit(entry); continue; }

    // The model's running count of what it has written, every few seconds: the total is on the line below.
    if (LOG_TELEMETRY.test(trimmed)) continue;
    if (written) {
      emit({ ...entry, k: 'dim', text: `Local model wrote ${(+written[2]).toLocaleString('en-US')} tokens${written[1] ? ` · ${(+written[1]).toFixed(1)} tok/s` : ''}` });
      continue;
    }
    // Starting the local model, from ComfyUI making room for it to its being ready, in one line.
    if (!model && LOG_MODEL_START.test(trimmed)) {
      flush();
      model = emit(group(entry, [entry], 'Starting the local model'));
      model.from = logClock(l.t);
      continue;
    }
    if (model && !problem) {
      model.children.push(entry);
      if (LOG_MODEL_READY.test(trimmed)) {
        const took = logTook(model.from, logClock(l.t));
        model.text = `Local model started${took ? ` · ${took}` : ''}`;
        model = null;
      }
      continue;
    }
    // A written prompt: its number and title on the line, the prompt itself inside.
    const promptLine = stage && /prompt|plan/i.test(stage.name) && !problem && !/^\s/.test(text) ? LOG_PROMPT.exec(trimmed) : null;
    if (promptLine) {
      flush();
      const long = plain(promptLine[2]).trim().length > LOG_PROMPT_TITLE;
      prompt = emit(group(entry, long ? [entry] : [], logPromptTitle(promptLine[1], promptLine[2])));
      continue;
    }
    if (prompt && /^\s{3,}/.test(text) && !problem) {
      prompt.children.push(entry);
      continue;
    }
    prompt = null;

    // A failure the app recovered from, in one line: what happened, and what it did next.
    if (held) {
      const gaveUp = LOG_AVATAR_GAVE_UP.exec(trimmed);
      if (gaveUp && gaveUp[1] === held.scene) {
        emit(group({ n: held.entry.n, t: held.entry.t, k: 'warn' }, [held.entry, entry], `Scene ${held.scene}: avatar failed · using stock footage`));
        held = null;
        continue;
      }
      flush();
    }
    const failed = LOG_AVATAR_FAILED.exec(trimmed);
    if (failed) { held = { scene: failed[1], entry }; continue; }
    const fellBack = LOG_FELL_BACK.exec(trimmed);
    if (fellBack) { emit({ ...entry, k: 'warn', text: `Scene ${fellBack[1]}: ${fellBack[2]} · using stock footage` }); continue; }

    if (clipLine && stage) {
      current.entry = emit(group(entry, [], logClipTitle(current)));
      continue;
    }
    if (/^🎥 Starting Double-Feature Video Download/.test(trimmed) && stage) {
      stock = { ready: new Set(), fallback: new Set(), failed: new Set(), scenes };
      stage.stocks.push(stock);
      stock.entry = emit(group(entry, [entry], ''));
      stock.entry.text = logStockTitle(stock);
      continue;
    }
    if (stock) {
      const ready = /^✅ Scene (\d+) Ready/.exec(trimmed), missing = /^⚠️ Scene (\d+) Clip [AB] missing/.exec(trimmed), lost = /^❌ Scene (\d+) Completely Failed/.exec(trimmed);
      if (ready) stock.ready.add(+ready[1]);
      if (missing) stock.fallback.add(+missing[1]);
      if (lost) stock.failed.add(+lost[1]);
      if (problem) emit(entry);
      else stock.entry.children.push(entry);
      stock.entry.text = logStockTitle(stock);
      if (/^🎥 Assets Downloaded/.test(trimmed)) stock = null;
      continue;
    }
    if (current && current.entry && inClip && !problem && detail) {
      current.entry.children.push(entry);
      current.entry.text = logClipTitle(current);
      continue;
    }
    if (current && current.entry) current.entry.text = logClipTitle(current);
    emit(entry);
  }
  flush();
  const last = [...blocks].reverse().find(block => block.entries);
  for (const block of blocks) {
    if (!block.entries) continue;
    const active = block === last;
    for (const c of block.clips) {
      c.running = !!(active && inClip && c === current && !c.saved && !c.failed);
      if (c.entry) c.entry.text = logClipTitle(c);
    }
  }
  return blocks;
}

function logStageHeading(stage) {
  const parts = [`Stage ${stage.idx}/${stage.total}`, esc(plain(stage.name))];
  const clips = stage.clips;
  if (clips.length) {
    const total = Math.max(...clips.map(c => c.total));
    const done = clips.filter(c => c.kept || c.saved || (!c.failed && !c.running)).length;
    const failed = clips.filter(c => c.failed).length;
    const things = clips.some(c => c.kind === 'Image') ? 'images' : 'clips';
    parts.push(done === total && !failed ? `${done}/${total} complete` : `${done}/${total} ${things}`);
    if (failed) parts.push(`<span class="bad">${failed} failed</span>`);
  } else if (stage.stocks.length) {
    const stock = stage.stocks[stage.stocks.length - 1];
    const total = stock.scenes || stock.ready.size + stock.failed.size;
    parts.push(`${stock.ready.size}/${total} scenes`);
  }
  const took = logTook(stage.from, stage.to);
  if (took) parts.push(took);
  const tokens = logTokens(stage);
  if (tokens) parts.push(tokens);
  if (stage.err) parts.push(`<span class="bad">${stage.err} error${stage.err === 1 ? '' : 's'}</span>`);
  if (stage.warn) parts.push(`<span class="caution">${stage.warn} warning${stage.warn === 1 ? '' : 's'}</span>`);
  return parts.join(' · ');
}

const RUN_START = /^=====\s*(.*?)\s*=====\s*(.*)$/s;
function logRowHtml(entry, detailed, child = false) {
  const problem = entry.k === 'err' || entry.k === 'warn';
  // Summary shows nesting by its folds, so a line's own indent goes; Detailed keeps it.
  const text = detailed ? plain(entry.text) : plain(entry.text).trim();
  const long = !detailed && text.length > LOG_PREVIEW_AT;
  const classes = `ln ${entry.k}${child ? ' child' : ''}`;
  const t = logMinute(entry.t);
  // "===== New run, 20 images ===== its title": the heading, and the title under it.
  const starting = RUN_START.exec(plain(entry.text).trim());
  if (starting) {
    return `<div class="${classes} run-start" data-n="${entry.n}"><span class="t">${t}</span><span class="x"><span class="run-start-head">${esc(starting[1])}</span>`
      + `${starting[2] ? `<span class="run-start-title">${esc(starting[2])}</span>` : ''}</span></div>`;
  }
  if (!long) return `<div class="${classes}" data-n="${entry.n}"><span class="t">${t}</span><span class="x">${esc(text)}</span></div>`;
  const cut = text.slice(0, LOG_PREVIEW), space = cut.lastIndexOf(' ');
  const preview = (space > LOG_PREVIEW / 2 ? cut.slice(0, space) : cut).trimEnd();
  const label = problem ? 'Show full message' : /^\s{3,}/.test(entry.text) || /prompt/i.test(entry.text.slice(0, 80)) ? 'Show full prompt' : 'Show full response';
  const open = logOpened.get(`m${entry.n}`) === true;
  return `<div class="${classes} long${open ? ' expanded' : ''}" data-n="${entry.n}"><span class="t">${t}</span><span class="x"><span class="x-short">${esc(preview)}…</span><span class="x-full">${esc(text)}</span>`
    + `<button type="button" class="ln-more" data-more="${entry.n}" data-label="${label}">${open ? 'Hide' : label}</button></span></div>`;
}

function logHtml(lines, detailed) {
  const blocks = buildLog(lines, detailed);
  const last = [...blocks].reverse().find(block => block.entries);
  const entryHtml = entry => {
    if (!entry.children) return logRowHtml(entry, detailed);
    const key = `g${entry.n}`, open = logOpened.get(key) === true;
    const row = `<div class="ln ${entry.k}" data-n="${entry.n}"><span class="t">${logMinute(entry.t)}</span>`;
    // Nothing more to show: a line, without a fold.
    if (!entry.children.length) return `${row}<span class="x">${esc(plain(entry.text))}</span></div>`;
    return `<div class="log-grp${open ? ' open' : ''}" data-key="${key}">${row}`
      + `<span class="x"><button type="button" class="log-fold" aria-expanded="${open}"><span class="grp-text">${esc(plain(entry.text))}</span><span class="log-chev"></span></button></span></div>`
      + `<div class="grp-body">${entry.children.map(child => logRowHtml(child, detailed, true)).join('')}</div></div>`;
  };
  return blocks.map(block => {
    if (!block.entries) return logRowHtml(block, detailed);
    const key = `s${block.n}`;
    const open = logOpened.has(key) ? logOpened.get(key) : detailed || block === last;
    return `<section class="stage-sec${open ? ' open' : ''}" data-key="${key}"><div class="ln stage" data-n="${block.n}"><span class="t">${logMinute(block.t)}</span>`
      + `<span class="x"><button type="button" class="log-fold" aria-expanded="${open}"><span class="stage-text">${logStageHeading(block)}</span><span class="log-chev"></span></button></span></div>`
      + `<div class="stage-body">${block.entries.map(entryHtml).join('')}</div></section>`;
  }).join('');
}

function renderLog(lines = logLines, force = false) {
  logLines = lines;
  if (!lines.length) return;
  const el = $('log');
  const key = `${logDetailed}|${lines.length}|${lines[0].n}|${lines[lines.length - 1].n}`;
  if (!force && key === logShown) return;
  // Not under a selection being copied: it would be lost. It is drawn on the next poll.
  const picked = typeof getSelection === 'function' ? getSelection() : null;
  if (!force && picked && !picked.isCollapsed && picked.anchorNode && el.contains(picked.anchorNode)) return;
  logShown = key;
  const follows = autoScroll;
  // Reading further up keeps what is in view where it is, as lines are added below or trimmed off the top.
  let anchor = null;
  if (!follows && el.querySelectorAll) {
    const top = el.getBoundingClientRect().top;
    for (const node of el.querySelectorAll('[data-n]')) {
      const box = node.getBoundingClientRect();
      if (box.height && box.bottom > top) { anchor = { n: node.dataset.n, offset: box.top - top }; break; }
    }
  }
  el.innerHTML = logHtml(lines, logDetailed);
  if (follows) el.scrollTop = el.scrollHeight;
  else if (anchor) {
    const node = el.querySelector(`[data-n="${anchor.n}"]`);
    if (node) el.scrollTop += node.getBoundingClientRect().top - el.getBoundingClientRect().top - anchor.offset;
  }
}
$('log').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('button');
  if (!button) return;
  if (button.classList.contains('log-fold')) {
    const box = button.closest('.stage-sec, .log-grp');
    const open = !box.classList.contains('open');
    box.classList.toggle('open', open);
    button.setAttribute('aria-expanded', String(open));
    logOpened.set(box.dataset.key, open);
  } else if (button.classList.contains('ln-more')) {
    const row = button.closest('.ln');
    const open = !row.classList.contains('expanded');
    row.classList.toggle('expanded', open);
    button.textContent = open ? 'Hide' : button.dataset.label;
    logOpened.set(`m${button.dataset.more}`, open);
  }
});
let uploadFollow = true;
const renderUploadLog = logWriter($('uploadLog'), () => uploadFollow);

function renderUpload(up) {
  // How each one ended is under Finished, so this only shows while one is going or waiting.
  $('uploadBox').hidden = !up.running && !up.queue.items.length;
  $('uploadDot').className = 'dot' + (up.running ? ' on' : '');
  $('stopUpload').hidden = !up.running;
  $('uploadStatus').textContent = up.running ? `Uploading · ${fmt(up.elapsed)} so far`
    : up.queue.held ? 'Uploads on hold' : 'Waiting to upload';
  renderQueue($('uploadQueue'), up.queue, 0);
  if (up.lines.length) renderUploadLog(up.lines);
}
