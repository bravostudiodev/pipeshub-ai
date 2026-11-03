'use client';

import { useEffect, useRef, useState } from 'react';
import { Box, Button, Flex, Text } from '@radix-ui/themes';
import { PdfLoader } from 'react-pdf-highlighter';

const workerSrc = new URL('../../../../node_modules/react-pdf-highlighter/node_modules/pdfjs-dist/build/pdf.worker.min.js', import.meta.url).toString();
type PdfDocument = { numPages: number; getPage: (page: number) => Promise<any> };

function Slides({ pdf }: { pdf: PdfDocument }) {
  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [page, setPage] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    const change = () => setFullscreen(document.fullscreenElement === container.current);
    document.addEventListener('fullscreenchange', change);
    return () => document.removeEventListener('fullscreenchange', change);
  }, []);
  useEffect(() => {
    if (!fullscreen) return;
    const key = (event: KeyboardEvent) => {
      if (['ArrowRight', 'ArrowDown', 'PageDown', ' '].includes(event.key)) {
        event.preventDefault(); setPage((value) => Math.min(value + 1, pdf.numPages));
      } else if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key)) {
        event.preventDefault(); setPage((value) => Math.max(value - 1, 1));
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [fullscreen, pdf.numPages]);
  useEffect(() => {
    let cancelled = false;
    let task: { cancel: () => void; promise: Promise<unknown> } | undefined;
    void (async () => {
      try {
        const slide = await pdf.getPage(page);
        const base = slide.getViewport({ scale: 1 });
        const scale = Math.min(3, 2400 / Math.max(base.width, base.height));
        const viewport = slide.getViewport({ scale });
        if (cancelled || !canvas.current) return;
        canvas.current.width = Math.ceil(viewport.width);
        canvas.current.height = Math.ceil(viewport.height);
        const context = canvas.current.getContext('2d');
        if (!context) throw new Error('Canvas unavailable');
        task = slide.render({ canvasContext: context, viewport, annotationMode: 0 });
        await task.promise;
        if (!cancelled) setError(false);
      } catch { if (!cancelled) setError(true); }
    })();
    return () => { cancelled = true; task?.cancel(); };
  }, [pdf, page]);
  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === container.current) await document.exitFullscreen();
      else await container.current?.requestFullscreen();
    } catch { /* Fullscreen can be denied by the browser or embedding policy. */ }
  }
  return <Box ref={container} style={{ width: '100%', height: '100%', minHeight: 350, position: 'relative', background: '#111', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
    {error && <Text style={{ color: 'white' }}>Could not preview this slide.</Text>}
    <canvas ref={canvas} aria-label={`Slide ${page} of ${pdf.numPages}`} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
    <Flex align="center" gap="2" style={{ position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)', background: 'rgba(0,0,0,.75)', padding: 8, borderRadius: 8 }}>
      <Button variant="soft" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
      <Text style={{ color: 'white', whiteSpace: 'nowrap' }}>{page} / {pdf.numPages}</Text>
      <Button variant="soft" disabled={page >= pdf.numPages} onClick={() => setPage(page + 1)}>Next</Button>
      <Button variant="soft" onClick={toggleFullscreen}>{fullscreen ? 'Exit presentation' : 'Present'}</Button>
    </Flex>
  </Box>;
}

export function PresentationPdfRenderer({ fileUrl }: { fileUrl: string }) {
  return <PdfLoader url={fileUrl} workerSrc={workerSrc} {...{ isEvalSupported: false, disableFontFace: true }} beforeLoad={<Text>Loading presentation…</Text>} errorMessage={<Text>Could not preview this presentation.</Text>}>
    {(pdf) => <Slides pdf={pdf} />}
  </PdfLoader>;
}
