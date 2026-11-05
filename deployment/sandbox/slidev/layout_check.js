// Injected by build_deck.py into a throwaway copy of the deck opened at
// `?print#/print`, where Slidev renders every slide with all clicks revealed.
// Writes a JSON report for headless Chromium's --dump-dom to hand back:
// text that leaves its slide, is clipped, overlaps other text, or has too
// little contrast; images that leave the slide; and OddBytes logos whose
// variant does not suit the background behind them.
//
// build_deck.py prepends `window.__oddjeevesBrand = {svg: {normalizedSvgText:
// variant}, png: {base64Prefix: variant}}` so logos can be recognised after
// inlining turned every file reference into a data: URI.
(() => {
  const TOLERANCE = 2;
  const MIN_CONTRAST = 3;
  const IGNORE = '[data-layout-ignore]';
  const brand = window.__oddjeevesBrand || { svg: {}, png: {} };

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

  const parseColor = (value) => {
    const match = /rgba?\(([^)]+)\)/.exec(value || '');
    if (!match) return null;
    const parts = match[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
    if (parts.length < 3 || parts.some(Number.isNaN)) return null;
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };

  const blend = (top, under) => ({
    r: top.a * top.r + (1 - top.a) * under.r,
    g: top.a * top.g + (1 - top.a) * under.g,
    b: top.a * top.b + (1 - top.a) * under.b,
    a: 1,
  });

  const luminance = ({ r, g, b }) => {
    const channel = (v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : (((c + 0.055) / 1.055) ** 2.4);
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };

  const contrast = (a, b) => {
    const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (light + 0.05) / (dark + 0.05);
  };

  // Solid colour painted behind `el` by its ancestors up to the slide; null
  // when an image or gradient is in the way, since its colour is unknown.
  const backgroundBehind = (el, slide) => {
    const layers = [];
    for (let node = el.parentElement; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage && style.backgroundImage !== 'none') return null;
      const color = parseColor(style.backgroundColor);
      if (color && color.a > 0) {
        layers.push(color);
        if (color.a >= 1) break;
      }
      if (node === slide) break;
    }
    let result = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = layers.length - 1; i >= 0; i -= 1) result = blend(layers[i], result);
    return result;
  };

  const ownBackground = (el) => {
    const color = parseColor(getComputedStyle(el).backgroundColor);
    return color && color.a > 0 ? color : null;
  };

  const decodeDataUri = (uri) => {
    const comma = uri.indexOf(',');
    if (comma < 0) return null;
    const header = uri.slice(0, comma);
    const payload = uri.slice(comma + 1);
    if (!header.startsWith('data:image/svg+xml')) {
      return header.includes('image/png') ? { png: payload.slice(0, 120) } : null;
    }
    try {
      const text = header.includes(';base64') ? atob(payload) : decodeURIComponent(payload);
      return { svg: text.replace(/\s+/g, '') };
    } catch (error) {
      return null;
    }
  };

  const logoVariant = (uri) => {
    if (!uri || !uri.startsWith('data:')) return null;
    const decoded = decodeDataUri(uri);
    if (!decoded) return null;
    if (decoded.svg !== undefined) return brand.svg[decoded.svg] || null;
    return brand.png[decoded.png] || null;
  };

  const imageSources = (el) => {
    const sources = [];
    if (el.tagName === 'IMG' && (el.currentSrc || el.src)) sources.push(el.currentSrc || el.src);
    const image = getComputedStyle(el).backgroundImage;
    const match = /url\(["']?(data:[^"')]+)["']?\)/.exec(image || '');
    if (match) sources.push(match[1]);
    return sources;
  };

  const checkSlide = (slide) => {
    const box = slide.getBoundingClientRect();
    const scale = box.width / (parseFloat(slide.style.width) || box.width);
    const no = parseInt(slide.id, 10);
    const issues = [];
    const items = [];

    for (const el of slide.querySelectorAll('*')) {
      if (el.closest(IGNORE) || !visible(el)) continue;

      for (const source of imageSources(el)) {
        const variant = logoVariant(source);
        if (!variant) continue;
        const behind = ownBackground(el) && el.tagName !== 'IMG' ? ownBackground(el) : backgroundBehind(el, slide);
        if (!behind) continue;
        const light = luminance(behind) >= 0.5;
        if ((variant === 'black' && !light) || (variant === 'white' && light)) {
          issues.push({ slide: no, kind: 'logo', variant, background: light ? 'light' : 'dark' });
        }
      }

      if (el.tagName === 'IMG' || el.tagName === 'svg' || el.tagName === 'VIDEO') {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          const visibleWidth = Math.max(0, Math.min(rect.right, box.right) - Math.max(rect.left, box.left));
          const visibleHeight = Math.max(0, Math.min(rect.bottom, box.bottom) - Math.max(rect.top, box.top));
          const shown = (visibleWidth * visibleHeight) / (rect.width * rect.height);
          if (shown < 0.9) {
            issues.push({ slide: no, kind: 'image', text: el.getAttribute('alt') || el.tagName.toLowerCase(), pct: Math.round((1 - shown) * 100) });
          }
        }
        continue;
      }

      const rects = textRects(el);
      if (rects.length) items.push({ el, rects, svg: !!el.closest('svg') });
    }

    for (const { el, rects, svg } of items) {
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
      if (svg) continue;
      const style = getComputedStyle(el);
      const color = parseColor(style.webkitTextFillColor || style.color) || parseColor(style.color);
      if (!color || color.a === 0) continue;
      const behind = backgroundBehind(el, slide);
      if (behind === null) continue;
      const ratio = contrast(color.a < 1 ? blend(color, behind) : color, behind);
      if (ratio < MIN_CONTRAST) {
        issues.push({ slide: no, kind: 'contrast', text: label(el), ratio: Math.round(ratio * 10) / 10 });
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
