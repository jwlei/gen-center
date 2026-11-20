// Classic scripts share the page's lexical scope; no draft data leaves this page.
const statusCatalogue = (() => {
  const keys = ['videos', 'image_sets', 'collections', 'output_order'];
  // The sets as the page uses them, kept while neither the catalogue nor the set being made changes: each update (every
  // 2 s) once made all of them anew, and Output's lists worked out again from those, for nothing.
  let revision = '', catalogue = null, sets = null, setsFor = '';
  return {
    url() { return '/api/status?catalogue_revision=' + encodeURIComponent(revision); },
    revision() { return revision; },
    hydrate(data) {
      if (typeof data.catalogue_revision !== 'string') return data; // Older servers.
      if (data.videos && Array.isArray(data.image_sets)) {
        catalogue = Object.fromEntries(keys.map(key => [key, data[key]]));
        revision = data.catalogue_revision;
        sets = null;
      } else if (!catalogue || data.catalogue_revision !== revision) {
        revision = '';
        throw new Error('Output catalogue is out of sync. Retrying a full update.');
      }
      const making = data.running && data.pipeline === 'image' && data.progress ? data.progress.run_id : null;
      if (!sets || setsFor !== String(making)) {
        sets = catalogue.image_sets.map(set => ({ ...set, generating: making !== null && making === set.id }));
        setsFor = String(making);
      }
      return { ...catalogue, ...data, image_sets: sets };
    },
  };
})();

const panelConnection = (() => {
  // A status call that fails for a while (a panel restart, a slow reply, the phone's network waking) isn't worth a
  // notice: it shows only after 30 s down. A page error waits 30 s too: a section that fails to draw shows only if it
  // is still failing then (drawn again with every answer, a gap of RENDER_GAP_MS without a failure means it recovered),
  // and the notice goes once it has gone that long without one; an error that happened once shows then regardless.
  const DISCONNECTED_AFTER_MS = 30000, RENDER_GAP_MS = 10000;
  let lastSuccess = null, disconnectTimer = null, lastError = null, wokeAt = 0, shown = null;
  let renderTimer = null, renderLast = 0, renderError = null, renderOnce = false;
  function show(message, kind = 'render') {
    const notice = document.getElementById('connectionNotice');
    notice.hidden = false;
    document.getElementById('connectionMessage').textContent = message;
    document.body.classList.remove('page-loading');
    shown = kind;
  }
  function disconnected() {
    // Hidden, or back less than 30 s ago (a timer frozen with the page goes off as soon as it's back): not yet.
    const since = Date.now() - wokeAt;
    if (document.hidden) return;
    if (since < DISCONNECTED_AFTER_MS) { disconnectTimer = setTimeout(disconnected, DISCONNECTED_AFTER_MS - since); return; }
    const last = lastSuccess ? ` Last update: ${lastSuccess.toLocaleTimeString()}.` : ' No status received yet.';
    show(`Panel disconnected. Retrying automatically.${last} ${(lastError && lastError.message) || 'Could not reach the panel.'}`, 'disconnected');
  }
  // The page back in sight (the browser opened again, the phone unlocked): its connection is waking too. Whatever
  // failed while it was away, the notice waits 30 s more from now, and one already up goes until then.
  function wake() {
    wokeAt = Date.now();
    if (shown === 'disconnected') {
      document.getElementById('connectionNotice').hidden = true;
      shown = null;
    }
    if (lastError) {
      clearTimeout(disconnectTimer);
      disconnectTimer = setTimeout(disconnected, DISCONNECTED_AFTER_MS);
    }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) wake(); });
  window.addEventListener('pageshow', event => { if (event.persisted) wake(); });
  // Loading, the same: "Connecting to the panel..." only if the first answer takes over 30 s.
  const connecting = setTimeout(() => { if (!lastSuccess) show('Connecting to the panel...'); }, DISCONNECTED_AFTER_MS);
  return {
    success() {
      // Back after the notice said disconnected: what happened goes to the panel's page error log now that it can be
      // reached, so a run of them can be told apart afterwards (a restart, the network, a slow reply).
      if (shown === 'disconnected') {
        const away = lastSuccess ? Math.round((Date.now() - lastSuccess) / 1000) : null;
        const text = `disconnected | since ${lastSuccess ? lastSuccess.toLocaleTimeString() : 'loading'}${away != null ? ` (${away}s)` : ''} | ${(lastError && lastError.message) || 'no reply'}`;
        try { fetch('/api/page-error', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ error: text }) }).catch(() => {}); } catch (_) {}
      }
      lastSuccess = new Date();
      clearTimeout(connecting);
      clearTimeout(disconnectTimer);
      disconnectTimer = null;
      lastError = null;
      // A section still failing to draw keeps its notice: each answer is drawn after this, and would show it again.
      if (shown === 'render' && Date.now() - renderLast < RENDER_GAP_MS) return;
      document.getElementById('connectionNotice').hidden = true;
      shown = null;
    },
    failure(error) {
      lastError = error;
      if (disconnectTimer) return;
      disconnectTimer = setTimeout(disconnected, DISCONNECTED_AFTER_MS);
    },
    wake,
    // once: an error that happened once (uncaught), not a section drawn again with every answer.
    renderFailure(error, once = false) {
      renderLast = Date.now();
      renderError = error;
      renderOnce = renderOnce || once;
      if (shown === 'render') { show(`A page section could not update. Retry now or reload the page. ${error.message || ''}`); return; }
      if (renderTimer) return;
      renderTimer = setTimeout(() => {
        renderTimer = null;
        const still = renderOnce || Date.now() - renderLast < RENDER_GAP_MS;
        renderOnce = false;
        if (still) show(`A page section could not update. Retry now or reload the page. ${(renderError && renderError.message) || ''}`);
      }, DISCONNECTED_AFTER_MS);
    },
    // Whether the notice is still up, for Retry to say how it went.
    showing() { return !document.getElementById('connectionNotice').hidden; },
  };
})();
window.addEventListener('error', event => {
  if (event.message === 'ResizeObserver loop completed with undelivered notifications.'
      || event.message === 'ResizeObserver loop limit exceeded') {
    console.warn(event.message);
    return;
  }
  panelConnection.renderFailure(event.error || new Error(event.message), true);
  reportUncaught(event.error || new Error(event.message));
});
window.addEventListener('unhandledrejection', event => {
  panelConnection.renderFailure(event.reason || new Error('Unexpected page error.'), true);
  reportUncaught(event.reason || new Error('Unexpected page error.'));
});
// An error no part of the page caught (a tap's handler, say) goes to the panel's page error log too, once each, as
// polling.js's safely() sends what a redraw threw: from a phone, there's no console to read it in.
const uncaughtSent = new Set();
function reportUncaught(e) {
  const text = ['uncaught', e && e.message, ...String(e && e.stack || '').split('\n').slice(0, 4)].join(' | ');
  if (uncaughtSent.has(text)) return;
  uncaughtSent.add(text);
  try { fetch('/api/page-error', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ error: text }) }).catch(() => {}); } catch (_) {}
}
