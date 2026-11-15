// --- Temperatures (Settings → GPU heat guard → Temperatures): GPU and CPU over time, lowest, average and highest ---
// Each sensor is its average line over a shaded band from its lowest to its highest reading in that stretch; the heat
// guard's restart and cool-down temperatures are the dashed lines. Data: /api/temperatures (panel/temperatures.py).
const tempDialog = $('tempDialog');
const TEMP_SENSORS = [{ key: 'gpu', label: 'GPU', color: 'var(--temp-gpu)' }, { key: 'cpu', label: 'CPU', color: 'var(--temp-cpu)' }];
const TEMP_HEIGHT = 240, TEMP_MARGIN = { top: 10, right: 40, bottom: 22, left: 34 };
let tempHours = 6, tempData = null, tempTimer = null, tempLoading = false;

function tempDegrees(value) { return value == null ? '—' : `${Math.round(value)}°`; }
function tempTime(t, withDay) {
  const date = new Date(t * 1000);
  const clock = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return withDay ? `${date.toLocaleDateString([], { weekday: 'short' })} ${clock}` : clock;
}

async function loadTemperatures() {
  if (tempLoading) return;
  tempLoading = true;
  try {
    const response = await fetch(`/api/temperatures?hours=${tempHours}`);
    const body = await response.json();
    if (!body.ok) throw new Error(body.error || 'Could not load the temperatures.');
    tempData = body;
    renderTemperatures();
  } catch (error) {
    $('tempNote').hidden = false;
    $('tempNote').textContent = error.message || 'Could not reach the panel.';
  } finally { tempLoading = false; }
}

function renderTemperatures() {
  const data = tempData, summary = data.summary || {};
  $('tempTiles').innerHTML = TEMP_SENSORS.map(({ key, label }) => {
    const s = summary[key];
    return `<div class="temp-tile"><div class="temp-tile-head"><i class="temp-key temp-key-${key}"></i>${label} now</div>
      <div class="temp-reading"><div class="temp-now">${s ? tempDegrees(s.now) + 'C' : '—'}</div>
      <div class="temp-stats"><span>Min <b>${tempDegrees(s && s.min)}</b></span><span>Avg <b>${tempDegrees(s && s.avg)}</b></span><span>Max <b>${tempDegrees(s && s.max)}</b></span></div></div></div>`;
  }).join('');
  const notes = [];
  if (!summary.cpu) notes.push('No CPU temperature: it comes from MSI Afterburner, with CPU temperature monitoring switched on in its settings.');
  if (!summary.gpu) notes.push('No GPU temperature: nvidia-smi gave none.');
  $('tempNote').hidden = !notes.length;
  $('tempNote').textContent = notes.join(' ');
  drawTemperatureChart();
  const withDay = data.hours > 24;
  $('tempTable').innerHTML = '<thead><tr><th>Time</th><th>GPU min</th><th>GPU avg</th><th>GPU max</th><th>CPU min</th><th>CPU avg</th><th>CPU max</th></tr></thead><tbody>'
    + data.points.slice().reverse().map(p => `<tr><td>${esc(tempTime(p.t, withDay))}</td>${TEMP_SENSORS.map(({ key }) =>
      (p[key] || [null, null, null]).map(v => `<td>${tempDegrees(v)}</td>`).join('')).join('')}</tr>`).join('') + '</tbody>';
}

