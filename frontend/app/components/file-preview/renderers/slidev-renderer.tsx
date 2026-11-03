'use client';

import { useRef } from 'react';
import { Box, Button } from '@radix-ui/themes';

interface SlidevRendererProps {
  fileUrl: string;
  fileName: string;
}

/** Built Slidev site running in its own opaque-origin sandboxed document. */
export function SlidevRenderer({ fileUrl, fileName }: SlidevRendererProps) {
  const iframe = useRef<HTMLIFrameElement>(null);
  return (
    <Box style={{ width: '100%', height: '100%', minHeight: '65vh', overflow: 'hidden', position: 'relative' }}>
      <Button variant="soft" onClick={() => { iframe.current?.focus(); void iframe.current?.requestFullscreen().catch(() => {}); }} style={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }}>Present</Button>
      <iframe
        ref={iframe}
        title={`Presentation preview: ${fileName}`}
        src={fileUrl}
        sandbox="allow-scripts"
        allow="fullscreen; screen-wake-lock"
        allowFullScreen
        referrerPolicy="no-referrer"
        style={{ display: 'block', width: '100%', height: '100%', minHeight: '65vh', border: 0, background: '#fff' }}
      />
    </Box>
  );
}
