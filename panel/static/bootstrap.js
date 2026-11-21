document.body.classList.add('page-loading', 'output-pending', 'starting');
// Out of sight until every script has run (they all run before DOMContentLoaded, even one that throws): before that,
// each section and every button a script hides would flash by, which an app opening afresh each time shows every time.
document.addEventListener('DOMContentLoaded', () => requestAnimationFrame(() => document.body.classList.remove('starting')));
