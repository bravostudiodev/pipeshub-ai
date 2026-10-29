import { Response } from 'express';

/**
 * Shared bytes are untrusted. Default to attachment/octet-stream even when a
 * file claims to be HTML, SVG, PDF or an image. A future preview must use a
 * separately reviewed sandbox and must not relax these download headers.
 */
export function setShareDownloadHeaders(response: Response): void {
  response.set({
    'Content-Type': 'application/octet-stream',
    'Content-Disposition': 'attachment; filename="artifact-download"',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; sandbox; base-uri 'none'; form-action 'none'",
    'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store, private',
    'Cross-Origin-Resource-Policy': 'same-origin',
  });
}

/** Apply to all token-based metadata and error responses as well as content. */
export function setShareResponsePrivacyHeaders(response: Response): void {
  response.set({
    'Cache-Control': 'no-store, private',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'Cross-Origin-Resource-Policy': 'same-origin',
  });
}
