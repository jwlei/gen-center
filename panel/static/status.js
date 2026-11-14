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
  let lastSuccess = null;
  function show(message) {
    const notice = document.getElementById('connectionNotice');
    notice.hidden = false;
    document.getElementById('connectionMessage').textContent = message;
    document.body.classList.remove('page-loading');
  }
  return {
    success() {
      lastSuccess = new Date();
      document.getElementById('connectionNotice').hidden = true;
    },
    failure(error) {
      const last = lastSuccess ? ` Last update: ${lastSuccess.toLocaleTimeString()}.` : ' No status received yet.';
      show(`Panel disconnected. Retrying automatically.${last} ${error.message || 'Could not reach the panel.'}`);
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
});
window.addEventListener('unhandledrejection', event => panelConnection.renderFailure(event.reason || new Error('Unexpected page error.')));
