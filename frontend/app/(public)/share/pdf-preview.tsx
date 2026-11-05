'use client';

import { useEffect, useRef, useState } from 'react';
import { Button, Flex, Text } from '@radix-ui/themes';
import { PdfLoader } from 'react-pdf-highlighter';

// Bundle the worker with the application rather than loading the library's
// default worker from a third-party CDN. Keep it at the exact pdf.js version.
const workerSrc = new URL('../../../node_modules/react-pdf-highlighter/node_modules/pdfjs-dist/build/pdf.worker.min.js', import.meta.url).toString();

type PdfDocument = { numPages: number; getPage: (number: number) => Promise<any> };

function PdfCanvas({ pdf }: { pdf: PdfDocument }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let task: { cancel: () => void } | undefined;
    void (async () => {
      try {
        const page = await pdf.getPage(pageNumber);
        const base = page.getViewport({ scale: 1 });
        const scale = Math.min(1.5, 1600 / Math.max(base.width, base.height));
        if (!Number.isFinite(scale) || scale <= 0 || cancelled || !canvas.current) throw new Error('Invalid PDF page');
        const viewport = page.getViewport({ scale });
        canvas.current.width = Math.ceil(viewport.width);
        canvas.current.height = Math.ceil(viewport.height);
        const context = canvas.current.getContext('2d');
        if (!context) throw new Error('Canvas unavailable');
        // Render only page pixels, not the annotation/link or form layers.
        const rendering = page.render({ canvasContext: context, viewport, annotationMode: 0 });
        task = rendering;
        await rendering.promise;
        if (!cancelled) setError(false);
      } catch { if (!cancelled) setError(true); }
    })();
    return () => { cancelled = true; task?.cancel(); };
  }, [pdf, pageNumber]);
  return <Flex direction="column" gap="2">
    <Flex align="center" gap="3"><Button variant="soft" disabled={pageNumber <= 1} onClick={() => setPageNumber(pageNumber - 1)}>Previous</Button><Text>Page {pageNumber} of {pdf.numPages}</Text><Button variant="soft" disabled={pageNumber >= pdf.numPages} onClick={() => setPageNumber(pageNumber + 1)}>Next</Button></Flex>
    {error && <Text>Could not preview this PDF.</Text>}
    <canvas ref={canvas} aria-label={`PDF page ${pageNumber}`} style={{ maxWidth: '100%', height: 'auto' }} />
  </Flex>;
}

export function PdfPreview({ url }: { url: string }) {
  return <PdfLoader url={url} workerSrc={workerSrc} {...{ isEvalSupported: false, disableFontFace: true }} beforeLoad={<Text>Loading preview…</Text>} errorMessage={<Text>Could not preview this PDF.</Text>}>
    {(pdf) => <PdfCanvas pdf={pdf} />}
  </PdfLoader>;
}
