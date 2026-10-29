'use client';

import { useEffect, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import { Box, Button, Flex, Heading, Text } from '@radix-ui/themes';
import { downloadShare, getShareContent, getShareMetadata, ShareMetadata } from './api';
import { ImageRenderer } from '@/app/components/file-preview/renderers/image-renderer';
import { HtmlRenderer } from '@/app/components/file-preview/renderers/html-renderer';
import { rasterMime, RasterPreview } from './raster-preview';

const PdfPreview = dynamic(() => import('./pdf-preview').then((module) => module.PdfPreview), { ssr: false });
type State = 'loading' | 'available' | 'unavailable';

export default function SharedArtifactPage() {
  const [token, setToken] = useState('');
  const [state, setState] = useState<State>('loading');
  const [metadata, setMetadata] = useState<ShareMetadata>();
  const [preview, setPreview] = useState<{ kind: 'text'; source: string }>();
  const [htmlUrl, setHtmlUrl] = useState('');
  const [svgUrl, setSvgUrl] = useState('');
  const [fullscreen, setFullscreen] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const [raster, setRaster] = useState<{ bytes: Uint8Array; mime: string }>();
  const [pdfUrl, setPdfUrl] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const value = window.location.hash.slice(1);
    setToken(value);
    let cancelled = false;
    let pdfObjectUrl = '';
    let htmlObjectUrl = '';
    let svgObjectUrl = '';
    if (!/^[A-Za-z0-9_-]{43}$/.test(value)) {
      setState('unavailable');
      return () => { cancelled = true; };
    }
    getShareMetadata(value).then(async (info) => {
      const isHtml = info.mimeType === 'text/html';
      const isSvg = info.mimeType === 'image/svg+xml';
      const kind = ['text/plain', 'text/csv', 'application/json'].includes(info.mimeType) ? 'text' : null;
      const isRaster = ['image/png', 'image/jpeg', 'image/webp'].includes(info.mimeType);
      const isPdf = info.mimeType === 'application/pdf';
      const content = kind || isRaster || isPdf || isHtml || isSvg ? await getShareContent(value) : undefined;
      const source = kind && content ? await content.text() : undefined;
      const bytes = (isRaster || isPdf) && content ? new Uint8Array(await content.arrayBuffer()) : undefined;
      const detectedMime = bytes ? rasterMime(bytes) : null;
      if (!cancelled) {
        setMetadata(info);
        if (kind && source !== undefined) setPreview({ kind, source });
        if (isHtml && content) {
          htmlObjectUrl = URL.createObjectURL(content);
          setHtmlUrl(htmlObjectUrl);
        }
        if (isSvg && content) {
          svgObjectUrl = URL.createObjectURL(new Blob([content], { type: 'image/svg+xml' }));
          setSvgUrl(svgObjectUrl);
        }
        if (bytes && detectedMime === info.mimeType) setRaster({ bytes, mime: detectedMime });
        if (bytes && isPdf && String.fromCharCode(...bytes.slice(0, 5)) === '%PDF-') {
          pdfObjectUrl = URL.createObjectURL(new Blob([new Uint8Array(bytes)], { type: 'application/pdf' }));
          setPdfUrl(pdfObjectUrl);
        }
        setState('available');
      }
    }).catch(() => { if (!cancelled) setState('unavailable'); });
    return () => { cancelled = true; if (pdfObjectUrl) URL.revokeObjectURL(pdfObjectUrl); if (htmlObjectUrl) URL.revokeObjectURL(htmlObjectUrl); if (svgObjectUrl) URL.revokeObjectURL(svgObjectUrl); };
  }, []);

  useEffect(() => {
    const update = () => setFullscreen(document.fullscreenElement === previewRef.current);
    document.addEventListener('fullscreenchange', update);
    return () => document.removeEventListener('fullscreenchange', update);
  }, []);

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === previewRef.current) await document.exitFullscreen();
      else await previewRef.current?.requestFullscreen();
    } catch { /* The browser may refuse fullscreen. */ }
  }

  async function download() {
    setBusy(true);
    try { await downloadShare(token, metadata?.name || 'artifact-download'); }
    catch { setState('unavailable'); }
    finally { setBusy(false); }
  }

  return (
    <Flex align="center" justify="center" style={{ minHeight: '100vh', padding: 'var(--space-5)' }}>
      <meta name="referrer" content="no-referrer" />
      <Box style={{ maxWidth: 1200, width: '100%', padding: 'var(--space-6)', background: 'white', borderRadius: 'var(--radius-4)' }}>
        <Heading size="5">Shared artifact</Heading>
        {state === 'loading' && <Text as="p" style={{ marginTop: 'var(--space-4)' }}>Checking availability…</Text>}
        {state === 'unavailable' && <Text as="p" style={{ marginTop: 'var(--space-4)' }}>This artifact is unavailable.</Text>}
        {state === 'available' && (
          <Flex direction="column" gap="4" style={{ marginTop: 'var(--space-4)' }}>
            <Text>{metadata?.name} · Version {metadata?.version}</Text>
            <Box ref={previewRef} style={{ background: 'white', overflow: 'auto', ...(fullscreen ? { width: '100%', height: '100%', padding: 'var(--space-4)' } : {}) }}>
              {(preview || htmlUrl || svgUrl || raster || pdfUrl) && <Button variant="soft" onClick={toggleFullscreen}>{fullscreen ? 'Exit full screen' : 'Full screen'}</Button>}
              {preview ? <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: fullscreen ? 'none' : 600, overflow: 'auto' }}>{preview.source}</pre> : htmlUrl ? <Box style={{ height: fullscreen ? '100%' : '70vh' }}><HtmlRenderer fileUrl={htmlUrl} fileName={metadata?.name || 'artifact.html'} /></Box> : svgUrl ? <Box style={{ height: fullscreen ? '100%' : '70vh' }}><ImageRenderer fileUrl={svgUrl} fileName={metadata?.name || 'artifact.svg'} /></Box> : raster ? <RasterPreview bytes={raster.bytes} mime={raster.mime} /> : pdfUrl ? <PdfPreview url={pdfUrl} /> : <Text size="2" color="gray">Preview is not available. Download the artifact to view it.</Text>}
            </Box>
            <Button onClick={download} disabled={busy}>{busy ? 'Downloading…' : 'Download'}</Button>
          </Flex>
        )}
      </Box>
    </Flex>
  );
}
