'use client';

import { useRef } from 'react';
import { Box, Button, Flex } from '@radix-ui/themes';

interface SlidevRendererProps {
  fileUrl: string;
  fileName: string;
}

/** Built Slidev site running in its own opaque-origin sandboxed document. */
export function SlidevRenderer({ fileUrl, fileName }: SlidevRendererProps) {
  const iframe = useRef<HTMLIFrameElement>(null);
  return (
    <Flex direction="column" gap="2" style={{ width: '100%', height: '100%', minHeight: '40vh' }}>
      <Flex justify="end">
        <Button variant="soft" onClick={() => { iframe.current?.focus(); void iframe.current?.requestFullscreen().catch(() => {}); }}>Present</Button>
      </Flex>
      {/* A 16:9 frame that fits the available box; any other shape makes Slidev letterbox with black bars. */}
      <Flex data-testid="slidev-stage" align="start" justify="center" style={{ flex: 1, minHeight: 0, containerType: 'size' }}>
        <Box style={{ width: 'min(100cqw, calc(100cqh * 16 / 9))', aspectRatio: '16 / 9' }}>
          <iframe
            ref={iframe}
            title={`Presentation preview: ${fileName}`}
            src={fileUrl}
            sandbox="allow-scripts"
            allow="fullscreen; screen-wake-lock"
            allowFullScreen
            referrerPolicy="no-referrer"
            style={{ display: 'block', width: '100%', height: '100%', border: 0, background: '#000' }}
          />
        </Box>
      </Flex>
    </Flex>
  );
}
