// --- Painting what to change, over image 1: a colour per change, by brush or by clicking a thing (Select) ---
const PAINT_COLOURS = [['red', '#e62828'], ['blue', '#285aeb'], ['green', '#28be46'], ['yellow', '#f5d21e'],
                       ['magenta', '#e132c8'], ['cyan', '#28d2dc'], ['orange', '#f58c1e'], ['purple', '#823cd2']];
const PAINT_ACTIONS = [['remove', 'Remove'], ['change', 'Change it to'], ['replace', 'Replace it with'], ['add', 'Add']];
const PAINT_PLACEHOLDERS = { change: 'what it becomes', remove: 'what to remove (optional)', replace: 'what goes there instead', add: 'what to add there' };
const MOST_UNDO = 8;
function forgetPaint() {
  paint = null;
  if ($('areasJson')) {
    $('areasJson').value = '';
    $('areasMask').value = '';
    $('areasHint').textContent = 'Nothing painted yet.';
  }
}
function paintColour() { return PAINT_COLOURS.find(([name]) => name === paint.colour)[1]; }
async function openPaint() {
  const epoch = workspaceEpoch;
  const box = sourceBoxes()[0], file = box && box.querySelector('input').files[0];
  if (!file) { showFormError('Choose image 1 first: the image to paint on.'); return; }
  if ($('paintImage').src) URL.revokeObjectURL($('paintImage').src);
  if (!paint || paint.file !== file || !paint.ready) {
    paint = { file, tool: 'brush', colour: 'red', history: [], texts: {}, actions: {}, key: null, canvas: document.createElement('canvas'), ready: false };
    const loaded = new Promise((resolve, reject) => {
      $('paintImage').onload = resolve;
      $('paintImage').onerror = reject;
    });
    $('paintImage').src = URL.createObjectURL(file);
    try { await loaded; } catch (e) {
      if (epoch === workspaceEpoch) showFormError('Could not load the image for painting. Choose it again.');
      return;
    }
    if (epoch !== workspaceEpoch) return;
    paint.canvas.width = $('paintImage').naturalWidth;
    paint.canvas.height = $('paintImage').naturalHeight;
    paint.ready = true;
  } else $('paintImage').src = URL.createObjectURL(file);
  const canvas = $('paintCanvas');
  canvas.width = paint.canvas.width;
  canvas.height = paint.canvas.height;
  canvas.getContext('2d').drawImage(paint.canvas, 0, 0);
  $('paintColours').innerHTML = PAINT_COLOURS.map(([name, hex]) =>
    `<button type="button" data-paint-colour="${name}" class="${name === paint.colour ? 'active' : ''}" style="background:${hex}" title="${name}" aria-label="${name}"></button>`).join('');
  for (const button of document.querySelectorAll('[data-paint-tool]')) button.classList.toggle('active', button.dataset.paintTool === paint.tool);
  showPaintColour();
  showPaintSize();
  closePaintPops();
  refreshAreas();
  paintError('');
  $('paintDialog').showModal();
  fitPaint();
}
function showPaintColour() { $('paintColourDot').style.background = paintColour(); }
function showPaintSize() {
  const px = Math.round(4 + (+$('paintSize').value - 1) * 18 / 19);
  $('paintSizeDot').style.width = $('paintSizeDot').style.height = `${px}px`;
}

