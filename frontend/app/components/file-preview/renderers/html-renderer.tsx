'use client';

import { useState, useEffect } from 'react';
import { Box, Flex, Text } from '@radix-ui/themes';

interface HtmlRendererProps {
  fileUrl: string;
  fileName: string;
}

/**
 * Render HTML as a real document, not a sanitized fragment in the app DOM.
 * The opaque-origin sandbox keeps artifact code away from the dashboard; CSP
 * permits inline page styling/scripts while blocking network access, frames,
 * forms, plugins, and navigation to a base URL.
 */
export function buildHtmlPreviewDocument(html: string): string {
  const policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
  const csp = `<meta http-equiv="Content-Security-Policy" content="${policy}">`;

  if (/<head\b[^>]*>/i.test(html)) {
    return html.replace(/(<head\b[^>]*>)/i, `$1${csp}`);
  }
  if (/<html\b[^>]*>/i.test(html)) {
    return html.replace(/(<html\b[^>]*>)/i, `$1<head>${csp}</head>`);
  }
  return `<!doctype html><html><head>${csp}</head><body>${html}</body></html>`;
}

export function HtmlRenderer({ fileUrl, fileName }: HtmlRendererProps) {
  const [html, setHtml] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fileUrl?.trim()) {
      setError('File URL not available');
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetch(fileUrl);
        if (!response.ok) throw new Error('Failed to fetch file content');
        const content = await response.text();
        if (!cancelled) setHtml(buildHtmlPreviewDocument(content));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load file');
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    void load();
    return () => { cancelled = true; };
  }, [fileUrl]);

  if (isLoading) {
    return (
      <Flex align="center" justify="center" style={{ height: '100%', padding: 'var(--space-6)' }}>
        <Text size="2" color="gray">Loading HTML...</Text>
      </Flex>
    );
  }

  if (error) {
    return (
      <Flex direction="column" align="center" justify="center" gap="3" style={{ height: '100%', padding: 'var(--space-6)' }}>
        <span className="material-icons-outlined" style={{ fontSize: '48px', color: 'var(--red-9)' }}>
          error_outline
        </span>
        <Text size="3" weight="medium" color="red">{error}</Text>
      </Flex>
    );
  }

  return (
    <Box style={{ width: '100%', height: '100%', minHeight: 0, overflow: 'hidden', border: '1px solid var(--olive-6)', borderRadius: 'var(--radius-3)', background: 'white' }}>
      <iframe
        title={`Preview of ${fileName}`}
        srcDoc={html}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        style={{ display: 'block', width: '100%', height: '100%', border: 0, background: 'white' }}
      />
    </Box>
  );
}
