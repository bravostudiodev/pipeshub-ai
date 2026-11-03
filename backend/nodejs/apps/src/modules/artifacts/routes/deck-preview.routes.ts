import { Router, Request, Response } from 'express';
import jwt, { JwtPayload } from 'jsonwebtoken';
import { AppConfig } from '../../tokens_manager/config/config';
import { fetchPinnedShareDeckFile } from '../services/share-content-client';
import { resolveShare } from '../services/resolve-share';
import { isShareOwnerActive } from '../services/share-owner';

interface DeckPreviewClaims extends JwtPayload {
  artifactId?: string;
  orgId?: string;
  userId?: string;
  version?: number;
  purpose?: string;
  name?: string;
  mimeType?: string;
}

export function isDeckZip(name: unknown, mimeType: unknown): boolean {
  return mimeType === 'application/zip' || mimeType === 'application/x-zip-compressed' ||
    ((mimeType === 'application/octet-stream' || !mimeType) && typeof name === 'string' && name.toLowerCase().endsWith('.zip'));
}

function sendDeckHeaders(res: Response, index: boolean): void {
  res.set({
    'Cache-Control': 'private, no-store',
    'Access-Control-Allow-Origin': '*',
    'Cross-Origin-Resource-Policy': 'cross-origin',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    ...(index ? { 'Content-Security-Policy': 'sandbox allow-scripts' } : {}),
  });
}

/**
 * Serves files from one versioned deck capability. The capability is minted
 * only by the authenticated artifact-preview endpoint and names one user,
 * organization, artifact, and version; the Python endpoint rechecks artifact
 * ACLs for every file request.
 */
export function createDeckPreviewRouter(appConfig: AppConfig): Router {
  const router = Router();
  const sharedHandler = async (req: Request, res: Response): Promise<void> => {
    sendDeckHeaders(res, false);
    try {
      if (!appConfig.scopedJwtSecret) {
        res.status(503).send('Presentation preview is unavailable.');
        return;
      }
      const shareToken = req.params.shareToken;
      const filePath =
        (req.params as unknown as Record<number, string>)[0] || 'index.html';
      let deckFile: { bytes: Buffer; contentType: string } | undefined;
      const authority = await resolveShare(shareToken, async (share) => {
        if (!isDeckZip(share.name, share.mimeType)) return false;
        deckFile = await fetchPinnedShareDeckFile(
          appConfig.connectorBackend,
          appConfig.scopedJwtSecret,
          share,
          filePath,
        );
        return true;
      });
      if (!authority || !deckFile) {
        res.status(404).send('Presentation is unavailable.');
        return;
      }
      sendDeckHeaders(res, filePath === 'index.html');
      res.setHeader('Content-Type', deckFile.contentType);
      res.setHeader('Content-Disposition', 'inline');
      res.status(200).send(deckFile.bytes);
    } catch {
      // Share tokens and artifact paths are deliberately never logged.
      if (!res.headersSent)
        res.status(404).send('Presentation is unavailable.');
    }
  };
  const handler = async (req: Request, res: Response): Promise<void> => {
    sendDeckHeaders(res, false);
    try {
      if (!appConfig.scopedJwtSecret) {
        res.status(503).send('Presentation preview is unavailable.');
        return;
      }
      const { artifactId, version, capability } = req.params as Record<
        string,
        string | undefined
      >;
      const numericVersion = Number(version);
      if (
        !artifactId ||
        !capability ||
        !Number.isSafeInteger(numericVersion) ||
        numericVersion < 1
      ) {
        res.status(404).send('Presentation is unavailable.');
        return;
      }
      const claims = jwt.verify(capability, appConfig.scopedJwtSecret, {
        algorithms: ['HS256'],
      }) as DeckPreviewClaims;
      if (
        claims.purpose !== 'deck-preview' ||
        !isDeckZip(claims.name, claims.mimeType) ||
        claims.artifactId !== artifactId ||
        claims.version !== numericVersion ||
        typeof claims.userId !== 'string' ||
        typeof claims.orgId !== 'string'
      ) {
        res.status(404).send('Presentation is unavailable.');
        return;
      }
      if (!(await isShareOwnerActive(claims.userId, claims.orgId))) {
        res.status(404).send('Presentation is unavailable.');
        return;
      }
      const filePath =
        (req.params as unknown as Record<number, string>)[0] || 'index.html';
      const serviceToken = jwt.sign(
        {
          orgId: claims.orgId,
          userId: claims.userId,
          artifactId,
          version: numericVersion,
          scopes: ['artifact-deck:content'],
          name: claims.name,
          mimeType: claims.mimeType,
        },
        appConfig.scopedJwtSecret,
        { algorithm: 'HS256', expiresIn: '60s' },
      );
      const url = new URL(
        '/api/v1/internal/artifact-deck/file',
        appConfig.connectorBackend,
      );
      url.searchParams.set('path', filePath);
      const upstream = await fetch(url, {
        method: 'GET',
        headers: { Authorization: `Bearer ${serviceToken}` },
        redirect: 'error',
        signal: AbortSignal.timeout(120_000),
      });
      if (!upstream.ok || !upstream.body) {
        res
          .status(
            upstream.status === 403 || upstream.status === 404 ? 404 : 503,
          )
          .send('Presentation is unavailable.');
        return;
      }
      const contentType = upstream.headers.get('content-type');
      sendDeckHeaders(res, filePath === 'index.html');
      if (contentType) res.setHeader('Content-Type', contentType);
      res.setHeader('Content-Disposition', 'inline');
      res.status(200);
      const bytes = Buffer.from(await upstream.arrayBuffer());
      res.send(bytes);
    } catch {
      // Capability tokens and artifact paths are deliberately never logged.
      if (!res.headersSent)
        res.status(404).send('Presentation is unavailable.');
    }
  };
  router.get('/shared/:shareToken', sharedHandler);
  router.get('/shared/:shareToken/*', sharedHandler);
  router.get('/:artifactId/:version/:capability', handler);
  router.get('/:artifactId/:version/:capability/*', handler);
  return router;
}
