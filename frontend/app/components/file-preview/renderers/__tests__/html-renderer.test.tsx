import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { buildHtmlPreviewDocument, HtmlRenderer } from '../html-renderer';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('HTML preview', () => {
  it('adds a restrictive CSP without stripping document styles or scripts', () => {
    const source = '<!doctype html><html><head><style>body { color: red }</style></head><body><script>document.body.dataset.ready = "yes"</script></body></html>';
    const result = buildHtmlPreviewDocument(source);

    expect(result).toContain('Content-Security-Policy');
    expect(result).toContain('<style>body { color: red }</style>');
    expect(result).toContain('<script>document.body.dataset.ready = "yes"</script>');
    expect(result).toContain("connect-src 'none'");
  });

  it('renders the document in an isolated iframe so page CSS applies', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      '<html><head><style>body { background: papayawhip }</style></head><body>Styled page</body></html>',
      { status: 200 },
    ));

    render(<HtmlRenderer fileUrl="blob:preview" fileName="summary.html" />);
    const frame = await screen.findByTitle('Preview of summary.html');

    await waitFor(() => expect(frame.getAttribute('srcdoc')).toContain('background: papayawhip'));
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    expect(frame.getAttribute('srcdoc')).toContain('Content-Security-Policy');
  });
});
