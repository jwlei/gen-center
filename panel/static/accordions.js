// After a fold, a phone's browser left what slid into view at the top unpainted, black until the next scroll. It
// happens when the page shrinks under a scrolled screen and the browser pulls the scroll back itself.
// The page drawn again, once: a change of opacity for two frames, too small to see, makes it paint all of it.
function repaintPage() {
  document.body.style.opacity = '.999';
  requestAnimationFrame(() => requestAnimationFrame(() => { document.body.style.opacity = ''; }));
}
// Holds the page at its height before something folds away, so the scroll isn't pulled back mid-fold.
function holdHeight() {
  if (!document.body.style.minHeight) document.body.style.minHeight = `${document.documentElement.scrollHeight}px`;
}
// Lets the page take its new height. Scrolled past where it now ends, the page is scrolled there first, by us, so the
// browser never has to pull it back.
function releaseHeight() {
  const held = document.body.style.minHeight;
  if (!held) return;
  document.body.style.minHeight = '';
  const end = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  if (window.scrollY <= end) { repaintPage(); return; }
  document.body.style.minHeight = held;
  window.scrollTo(0, end);
  requestAnimationFrame(() => { document.body.style.minHeight = ''; repaintPage(); });
}
function updateSectionFade(section) {
  const body = section.querySelector('.section-body');
  const shown = section.open || section.classList.contains('section-closing');
  section.classList.toggle('scroll-below', shown && body.scrollHeight - body.clientHeight - body.scrollTop > 1);
  // And at the top, once it's scrolled down: what went up under the edge fades out there too.
  section.classList.toggle('scroll-above', shown && body.scrollTop > 1);
}
function animateAccordionSections(sections, change, onFinish = null) {
  const before = sections.map(section => {
    const generation = section.classList.contains('section');
    const closingClass = generation ? 'section-closing' : 'queue-closing';
    return { section, generation, closingClass, height: section.getBoundingClientRect().height,
      open: section.open || section._open || section.classList.contains(closingClass) };
  });
  for (const { section, closingClass } of before) {
    if (section._sectionAnimation) section._sectionAnimation.cancel();
    section.classList.remove(closingClass);
    section.style.flex = '';
    section.style.height = '';
  }
  change();
  const after = before.map(({ section }) => section.getBoundingClientRect().height);
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    before.filter(item => item.generation).forEach(({ section }) => updateSectionFade(section));
    if (onFinish) onFinish();
    return;
  }
  let remaining = 0, cancelled = false;
  before.forEach(({ section, generation, closingClass, height, open }, index) => {
    if (!height || !after[index] || Math.abs(height - after[index]) < 1) return;
    section.classList.toggle(closingClass, open && !(generation ? section.open : section._open));
    section.style.flex = '0 0 auto';
    section.style.height = `${after[index]}px`;
    const animation = section._sectionAnimation = section.animate(
      { height: [`${height}px`, `${after[index]}px`] }, { duration: 250, easing: 'ease-in-out' });
    remaining++;
    const finish = wasCancelled => {
      if (section._sectionAnimation !== animation) return;
      section._sectionAnimation = null;
      section.classList.remove(closingClass);
      section.style.flex = '';
      section.style.height = '';
      if (generation) updateSectionFade(section);
      cancelled ||= wasCancelled;
      if (!--remaining && !cancelled && onFinish) onFinish();
    };
    animation.onfinish = () => finish(false);
    animation.oncancel = () => finish(true);
  });
  before.filter(item => item.generation).forEach(({ section }) => updateSectionFade(section));
  if (!remaining && onFinish) onFinish();
}
// Keep sections open: on Shorts and Video only. Image doesn't offer the pin, so it always folds the others away.
function keepsOpen(form) { return keepSectionsOpen && form.id !== 'formImage'; }
function setGenerationSection(section, open) {
  const form = section.closest('.pipeline-form');
  animateAccordionSections([...form.querySelectorAll('details.section')], () => {
    section.open = open;
    if (!open) return;
    form._activeSection = section;
    if (!keepsOpen(form)) {
      for (const other of form.querySelectorAll('details.section')) if (other !== section) other.open = false;
    }
  });
}
function setQueueAccordionSection(section, open) {
  animateAccordionSections([...$('queueBox').querySelectorAll(':scope > .queue')], () => {
    setQueueSectionOpen(section, open);
    if (open) closeOtherQueues(section);
  }, () => { if (open && section._open) revealQueueSection(section); });
}
// A header opens and closes the way the queue does: its height moves, so what is below slides rather than jumps.
function foldDetails(details) {
  const summary = details.querySelector(':scope > summary');
  if (!summary) return;
  summary.addEventListener('click', e => {
    if (e.target.closest && e.target.closest('[data-no-fold]')) return;
    if (details.classList.contains('section')) {
      e.preventDefault();
      setGenerationSection(details, !details.open);
      return;
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setTimeout(() => { if (details.open) revealQueueSection(details); });
      return;
    }
    e.preventDefault();
    const opening = details._fold ? !details._wantOpen : !details.open;
    const start = details.getBoundingClientRect().height;
    if (details._fold) details._fold.cancel();
    // Closing, the page keeps its height until the fold is done: shrinking under the screen frame by frame made the
    // browser pull the scroll back each time, and what it hadn't painted yet showed black at the top.
    if (opening) document.body.style.minHeight = ''; else holdHeight();
    details.open = false;
    const closed = details.getBoundingClientRect().height;
    details.open = true;
    const end = opening ? details.getBoundingClientRect().height : closed;
    details._wantOpen = opening;
    details.classList.toggle('fold-opening', opening);
    details.style.overflow = 'hidden';
    const fold = details._fold = details.animate({ height: [`${start}px`, `${end}px`] }, { duration: 250, easing: 'ease' });
    fold.onfinish = () => {
      if (details._fold !== fold) return;
      details._fold = null;
      details.style.overflow = '';
      details.classList.remove('fold-opening');
      details.open = opening;
      // Opened, it comes to the top of the screen, as the queue's sections do.
      if (opening) revealQueueSection(details);
      else {
        // Closed, the page shrinks once, and the header stays in sight.
        releaseHeight();
        if (summary.getBoundingClientRect().top < 0) summary.scrollIntoView({ block: 'start' });
      }
    };
  });
}
function closeOtherSections(current) {
  const form = current.closest('.pipeline-form');
  form._activeSection = current;
  if (keepsOpen(form)) return;
  if ([...form.querySelectorAll('details.section')].some(section => section !== current && section.open)) {
    setGenerationSection(current, true);
  }
}
document.querySelectorAll('details.section').forEach(section => {
  const body = document.createElement('div');
  body.className = 'section-body';
  for (const child of [...section.childNodes]) {
    if (child.nodeName !== 'SUMMARY') body.appendChild(child);
  }
  section.appendChild(body);
  section.addEventListener('toggle', () => { if (section.open) closeOtherSections(section); });
  body.addEventListener('scroll', () => updateSectionFade(section), { passive: true });
  if (window.ResizeObserver) {
    const observer = new ResizeObserver(() => updateSectionFade(section));
    const observeContent = () => {
      observer.disconnect();
      observer.observe(body);
      for (const child of body.children) observer.observe(child);
      updateSectionFade(section);
    };
    observeContent();
    if (window.MutationObserver) new MutationObserver(observeContent).observe(body, { childList: true, subtree: true });
  }
});
try { keepSectionsOpen = localStorage.getItem('gen-center.keep-sections-open') === '1'; }
catch (e) { console.warn('Could not read the section preference:', e); }
$('keepSectionsOpen').setAttribute('aria-pressed', String(keepSectionsOpen));
$('keepSectionsOpen').addEventListener('click', e => {
  e.preventDefault();
  keepSectionsOpen = !keepSectionsOpen;
  $('keepSectionsOpen').setAttribute('aria-pressed', String(keepSectionsOpen));
  try { localStorage.setItem('gen-center.keep-sections-open', keepSectionsOpen ? '1' : '0'); }
  catch (error) { panelConnection.renderFailure(error); }
  if (!keepSectionsOpen) {
    for (const form of document.querySelectorAll('.pipeline-form')) {
      const current = form._activeSection?.open ? form._activeSection : form.querySelector('details.section[open]');
      if (current) closeOtherSections(current);
    }
  }
});
function sizeGenerationPanel() {
  const card = $('optionsCard');
  if (!card.getClientRects().length) return;
  const top = card.getBoundingClientRect().top + window.scrollY;
  const value = `${top}px`;
  if (card.style.getPropertyValue('--generate-top') !== value) card.style.setProperty('--generate-top', value);
}
window.addEventListener('resize', sizeGenerationPanel);
if (window.ResizeObserver) new ResizeObserver(sizeGenerationPanel).observe($('stick'));
if (window.MutationObserver) new MutationObserver(sizeGenerationPanel).observe(document.body, {
  attributes: true, attributeFilter: ['class', 'data-page'],
});
requestAnimationFrame(sizeGenerationPanel);
if (window.MutationObserver) {
  new MutationObserver(() => {
    for (const section of $('queueBox').querySelectorAll(':scope > .queue')) {
      const open = section.querySelector('.stopped-fold')?.open || !!section.querySelector('.queue-list:not([hidden])');
      section.classList.toggle('queue-open', !section.hidden && open);
    }
  }).observe($('queueBox'), { subtree: true, childList: true, attributes: true, attributeFilter: ['open', 'hidden'] });
}
document.querySelectorAll('details.section, details.h3-help').forEach(foldDetails);
// Collapsing a header (a section, the queue, Pending or Failed) makes the page shorter. Scrolled down, the browser
// then left the top of the screen black until the next scroll: what slid into view was never repainted. A scroll of
// 1px and back, a frame apart, has it paint, as scrolling by hand did.
if (window.ResizeObserver) {
  let lastHeight = document.documentElement.scrollHeight, nudging = false;
  new ResizeObserver(() => {
    const height = document.documentElement.scrollHeight;
    if (height < lastHeight && window.scrollY > 0 && !nudging) {
      nudging = true;
      requestAnimationFrame(() => {
        const y = window.scrollY;
        window.scrollTo(0, Math.max(0, y - 1));
        requestAnimationFrame(() => { window.scrollTo(0, y); nudging = false; });
        repaintPage();
      });
    }
    lastHeight = height;
  }).observe(document.body);
}
// --- On a phone: one generation section at a time, chosen in the bar over Generate ---
// The model and preset part stays on top; the bar names the sections (their headers keep only their buttons), and the
// one chosen slides in from the side of its button. A wide screen keeps them all, as headers that fold.
const SECTION_TABS = window.matchMedia('(max-width: 999.98px)'), SECTION_TAB_KEY = 'gen-center.section-tab.';
function sectionLabel(section) {
  const summary = section.querySelector(':scope > summary');
  return summary ? [...summary.childNodes].filter(node => node.nodeType === 3).map(node => node.textContent).join('').trim() : '';
}
function shownForm() { return [...document.querySelectorAll('#optionsCard .pipeline-form')].find(form => form.getClientRects().length) || null; }
function tabSections(form) { return [...form.querySelectorAll('details.section')].filter(section => !section.hidden); }
function chosenTab(form, sections) {
  if (!form._tab) try { form._tab = form.querySelector(`#${CSS.escape(localStorage.getItem(SECTION_TAB_KEY + form.id) || '')}`); } catch (e) {}
  return sections.includes(form._tab) ? form._tab : sections[0];
}
function syncSectionBar() {
  const phone = SECTION_TABS.matches, form = phone ? shownForm() : null;
  document.body.classList.toggle('section-tabs-on', phone);
  $('sectionBar').hidden = !form || document.body.dataset.page !== 'generate';
  if (!form) return;
  const sections = tabSections(form), current = chosenTab(form, sections);
  const key = JSON.stringify([form.id, sections.map(section => section.id || sectionLabel(section))]);
  if ($('sectionTabs').dataset.key !== key) {
    $('sectionTabs').dataset.key = key;
    $('sectionTabs').innerHTML = sections.map((section, index) =>
      `<button type="button" role="tab" data-tab="${index}">${esc(sectionLabel(section))}</button>`).join('');
  }
  for (const section of form.querySelectorAll('details.section')) section.classList.toggle('tab-hidden', section !== current);
  // Others closed first, so opening this one has nothing to fold away.
  for (const section of sections) if (section !== current && section.open) section.open = false;
  if (current && !current.open) current.open = true;
  const buttons = [...$('sectionTabs').querySelectorAll('button')];
  buttons.forEach((button, index) => button.setAttribute('aria-selected', String(sections[index] === current)));
  placeUnderline($('sectionGlider'), buttons[sections.indexOf(current)], $('sectionBar'));
}
// The section at index in the bar, shown: tapped, it slides in from the side of its button; pulled to from the end of
// the one before or after (pullSections), from below or above. Whether it changed.
function showSectionTab(index, way = 'side') {
  const form = shownForm();
  if (!form) return false;
  const sections = tabSections(form), next = sections[index], before = sections.indexOf(chosenTab(form, sections));
  if (!next || before === index) return false;
  form._tab = next;
  if (next.id) try { localStorage.setItem(SECTION_TAB_KEY + form.id, next.id); } catch (error) {}
  syncSectionBar();
  // Further along: from the right (or below); back: from the left (or above).
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && next.animate) {
    const from = `${way === 'side' ? 'translateX' : 'translateY'}(${index > before ? '24%' : '-24%'})`;
    next.animate([{ transform: from, opacity: 0 }, { transform: 'none', opacity: 1 }],
                 { duration: 260, easing: 'cubic-bezier(.3, .7, .3, 1)' });
  }
  return true;
}
$('sectionTabs').addEventListener('click', e => {
  const button = e.target.closest && e.target.closest('[data-tab]');
  if (button) showSectionTab(+button.dataset.tab);
});
// Pulled on past the end of a section, a finger goes on to the next one; past its top, back to the one before, at its
// end. Only a pull that starts there, at the end already: a scroll that runs into it stops there, as ever. The section
// gives a little as it's pulled, so the pull is felt before it's let go.
const SECTION_PULL = 80;
let sectionPull = null;
function pullSections(e) {
  sectionPull = null;
  if (!document.body.classList.contains('section-tabs-on') || document.body.dataset.page !== 'generate' || e.touches.length !== 1) return;
  const target = e.target, body = target.closest && target.closest('#optionsCard details.section[open] > .section-body');
  if (!body || target.closest('textarea, select, [contenteditable], .shots-list, dialog')) return;
  const top = body.scrollTop <= 1, bottom = body.scrollTop + body.clientHeight >= body.scrollHeight - 1;
  if (top || bottom) sectionPull = { body, y: e.touches[0].clientY, top, bottom, by: 0 };
}
function pulling(e) {
  const pull = sectionPull;
  if (!pull) return;
  if (e.touches.length !== 1) { letGoSections(); return; }
  const dy = e.touches[0].clientY - pull.y;
  // Up past the end (dy < 0) or down past the top (dy > 0), and still there; the other way is an ordinary scroll.
  pull.by = (dy < 0 && pull.bottom) || (dy > 0 && pull.top) ? dy : 0;
  pull.body.style.transition = '';
  pull.body.style.transform = pull.by ? `translateY(${Math.max(-40, Math.min(40, pull.by * 0.35))}px)` : '';
}
function letGoSections() {
  const pull = sectionPull;
  sectionPull = null;
  if (!pull) return;
  // Eased back into place, not snapped.
  pull.body.style.transition = 'transform .2s ease';
  pull.body.style.transform = '';
  setTimeout(() => { pull.body.style.transition = ''; }, 220);
  if (Math.abs(pull.by) < SECTION_PULL) return;
  const form = shownForm();
  if (!form) return;
  const sections = tabSections(form), at = sections.indexOf(chosenTab(form, sections)), index = at + (pull.by < 0 ? 1 : -1);
  if (!showSectionTab(index, 'pull')) return;
  // Onward at its start; back at its end, where it was left off coming the other way.
  const body = sections[index].querySelector(':scope > .section-body');
  if (body) body.scrollTop = pull.by < 0 ? 0 : body.scrollHeight;
}
$('optionsCard').addEventListener('touchstart', pullSections, { passive: true });
$('optionsCard').addEventListener('touchmove', pulling, { passive: true });
$('optionsCard').addEventListener('touchend', letGoSections, { passive: true });
$('optionsCard').addEventListener('touchcancel', () => { if (sectionPull) sectionPull.body.style.transform = ''; sectionPull = null; }, { passive: true });
SECTION_TABS.addEventListener('change', () => { $('sectionGlider').dataset.place = ''; syncSectionBar(); });
window.addEventListener('resize', () => { $('sectionGlider').dataset.place = ''; syncSectionBar(); });
if (window.MutationObserver) {
  // Another page or side, or a section shown or hidden (Workflow has none to show for some workflows).
  new MutationObserver(syncSectionBar).observe(document.body, { attributes: true, attributeFilter: ['class', 'data-page'] });
  new MutationObserver(syncSectionBar).observe($('optionsCard'), { subtree: true, attributes: true, attributeFilter: ['hidden'] });
}
requestAnimationFrame(syncSectionBar);
