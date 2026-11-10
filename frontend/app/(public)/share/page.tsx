'use client';

import { useEffect, useRef, useState } from 'react';
import { Box, Button, Flex, Heading, Text } from '@radix-ui/themes';
import { downloadShare, getShareContent, getShareMetadata, ShareMetadata } from './api';
import { FilePreviewRenderer } from '@/app/components/file-preview/renderers/file-preview-renderer';
import { getRendererType, isDocxFile, isLegacyWordDocFile, isPresentationFile } from '@/app/components/file-preview/utils';
import { downloadPresentationHtml, presentationTitle } from '@/app/components/file-preview/presentation';
type State = 'loading' | 'available' | 'unavailable';

export default function SharedArtifactPage() {
  const [token, setToken] = useState('');
  const [state, setState] = useState<State>('loading');
  const [metadata, setMetadata] = useState<ShareMetadata>();
  const [preview, setPreview] = useState<{ url: string; type: string; blob?: Blob }>();
  const [deckUrl, setDeckUrl] = useState('');
  const [fullscreen, setFullscreen] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const supplied = params.getAll('token');
    const pathMatch = window.location.pathname.match(/^\/share\/([A-Za-z0-9_-]{43})\/?$/);
    // New links keep the token in the path so gateway redirects preserve it.
    // Continue accepting earlier query and fragment links; reject mixed inputs.
    const isLegacyPath = /^\/share\/?$/.test(window.location.pathname);
    const value = pathMatch
      ? (supplied.length === 0 && !window.location.hash ? pathMatch[1] : '')
      : !isLegacyPath ? '' : supplied.length === 1 ? supplied[0] : supplied.length === 0 ? window.location.hash.slice(1) : '';
    if (supplied.length > 0) {
      window.history.replaceState(null, '', `${window.location.pathname}${/^[A-Za-z0-9_-]{43}$/.test(value) ? `#${value}` : ''}`);
    }
    setToken(value);
    let cancelled = false;
    let objectUrl = '';
    if (!/^[A-Za-z0-9_-]{43}$/.test(value)) {
      setState('unavailable');
      return () => { cancelled = true; };
    }
    getShareMetadata(value).then(async (info) => {
      const isSlidev = info.isDeck === true;
      const isPresentation = isPresentationFile(info.mimeType, info.name);
      const convertToPdf = isPresentation || isLegacyWordDocFile(info.mimeType, info.name);
      const renderer = getRendererType(info.mimeType, info.name);
      const canPreview = convertToPdf || !['unknown', 'document'].includes(renderer);
      let content: Blob | undefined;
      if (!isSlidev && canPreview) {
        try { content = await getShareContent(value, convertToPdf); } catch { /* Keep the download available if preview conversion fails. */ }
      }
      if (!cancelled) {
        setMetadata(info);
        if (isSlidev) setDeckUrl(`/decks/shared/${encodeURIComponent(value)}/index.html`);
        if (content) {
          const blobType = convertToPdf ? 'application/pdf' : info.mimeType;
          const blob = new Blob([content], { type: blobType });
          const type = isPresentation ? 'application/vnd.oddjeeves.presentation-preview' : blobType;
          objectUrl = URL.createObjectURL(blob);
          setPreview({ url: objectUrl, type, ...(isDocxFile(type, info.name) ? { blob } : {}) });
        }
        setState('available');
      }
    }).catch(() => { if (!cancelled) setState('unavailable'); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
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

  // A deck downloads as one HTML file that opens in any browser; the ZIP
  // (source plus build) stays available as a secondary download.
  async function downloadPresentation() {
    setBusy(true);
    try { await downloadPresentationHtml(deckUrl, presentationTitle(metadata?.name || '')); }
    catch { await download(); return; }
    finally { setBusy(false); }
  }

  const displayName = deckUrl ? presentationTitle(metadata?.name || '') : metadata?.name;

  return (
    <Flex align="center" justify="center" style={{ minHeight: '100vh', padding: 'var(--space-5)' }}>
      <meta name="referrer" content="no-referrer" />
      <Box style={{ maxWidth: 1200, width: '100%', padding: 'var(--space-6)', background: 'var(--color-panel-solid)', color: 'var(--gray-12)', borderRadius: 'var(--radius-4)' }}>
        <Heading size="5">Shared artifact</Heading>
        {state === 'loading' && <Text as="p" style={{ marginTop: 'var(--space-4)' }}>Checking availability…</Text>}
        {state === 'unavailable' && <Text as="p" style={{ marginTop: 'var(--space-4)' }}>This artifact is unavailable.</Text>}
        {state === 'available' && (
          <Flex direction="column" gap="4" style={{ marginTop: 'var(--space-4)' }}>
            <Text>{displayName} · Version {metadata?.version}</Text>
            <Box ref={previewRef} style={{ background: 'var(--color-panel-solid)', overflow: 'auto', ...(fullscreen ? { width: '100%', height: '100%', padding: 'var(--space-4)' } : {}) }}>
              {preview && !deckUrl && <Button variant="soft" onClick={toggleFullscreen}>{fullscreen ? 'Exit full screen' : 'Full screen'}</Button>}
              {deckUrl ? <Box style={{ height: fullscreen ? 'calc(100vh - 100px)' : '70vh' }}><FilePreviewRenderer fileUrl={deckUrl} fileName={displayName || 'shared deck'} fileType="application/vnd.oddjeeves.slidev-preview" /></Box> : preview ? <Box style={{ height: fullscreen ? 'calc(100vh - 100px)' : '70vh' }}><FilePreviewRenderer fileUrl={preview.url} fileBlob={preview.blob} fileName={metadata?.name || 'artifact'} fileType={preview.type} /></Box> : <Text size="2" color="gray">Preview is not available. Download the artifact to view it.</Text>}
            </Box>
            {deckUrl ? (
              <Flex direction="column" gap="2">
                <Button onClick={downloadPresentation} disabled={busy}>{busy ? 'Downloading…' : 'Download presentation'}</Button>
                <Button variant="ghost" size="1" onClick={download} disabled={busy} style={{ alignSelf: 'center' }}>Download source (.zip)</Button>
              </Flex>
            ) : (
              <Button onClick={download} disabled={busy}>{busy ? 'Downloading…' : 'Download'}</Button>
            )}
          </Flex>
        )}
      </Box>
    </Flex>
  );
}