// --- Zooming in to paint fine details: the wheel or two fingers; Space or the middle button drags it about ---
const MOST_PAINT_ZOOM = 16;
const paintView = { z: 1, x: 0, y: 0, w: 0, h: 0 };  // the picture's fitted size, and how far it is zoomed and moved
function fitPaint() {
  if (!paint) return;
  const stage = $('paintStage'), scale = Math.min(stage.clientWidth / paint.canvas.width, stage.clientHeight / paint.canvas.height) || 1;
  paintView.w = paint.canvas.width * scale;
  paintView.h = paint.canvas.height * scale;
  paintView.z = 1;
  $('paintBoard').style.width = `${paintView.w}px`;
  $('paintBoard').style.height = `${paintView.h}px`;
  placeBoard();
}
// Centred while it fits, and never dragged off past its edges once it doesn't.
function placeBoard() {
  const stage = $('paintStage'), width = stage.clientWidth, height = stage.clientHeight, w = paintView.w * paintView.z, h = paintView.h * paintView.z;
  paintView.x = w <= width ? (width - w) / 2 : Math.min(0, Math.max(width - w, paintView.x));
  paintView.y = h <= height ? (height - h) / 2 : Math.min(0, Math.max(height - h, paintView.y));
  $('paintBoard').style.transform = `translate(${paintView.x}px, ${paintView.y}px) scale(${paintView.z})`;
  $('paintFit').hidden = paintView.z <= 1.001;
}
// Zoomed about a point on the stage, which stays under the pointer.
function zoomPaintAt(x, y, z) {
  z = Math.min(MOST_PAINT_ZOOM, Math.max(1, z));
  const bx = (x - paintView.x) / paintView.z, by = (y - paintView.y) / paintView.z;
  paintView.z = z;
  paintView.x = x - bx * z;
  paintView.y = y - by * z;
  placeBoard();
}
function stagePoint(clientX, clientY) {
  const rect = $('paintStage').getBoundingClientRect();
  return [clientX - rect.left, clientY - rect.top];
}
$('paintStage').addEventListener('wheel', e => {
  if (!paint) return;
  e.preventDefault();
  const delta = e.deltaY * (e.deltaMode === 1 ? 16 : 1);
  zoomPaintAt(...stagePoint(e.clientX, e.clientY), paintView.z * Math.exp(-delta * (e.ctrlKey ? 0.01 : 0.0015)));
}, { passive: false });
$('paintFit').addEventListener('click', fitPaint);
window.addEventListener('resize', () => { if (paint && $('paintDialog').open) fitPaint(); });
let spaceHeld = false;
document.addEventListener('keydown', e => {
  if (e.key !== ' ' || !$('paintDialog').open || $('paintPrompts').open || e.target.matches('input, select, textarea')) return;
  e.preventDefault();
  spaceHeld = true;
  $('paintStage').classList.add('panning');
});
document.addEventListener('keyup', e => {
  if (e.key !== ' ') return;
  spaceHeld = false;
  $('paintStage').classList.remove('panning');
});

