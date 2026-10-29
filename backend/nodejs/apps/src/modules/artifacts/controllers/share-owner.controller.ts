import { NextFunction, Response } from 'express';
import { AuthenticatedUserRequest } from '../../../libs/middlewares/types';
import { HttpMethod } from '../../../libs/enums/http-methods.enum';
import { AppConfig } from '../../tokens_manager/config/config';
import { executeConnectorCommand } from '../../tokens_manager/utils/connector.utils';
import { insertShare, listActiveShares, revokeShare } from '../services/share-repository';
import { isShareOwnerActive } from '../services/share-owner';
import { setShareResponsePrivacyHeaders } from '../services/share-response';

function identity(req: AuthenticatedUserRequest): { userId: string; orgId: string } | null {
  const { userId, orgId } = req.user || {};
  return userId && orgId ? { userId: String(userId), orgId: String(orgId) } : null;
}

export const createArtifactShare = (config: AppConfig) => async (
  req: AuthenticatedUserRequest, res: Response, _next: NextFunction,
): Promise<void> => {
  setShareResponsePrivacyHeaders(res);
  const actor = identity(req);
  const { version, expiresInDays } = req.body || {};
  if (!actor || !Number.isSafeInteger(version) || version < 1 || ![1, 7, 30].includes(expiresInDays)) {
    res.status(400).json({ message: 'Invalid share request.' });
    return;
  }
  try {
    if (!await isShareOwnerActive(actor.userId, actor.orgId)) {
      res.status(404).json({ message: 'Artifact unavailable.' });
      return;
    }
    const artifactId = String(req.params.artifactId);
    const url = `${config.connectorBackend}/api/v1/artifacts/${encodeURIComponent(artifactId)}/share-authorization?version=${version}`;
    const result = await executeConnectorCommand<{ authorized?: boolean; contentHash?: string; name?: string; mimeType?: string }>(url, HttpMethod.POST, req.headers as Record<string, string>);
    if (result.statusCode !== 200 || result.data?.authorized !== true ||
        !/^[0-9a-f]{64}$/.test(result.data.contentHash || '') ||
        typeof result.data.name !== 'string' || !result.data.name || result.data.name.length > 255 ||
        typeof result.data.mimeType !== 'string' || !result.data.mimeType || result.data.mimeType.length > 255) {
      res.status(404).json({ message: 'Artifact unavailable.' });
      return;
    }
    const share = await insertShare({ artifactId, version, contentHash: result.data.contentHash!, name: result.data.name, mimeType: result.data.mimeType, orgId: actor.orgId, ownerId: actor.userId,
      expiresAt: new Date(Date.now() + expiresInDays * 86_400_000) });
    // The bearer token is returned once and is never persisted or logged.
    res.status(201).json(share);
  } catch {
    res.status(503).json({ message: 'Could not create share. Please try again.' });
  }
};

export const listArtifactShares = () => async (
  req: AuthenticatedUserRequest, res: Response, _next: NextFunction,
): Promise<void> => {
  setShareResponsePrivacyHeaders(res);
  const actor = identity(req);
  if (!actor) { res.status(401).json({ message: 'Authentication required.' }); return; }
  try {
    const shares = await listActiveShares({ artifactId: String(req.params.artifactId), orgId: actor.orgId, ownerId: actor.userId });
    res.json({ shares });
  } catch { res.status(503).json({ message: 'Could not load shares.' }); }
};

export const revokeArtifactShare = () => async (
  req: AuthenticatedUserRequest, res: Response, _next: NextFunction,
): Promise<void> => {
  setShareResponsePrivacyHeaders(res);
  const actor = identity(req);
  if (!actor) { res.status(401).json({ message: 'Authentication required.' }); return; }
  try {
    const revoked = await revokeShare({ shareId: String(req.params.shareId), artifactId: String(req.params.artifactId), orgId: actor.orgId, ownerId: actor.userId });
    if (!revoked) { res.status(404).json({ message: 'Share unavailable.' }); return; }
    res.status(204).end();
  } catch { res.status(503).json({ message: 'Could not stop sharing.' }); }
};
