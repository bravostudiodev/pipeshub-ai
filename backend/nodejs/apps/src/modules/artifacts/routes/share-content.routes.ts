import { Router } from 'express';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { AppConfig } from '../../tokens_manager/config/config';
import { fetchPinnedShareContent, fetchPinnedShareDeckFile } from '../services/share-content-client';
import { isDeckZip } from './deck-preview.routes';
import { resolveShare } from '../services/resolve-share';
import { setShareDownloadHeaders, setShareResponsePrivacyHeaders } from '../services/share-response';

/** Bearer token is supplied only in the body, never in the request URL. */
export function createShareContentRouter(appConfig: AppConfig): Router {
  const router = Router();
  router.post('/metadata', async (req, res) => {
    setShareResponsePrivacyHeaders(res);
    try {
      let isDeck = false;
      const authority = await resolveShare(req.body?.token, async (share) => {
        const upstream = await fetchPinnedShareContent(appConfig.connectorBackend, appConfig.scopedJwtSecret, share);
        await upstream.body?.cancel().catch(() => undefined);
        if (isDeckZip(share.name, share.mimeType)) {
          try {
            await fetchPinnedShareDeckFile(appConfig.connectorBackend, appConfig.scopedJwtSecret, share, 'index.html');
            isDeck = true;
          } catch { /* Ordinary ZIP files remain download-only. */ }
        }
        return true;
      });
      if (!authority) {
        res.status(404).json({ message: 'This artifact is unavailable.' });
        return;
      }
      res.json({ version: authority.version, name: authority.name, mimeType: authority.mimeType, isDeck });
    } catch {
      res.status(404).json({ message: 'This artifact is unavailable.' });
    }
  });
  router.post('/content', async (req, res) => {
    setShareResponsePrivacyHeaders(res);
    // Uniform failures avoid revealing whether a share or artifact exists.
    const unavailable = () => res.status(404).json({ message: 'This artifact is unavailable.' });
    let upstream: globalThis.Response | undefined;
    try {
      const authority = await resolveShare(req.body?.token, async (share) => {
        upstream = await fetchPinnedShareContent(appConfig.connectorBackend, appConfig.scopedJwtSecret, share, req.body?.previewPdf === true);
        return true;
      });
      if (!authority || !upstream?.body) {
        await upstream?.body?.cancel().catch(() => undefined);
        unavailable();
        return;
      }
      setShareDownloadHeaders(res);
      res.status(200);
      const body = upstream.body;
      await pipeline(Readable.from((async function* () {
        const reader = body.getReader();
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            yield value;
          }
        } finally {
          await reader.cancel().catch(() => undefined);
        }
      })()), res);
    } catch {
      // Neither exceptions nor request bodies are logged here: they can contain
      // bearer secrets or upstream response details.
      await upstream?.body?.cancel().catch(() => undefined);
      if (!res.headersSent && !res.destroyed) unavailable();
      else res.destroy();
    }
  });
  return router;
}