// --- The colour and the brush size: each grows out of its button, and a tap anywhere else puts it away ---
function closePaintPops(except) {
  for (const [toggle, pop] of [['paintColourToggle', 'paintColourPop'], ['paintSizeToggle', 'paintSizePop']]) {
    if (pop === except) continue;
    $(pop).hidden = true;
    $(toggle).setAttribute('aria-expanded', 'false');
  }
}
for (const [toggle, pop] of [['paintColourToggle', 'paintColourPop'], ['paintSizeToggle', 'paintSizePop']]) {
  $(toggle).addEventListener('click', () => {
    closePaintPops(pop);
    $(pop).hidden = !$(pop).hidden;
    $(toggle).setAttribute('aria-expanded', String(!$(pop).hidden));
  });
}
$('paintDialog').addEventListener('pointerdown', e => {
  if (!e.target.closest('.paint-pop-wrap')) closePaintPops();
});
$('paintSize').addEventListener('input', showPaintSize);
function paintPoint(e) {
  const canvas = $('paintCanvas'), rect = canvas.getBoundingClientRect();
  return [(e.clientX - rect.left) * canvas.width / rect.width, (e.clientY - rect.top) * canvas.height / rect.height];
}
function snapshot() {
  const canvas = $('paintCanvas');
  paint.history.push(canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height));
  if (paint.history.length > MOST_UNDO) paint.history.shift();
}
function stroke(from, to) {
  const canvas = $('paintCanvas'), ctx = canvas.getContext('2d');
  ctx.globalCompositeOperation = paint.tool === 'erase' ? 'destination-out' : 'source-over';
  ctx.strokeStyle = ctx.fillStyle = paintColour();
  ctx.lineWidth = +$('paintSize').value / 200 * Math.max(canvas.width, canvas.height) / paintView.z;
  ctx.lineCap = ctx.lineJoin = 'round';
  ctx.beginPath();
  ctx.moveTo(from[0], from[1]);
  ctx.lineTo(to[0] + 0.01, to[1]);
  ctx.stroke();
}
// One finger or the mouse paints, or with Select picks the thing it lifts on; two fingers zoom and move the picture,
// as do Space or the middle button with the mouse.
let painting = null, paintTap = null, paintPinch = null, paintPan = null, paintResting = false;
const paintPointers = new Map();
function startPaintPinch() {
  const [a, b] = [...pointers.values()];
  const mid = stagePoint((a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
  paintPinch = { distance: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, z: paintView.z,
            bx: (mid[0] - paintView.x) / paintView.z, by: (mid[1] - paintView.y) / paintView.z };
}
$('paintStage').addEventListener('pointerdown', e => {
  if (!paint || e.target === $('paintFit')) return;
  e.preventDefault();
  closePaintPops();
  paintPointers.set(e.pointerId, [e.clientX, e.clientY]);
  $('paintStage').setPointerCapture(e.pointerId);
  if (paintPointers.size === 2) {
    // The first finger began a stroke: the second makes it a paintPinch, so that stroke is taken back.
    if (painting) { $('paintCanvas').getContext('2d').putImageData(paint.history.pop(), 0, 0); painting = null; }
    paintTap = null;
    startPaintPinch();
    return;
  }
  if (paintPointers.size > 2 || paintResting) return;
  if (e.button === 1 || spaceHeld) { paintPan = { x: e.clientX, y: e.clientY, vx: paintView.x, vy: paintView.y }; return; }
  if (e.button !== 0) return;
  const point = paintPoint(e);
  if (paint.tool === 'select') { paintTap = { id: e.pointerId, x: e.clientX, y: e.clientY, point, away: e.shiftKey }; return; }
  snapshot();
  painting = point;
  stroke(point, point);
});
// The middle button drags the picture, rather than starting the browser's own scrolling.
$('paintStage').addEventListener('mousedown', e => { if (e.button === 1) e.preventDefault(); });
$('paintStage').addEventListener('pointermove', e => {
  if (!paintPointers.has(e.pointerId)) return;
  paintPointers.set(e.pointerId, [e.clientX, e.clientY]);
  if (paintPinch && paintPointers.size >= 2) {
    const [a, b] = [...pointers.values()];
    const mid = stagePoint((a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
    paintView.z = Math.min(MOST_PAINT_ZOOM, Math.max(1, paintPinch.z * Math.hypot(a[0] - b[0], a[1] - b[1]) / paintPinch.distance));
    paintView.x = mid[0] - paintPinch.bx * paintView.z;
    paintView.y = mid[1] - paintPinch.by * paintView.z;
    placeBoard();
  } else if (paintPan) {
    paintView.x = paintPan.vx + e.clientX - paintPan.x;
    paintView.y = paintPan.vy + e.clientY - paintPan.y;
    placeBoard();
  } else if (painting) {
    const point = paintPoint(e);
    stroke(painting, point);
    painting = point;
  } else if (paintTap && Math.hypot(e.clientX - paintTap.x, e.clientY - paintTap.y) > 8) {
    paintTap = null;
  }
});
for (const kind of ['pointerup', 'pointercancel']) $('paintStage').addEventListener(kind, e => {
  if (!paintPointers.delete(e.pointerId)) return;
  if (paintPinch) {
    paintPinch = null;
    // The finger left after a paintPinch doesn't start painting where it rests.
    paintResting = paintPointers.size > 0;
    return;
  }
  if (!paintPointers.size) paintResting = false;
  paintPan = null;
  if (paintTap && paintTap.id === e.pointerId && kind === 'pointerup') selectAt(paintTap.point, paintTap.away);
  paintTap = null;
  if (painting) {
    painting = null;
    refreshAreas();
  }
});
// A click on a thing paints all of it in the colour chosen; with Shift it takes it away.
async function selectAt([x, y], away) {
  const epoch = workspaceEpoch, selection = paint;
  $('paintStage').classList.add('busy');
  try {
    if (!paint.key) {
      const body = new FormData();
      body.append('image', paint.file);
      const reply = await (await fetch('/api/select/image', { method: 'POST', body })).json();
      if (epoch !== workspaceEpoch || paint !== selection) return;
      if (!reply.ok) throw new Error(reply.error || 'Select could not read the image.');
      paint.key = reply.key;
    }
    const response = await fetch('/api/select', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: paint.key, points: [[x, y, true]] }) });
    if (epoch !== workspaceEpoch || paint !== selection) return;
    if (!response.ok) {
      const reply = await response.json().catch(() => ({}));
      if (epoch !== workspaceEpoch || paint !== selection) return;
      if (response.status === 410) paint.key = null;
      throw new Error(reply.error || 'Select could not find anything there.');
    }
    const mask = await createImageBitmap(await response.blob());
    if (epoch !== workspaceEpoch || paint !== selection) { mask.close(); return; }
    const canvas = $('paintCanvas'), layer = document.createElement('canvas');
    layer.width = canvas.width;
    layer.height = canvas.height;
    const lctx = layer.getContext('2d');
    lctx.drawImage(mask, 0, 0, layer.width, layer.height);
    mask.close();
    const pixels = lctx.getImageData(0, 0, layer.width, layer.height), data = pixels.data;
    const hex = paintColour(), rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    for (let i = 0; i < data.length; i += 4) {
      const on = data[i] > 127;
      data[i] = rgb[0]; data[i + 1] = rgb[1]; data[i + 2] = rgb[2]; data[i + 3] = on ? 255 : 0;
    }
    lctx.putImageData(pixels, 0, 0);
    snapshot();
    const ctx = canvas.getContext('2d');
    ctx.globalCompositeOperation = away ? 'destination-out' : 'source-over';
    ctx.drawImage(layer, 0, 0);
    refreshAreas();
  } catch (e) {
    if (epoch === workspaceEpoch && paint === selection) paintError(e.message || 'Select could not find anything there.');
  } finally {
    if (epoch === workspaceEpoch && paint === selection) $('paintStage').classList.remove('busy');
  }
}
// The colours painted, found on a small copy, in the order of the palette.
function paintedColours() {
  const canvas = $('paintCanvas'), small = document.createElement('canvas'), scale = Math.min(1, 256 / Math.max(canvas.width, canvas.height, 1));
  small.width = Math.max(1, Math.round(canvas.width * scale));
  small.height = Math.max(1, Math.round(canvas.height * scale));
  const ctx = small.getContext('2d');
  ctx.drawImage(canvas, 0, 0, small.width, small.height);
  const data = ctx.getImageData(0, 0, small.width, small.height).data, found = new Set();
  const palette = PAINT_COLOURS.map(([name, hex]) => [name, [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16))]);
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 128) continue;
    let best = null, distance = Infinity;
    for (const [name, rgb] of palette) {
      const d = (data[i] - rgb[0]) ** 2 + (data[i + 1] - rgb[1]) ** 2 + (data[i + 2] - rgb[2]) ** 2;
      if (d < distance) { distance = d; best = name; }
    }
    found.add(best);
  }
  return PAINT_COLOURS.map(([name]) => name).filter(name => found.has(name));
}
function refreshAreas() {
  const colours = paintedColours(), single = colours.length === 1;
  $('paintAreaList').innerHTML = colours.map(name => {
    const hex = PAINT_COLOURS.find(([n]) => n === name)[1], action = single ? paint.actions[name] || 'remove' : 'change';
    const actions = single ? `<select data-area-action="${name}" aria-label="What to do">${PAINT_ACTIONS.map(([value, text]) =>
      `<option value="${value}"${value === action ? ' selected' : ''}>${text}</option>`).join('')}</select>` : '';
    return `<div class="paint-area"><span class="swatch" style="background:${hex}"></span><div class="fields">${actions}`
      + `<input data-area-text="${name}" value="${esc(paint.texts[name] || '')}" placeholder="${single ? PAINT_PLACEHOLDERS[action] : 'what goes in the ' + name + ' area'}" aria-label="What goes in the ${name} area"></div></div>`;
  }).join('') || '<div class="hint">Nothing painted yet.</div>';
  $('paintPromptSwatches').innerHTML = colours.map(name => `<i style="background:${PAINT_COLOURS.find(([n]) => n === name)[1]}"></i>`).join('');
}
$('paintPromptsOpen').addEventListener('click', () => {
  closePaintPops();
  refreshAreas();
  $('paintPrompts').showModal();
  const first = $('paintAreaList').querySelector('input');
  if (first) first.focus();
});
$('paintPromptsClose').addEventListener('click', () => $('paintPrompts').close());
$('paintAreaList').addEventListener('input', e => {
  if (e.target.dataset.areaText) paint.texts[e.target.dataset.areaText] = e.target.value;
});
$('paintAreaList').addEventListener('change', e => {
  if (!e.target.dataset.areaAction) return;
  paint.actions[e.target.dataset.areaAction] = e.target.value;
  refreshAreas();
});
$('paintColours').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('[data-paint-colour]');
  if (!button) return;
  paint.colour = button.dataset.paintColour;
  for (const other of $('paintColours').querySelectorAll('button')) other.classList.toggle('active', other === button);
  showPaintColour();
  closePaintPops();
});
for (const button of document.querySelectorAll('[data-paint-tool]')) button.addEventListener('click', () => {
  paint.tool = button.dataset.paintTool;
  for (const other of document.querySelectorAll('[data-paint-tool]')) other.classList.toggle('active', other === button);
});
$('paintUndo').addEventListener('click', () => {
  if (!paint || !paint.history.length) return;
  $('paintCanvas').getContext('2d').putImageData(paint.history.pop(), 0, 0);
  refreshAreas();
});
$('paintClear').addEventListener('click', () => {
  if (!paint) return;
  snapshot();
  const canvas = $('paintCanvas');
  canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  refreshAreas();
});
$('paintCancel').addEventListener('click', () => $('paintDialog').close());
// What stops the painting from being kept, said in the paint window itself, and in Colour prompts, where it's seen.
function paintError(text) {
  for (const id of ['paintError', 'paintPromptsError']) {
    $(id).textContent = text;
    $(id).hidden = !text;
  }
}
$('paintDone').addEventListener('click', async () => {
  const epoch = workspaceEpoch;
  try {
    const colours = paintedColours(), single = colours.length === 1;
    if (!colours.length) { paintError('Paint over what to change first.'); return; }
    const areas = colours.map(name => ({ colour: PAINT_COLOURS.find(([n]) => n === name)[1], action: single ? paint.actions[name] || 'remove' : 'change',
                                          text: (paint.texts[name] || '').trim() }));
    const missing = areas.find(area => !area.text && !(single && area.action === 'remove'));
    if (missing) {
      paintError(single ? 'Say what it changes to, what replaces it or what to add. Remove needs no words.'
                        : 'Say what goes in each colour.');
      if (!$('paintPrompts').open) $('paintPromptsOpen').click();
      return;
    }
    // Kept, so the window opens again as it was left.
    paint.canvas.getContext('2d').clearRect(0, 0, paint.canvas.width, paint.canvas.height);
    paint.canvas.getContext('2d').drawImage($('paintCanvas'), 0, 0);
    const blob = await new Promise(resolve => $('paintCanvas').toBlob(resolve, 'image/png'));
    if (epoch !== workspaceEpoch) return;
    if (!blob) throw new Error('The painting could not be read back.');
    putFile($('areasMask'), new File([blob], 'areas.png', { type: 'image/png' }));
    $('areasJson').value = JSON.stringify(areas);
    $('areasHint').textContent = single
      ? `${PAINT_ACTIONS.find(([value]) => value === areas[0].action)[1]}${areas[0].text ? ` ${areas[0].text}` : ' what is painted'}. Press Generate.`
      : `${areas.length} changes: ${areas.map(area => area.text).join('; ')}. Press Generate.`;
    paintError('');
    if ($('paintPrompts').open) $('paintPrompts').close();
    $('paintDialog').close();
  } catch (e) {
    if (epoch === workspaceEpoch) paintError(`Could not keep the painting: ${e.message || e}`);
  }
});
$('paintAreas').addEventListener('click', openPaint);