function drawTemperatureChart() {
  const data = tempData, box = $('tempChart');
  if (!data.points.length) {
    box.innerHTML = '<div class="hint">No readings yet: they are taken every few seconds while the panel runs.</div>';
    return;
  }
  const width = Math.max(280, box.clientWidth || 640), m = TEMP_MARGIN;
  const plotW = width - m.left - m.right, plotH = TEMP_HEIGHT - m.top - m.bottom;
  const guard = data.guard || {};
  const values = data.points.flatMap(p => TEMP_SENSORS.flatMap(({ key }) => p[key] ? [p[key][0], p[key][2]] : []));
  if (guard.on) values.push(guard.restart_above, guard.rearm_at);
  const low = Math.floor((Math.min(...values) - 2) / 5) * 5, high = Math.ceil((Math.max(...values) + 2) / 5) * 5;
  const x = t => m.left + (t - data.start) / (data.end - data.start) * plotW;
  const y = v => m.top + (high - v) / (high - low) * plotH;
  const parts = [];
  // Recessive grid: a line every 5 or 10 degrees.
  const every = high - low > 40 ? 10 : 5;
  for (let v = low; v <= high; v += every) {
    parts.push(`<line x1="${m.left}" x2="${width - m.right}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-width="1"/>`,
               `<text x="${m.left - 6}" y="${y(v) + 4}" text-anchor="end">${v}°</text>`);
  }
  const withDay = data.hours > 24, ticks = 5;
  for (let i = 0; i <= ticks; i++) {
    const t = data.start + (data.end - data.start) * i / ticks;
    parts.push(`<text x="${x(t)}" y="${TEMP_HEIGHT - 4}" text-anchor="${i === 0 ? 'start' : i === ticks ? 'end' : 'middle'}">${esc(tempTime(t, withDay))}</text>`);
  }
  if (guard.on) {
    for (const [v, name] of [[guard.restart_above, 'restart'], [guard.rearm_at, 'cool']]) {
      parts.push(`<line x1="${m.left}" x2="${width - m.right}" y1="${y(v)}" y2="${y(v)}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="4 4"/>`,
                 `<text x="${width - m.right + 4}" y="${y(v) + 4}">${name}</text>`);
    }
  }
  // Runs of points without a gap: the panel was off in between, and the line doesn't pretend otherwise.
  const runs = key => {
    const out = [];
    let run = [];
    for (const p of data.points) {
      if (!p[key] || (run.length && p.t - run[run.length - 1].t > data.step * 2.5)) { if (run.length) out.push(run); run = []; }
      if (p[key]) run.push(p);
    }
    if (run.length) out.push(run);
    return out;
  };
  const ends = [];
  for (const { key, color } of TEMP_SENSORS) {
    for (const run of runs(key)) {
      const mid = p => x(p.t + data.step / 2);
      const top = run.map(p => `${mid(p)},${y(p[key][2])}`), bottom = run.slice().reverse().map(p => `${mid(p)},${y(p[key][0])}`);
      parts.push(`<polygon points="${top.concat(bottom).join(' ')}" fill="${color}" fill-opacity=".18"/>`);
      parts.push(run.length > 1
        ? `<polyline points="${run.map(p => `${mid(p)},${y(p[key][1])}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`
        : `<circle cx="${mid(run[0])}" cy="${y(run[0][key][1])}" r="3" fill="${color}"/>`);
    }
    const last = data.points.filter(p => p[key]).pop();
    if (last) ends.push({ key, label: TEMP_SENSORS.find(s => s.key === key).label, y: y(last[key][1]) });
  }
  // Direct labels at the line ends, nudged apart when the two lines end close together.
  ends.sort((a, b) => a.y - b.y);
  if (ends.length === 2 && ends[1].y - ends[0].y < 13) { const centre = (ends[0].y + ends[1].y) / 2; ends[0].y = centre - 7; ends[1].y = centre + 7; }
  for (const end of ends) parts.push(`<text class="temp-label" x="${width - m.right + 4}" y="${end.y + 4}">${end.label}</text>`);
  parts.push(`<line id="tempCrosshair" x1="0" x2="0" y1="${m.top}" y2="${m.top + plotH}" stroke="var(--muted)" stroke-width="1" visibility="hidden"/>`);
  parts.push(TEMP_SENSORS.map(({ key, color }) => `<circle id="tempDot-${key}" r="4" fill="${color}" stroke="var(--panel)" stroke-width="2" visibility="hidden"/>`).join(''));
  parts.push(`<rect id="tempHit" x="${m.left}" y="${m.top}" width="${plotW}" height="${plotH}" fill="transparent"/>`);
  box.innerHTML = `<svg viewBox="0 0 ${width} ${TEMP_HEIGHT}" role="img" aria-label="GPU and CPU temperature over the last ${data.hours > 24 ? '7 days' : data.hours + ' hours'}">${parts.join('')}</svg>`;
  const hit = $('tempHit');
  if (!hit || !hit.addEventListener) return;
  hit.addEventListener('pointermove', event => showTemperatureAt(event, { x, y, width, plotW }));
  hit.addEventListener('pointerleave', hideTemperatureTip);
}

// Hover: a hairline at the nearest stretch, and its readings in a tooltip.
function showTemperatureAt(event, scale) {
  const data = tempData, svg = $('tempChart').querySelector('svg');
  const rect = svg.getBoundingClientRect(), px = (event.clientX - rect.left) * scale.width / rect.width;
  let nearest = null, distance = Infinity;
  for (const p of data.points) {
    const d = Math.abs(scale.x(p.t + data.step / 2) - px);
    if (d < distance) { distance = d; nearest = p; }
  }
  if (!nearest) return;
  const cx = scale.x(nearest.t + data.step / 2), line = $('tempCrosshair');
  line.setAttribute('x1', cx); line.setAttribute('x2', cx); line.setAttribute('visibility', 'visible');
  for (const { key } of TEMP_SENSORS) {
    const dot = $(`tempDot-${key}`);
    if (!nearest[key]) { dot.setAttribute('visibility', 'hidden'); continue; }
    dot.setAttribute('cx', cx); dot.setAttribute('cy', scale.y(nearest[key][1])); dot.setAttribute('visibility', 'visible');
  }
  const minutes = data.step / 60;
  const tip = $('tempTip');
  tip.innerHTML = `<div class="temp-tip-time">${esc(tempTime(nearest.t, data.hours > 24))}${minutes > 1 ? ` · ${minutes} min` : ''}</div>`
    + TEMP_SENSORS.map(({ key, label }) => nearest[key]
      ? `<div class="temp-tip-row"><i class="temp-key temp-key-${key}"></i>${label} <b>${tempDegrees(nearest[key][1])}</b> (${tempDegrees(nearest[key][0])}–${tempDegrees(nearest[key][2])})</div>` : '').join('');
  tip.hidden = false;
  const left = rect.left + cx * rect.width / scale.width;
  tip.style.left = `${Math.min(window.innerWidth - tip.offsetWidth - 8, Math.max(8, left + 12))}px`;
  tip.style.top = `${Math.max(8, event.clientY - tip.offsetHeight - 12)}px`;
}
function hideTemperatureTip() {
  $('tempTip').hidden = true;
  const line = $('tempCrosshair');
  if (line) line.setAttribute('visibility', 'hidden');
  for (const { key } of TEMP_SENSORS) { const dot = $(`tempDot-${key}`); if (dot) dot.setAttribute('visibility', 'hidden'); }
}

$('openTemperatures').addEventListener('click', () => {
  $('tempNote').hidden = true;
  tempDialog.showModal();
  loadTemperatures();
  clearInterval(tempTimer);
  tempTimer = setInterval(loadTemperatures, 30000);  // A new minute's bucket shows while it stays open
});
tempDialog.addEventListener('close', () => { clearInterval(tempTimer); tempTimer = null; hideTemperatureTip(); });
$('tempClose').addEventListener('click', () => tempDialog.close());
tempDialog.addEventListener('click', event => {
  if (event.target === tempDialog) { tempDialog.close(); return; }
  const range = event.target.closest ? event.target.closest('[data-hours]') : null;
  if (!range) return;
  tempHours = Number(range.dataset.hours);
  for (const button of tempDialog.querySelectorAll('[data-hours]')) button.setAttribute('aria-pressed', String(button === range));
  loadTemperatures();
});
window.addEventListener('resize', () => { if (tempDialog.open && tempData) drawTemperatureChart(); });
