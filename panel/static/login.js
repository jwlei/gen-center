// Sent: it says so, and can't be sent twice, while the panel opens.
document.getElementById('loginForm').addEventListener('submit', e => {
  const form = e.currentTarget, button = document.getElementById('loginButton');
  if (form.classList.contains('busy')) { e.preventDefault(); return; }
  form.classList.add('busy');
  form.setAttribute('aria-busy', 'true');
  document.getElementById('loginLabel').textContent = 'Signing in…';
  // Disabled after it is sent, or the browser would not send it.
  setTimeout(() => { button.disabled = true; }, 0);
});
// Back from the browser's history, a page left busy would wait for nothing.
window.addEventListener('pageshow', () => {
  const form = document.getElementById('loginForm');
  form.classList.remove('busy');
  form.removeAttribute('aria-busy');
  document.getElementById('loginButton').disabled = false;
  document.getElementById('loginLabel').textContent = 'Sign in';
});
