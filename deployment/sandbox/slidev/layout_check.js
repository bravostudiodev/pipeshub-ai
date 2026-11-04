// Injected by build_deck.py into a throwaway copy of the deck opened at
// `?print#/print`, where Slidev renders every slide with all clicks revealed.
// Writes a JSON report of text that leaves its slide, is clipped by a box, or
// overlaps other text, for headless Chromium's --dump-dom to hand back.
(() => {
  const TOLERANCE = 2;
  const IGNORE = '[data-layout-ignore]';

  const label = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60);

  const textRects = (el) => {
    const rects = [];
    for (const node of el.childNodes) {
      if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        if (rect.width > 0 && rect.height > 0) rects.push(rect);
      }
    }
    return rects;
  };

  const bounds = (rects) => ({
    left: Math.min(...rects.map((r) => r.left)),
    top: Math.min(...rects.map((r) => r.top)),
    right: Math.max(...rects.map((r) => r.right)),
    bottom: Math.max(...rects.map((r) => r.bottom)),
  });

  const overflow = (inner, outer) => ({
    left: outer.left - inner.left,
    top: outer.top - inner.top,
    right: inner.right - outer.right,
    bottom: inner.bottom - outer.bottom,
  });

  const worst = (sides) => Object.entries(sides).sort((a, b) => b[1] - a[1])[0];

  // Tight line boxes of stacked text touch slightly; count an overlap only
  // when it covers a real part of a line.
  const overlaps = (a, b, scale) => a.some((r) => b.some((s) => {
    const width = Math.min(r.right, s.right) - Math.max(r.left, s.left);
    const height = Math.min(r.bottom, s.bottom) - Math.max(r.top, s.top);
    return width > 4 * scale && height > 0.25 * Math.min(r.height, s.height);
  }));

  const visible = (el) => !el.checkVisibility
    || el.checkVisibility({ opacityProperty: true, visibilityProperty: true });

  const checkSlide = (slide) => {
    const box = slide.getBoundingClientRect();
    const scale = box.width / (parseFloat(slide.style.width) || box.width);
    const no = parseInt(slide.id, 10);
    const issues = [];
    const items = [];
    for (const el of slide.querySelectorAll('*')) {
      if (el.closest(IGNORE) || !visible(el)) continue;
      const rects = textRects(el);
      if (rects.length) items.push({ el, rects, svg: !!el.closest('svg') });
    }
    for (const { el, rects } of items) {
      const text = bounds(rects);
      const [side, px] = worst(overflow(text, box));
      if (px > TOLERANCE * scale) {
        issues.push({ slide: no, kind: 'outside', text: label(el), side, px: Math.round(px / scale) });
        continue;
      }
      for (let parent = el; parent && parent !== slide; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (style.overflowX === 'visible' && style.overflowY === 'visible') continue;
        const [, cut] = worst(overflow(text, parent.getBoundingClientRect()));
        if (cut > TOLERANCE * scale) {
          issues.push({ slide: no, kind: 'clipped', text: label(el), px: Math.round(cut / scale) });
          break;
        }
      }
    }
    // Diagram labels inside SVG are laid out by their renderer; only HTML text is compared.
    const html = items.filter((item) => !item.svg);
    for (let i = 0; i < html.length; i += 1) {
      for (let j = i + 1; j < html.length; j += 1) {
        const a = html[i];
        const b = html[j];
        if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
        if (overlaps(a.rects, b.rects, scale)) {
          issues.push({ slide: no, kind: 'overlap', text: label(a.el), other: label(b.el) });
        }
      }
    }
    return issues;
  };

  const report = (data) => {
    const pre = document.createElement('pre');
    pre.id = 'oddjeeves-layout-report';
    pre.textContent = JSON.stringify(data);
    document.body.appendChild(pre);
  };

  const run = () => {
    const slides = [...document.querySelectorAll('.print-slide-container')];
    try {
      report({ slides: slides.length, issues: slides.flatMap(checkSlide) });
    } catch (error) {
      report({ error: String(error) });
    }
  };

  const started = performance.now();
  const wait = () => {
    if (!document.querySelector('.print-slide-container') && performance.now() - started < 20000) {
      setTimeout(wait, 200);
      return;
    }
    // Let fonts load and v-motion entrances settle before measuring.
    document.fonts.ready.then(() => setTimeout(run, 2000));
  };
  addEventListener('load', wait);
})();
