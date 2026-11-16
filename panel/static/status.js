// Classic scripts share the page's lexical scope; no draft data leaves this page.
const statusCatalogue = (() => {
  const keys = ['videos', 'image_sets', 'collections', 'output_order'];
  let revision = '', catalogue = null;
  return {
    url() { return '/api/status?catalogue_revision=' + encodeURIComponent(revision); },
    hydrate(data) {
      if (typeof data.catalogue_revision !== 'string') return data; // Older servers.
      if (data.videos && Array.isArray(data.image_sets)) {
        catalogue = Object.fromEntries(keys.map(key => [key, data[key]]));
        revision = data.catalogue_revision;
      } else if (!catalogue || data.catalogue_revision !== revision) {
        revision = '';
        throw new Error('Output catalogue is out of sync. Retrying a full update.');
      }
      const merged = { ...catalogue, ...data };
      merged.image_sets = merged.image_sets.map(set => ({ ...set, generating: !!(
        data.running && data.pipeline === 'image' && data.progress && data.progress.run_id === set.id
      ) }));
      return merged;
    },
  };
})();

const panelConnection = (() => {
  // A status call that fails once (a panel restart, a slow reply) isn't worth a notice: it shows only after 5 s down.
  const DISCONNECTED_AFTER_MS = 5000;
  let lastSuccess = null, disconnectTimer = null, lastError = null;
  function show(message) {
    const notice = document.getElementById('connectionNotice');
    notice.hidden = false;
    document.getElementById('connectionMessage').textContent = message;
    document.body.classList.remove('page-loading');
  }
  // Loading, the same: "Connecting to the panel..." only if the first answer takes over 5 s.
  const connecting = setTimeout(() => { if (!lastSuccess) show('Connecting to the panel...'); }, DISCONNECTED_AFTER_MS);
  return {
    success() {
      lastSuccess = new Date();
      clearTimeout(connecting);
      clearTimeout(disconnectTimer);
      disconnectTimer = null;
      document.getElementById('connectionNotice').hidden = true;
    },
    failure(error) {
      lastError = error;
      if (disconnectTimer) return;
      disconnectTimer = setTimeout(() => {
        const last = lastSuccess ? ` Last update: ${lastSuccess.toLocaleTimeString()}.` : ' No status received yet.';
        show(`Panel disconnected. Retrying automatically.${last} ${lastError.message || 'Could not reach the panel.'}`);
      }, DISCONNECTED_AFTER_MS);
    },
    renderFailure(error) {
      show(`A page section could not update. Retry now or reload the page. ${error.message || ''}`);
    },
  };
})();
window.addEventListener('error', event => {
  if (event.message === 'ResizeObserver loop completed with undelivered notifications.'
      || event.message === 'ResizeObserver loop limit exceeded') {
    console.warn(event.message);
    return;
  }
  panelConnection.renderFailure(event.error || new Error(event.message));
  reportUncaught(event.error || new Error(event.message));
});
window.addEventListener('unhandledrejection', event => {
  panelConnection.renderFailure(event.reason || new Error('Unexpected page error.'));
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
