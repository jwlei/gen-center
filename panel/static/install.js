// The panel as an app on a phone (panel/routes/install.py): its service worker, which shows a page of its own when
// the panel can't be reached. Browsers only allow one over HTTPS (the app address) or on this PC, so elsewhere,
// on the plain http:// address, there's nothing to do.
if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}
