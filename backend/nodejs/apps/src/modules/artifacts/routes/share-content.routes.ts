import { Router } from 'express';
import { AppConfig } from '../../tokens_manager/config/config';
import { fetchPinnedShareContent } from '../services/share-content-client';
import { resolveShare } from '../services/resolve-share';
import { setShareDownloadHeaders, setShareResponsePrivacyHeaders } from '../services/share-response';

/** Bearer token is supplied only in the body, never in the request URL. */
export function createShareContentRouter(appConfig: AppConfig): Router {
  const router = Router();
  router.post('/metadata', async (req, res) => {
    setShareResponsePrivacyHeaders(res);
    try {
      const authority = await resolveShare(req.body?.token, async (share) => {
        await fetchPinnedShareContent(appConfig.connectorBackend, appConfig.scopedJwtSecret, share);
        return true;
      });
      if (!authority) {
        res.status(404).json({ message: 'This artifact is unavailable.' });
        return;
      }
      res.json({ version: authority.version, name: authority.name, mimeType: authority.mimeType });
    } catch {
      res.status(404).json({ message: 'This artifact is unavailable.' });
    }
  });
  router.post('/content', async (req, res) => {
    setShareResponsePrivacyHeaders(res);
    // Uniform failures avoid revealing whether a share or artifact exists.
    const unavailable = () => res.status(404).json({ message: 'This artifact is unavailable.' });
    try {
      let bytes: Buffer | undefined;
      const authority = await resolveShare(req.body?.token, async (share) => {
        bytes = await fetchPinnedShareContent(appConfig.connectorBackend, appConfig.scopedJwtSecret, share);
        return true;
      });
      if (!authority || !bytes) {
        unavailable();
        return;
      }
      setShareDownloadHeaders(res);
      res.status(200).send(bytes);
    } catch {
      // Neither exceptions nor request bodies are logged here: they can contain
      // bearer secrets or upstream response details.
      unavailable();
    }
  });
  return router;
}
