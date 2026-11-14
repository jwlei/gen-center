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
  section.classList.toggle('scroll-below', (section.open || section.classList.contains('section-closing'))
    && body.scrollHeight - body.clientHeight - body.scrollTop > 1);
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
function setGenerationSection(section, open) {
  const form = section.closest('.pipeline-form');
  animateAccordionSections([...form.querySelectorAll('details.section')], () => {
    section.open = open;
    if (!open) return;
    form._activeSection = section;
    if (!keepSectionsOpen) {
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
  if (keepSectionsOpen) return;
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
