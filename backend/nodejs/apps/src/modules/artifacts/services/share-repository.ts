import { ArtifactShareModel } from '../schema/artifact-share.schema';
import { createShareToken, hashShareToken } from './share-token';

/** Persistence only: callers must establish owner authority before creating or revoking. */
export async function insertShare(input: {
  artifactId: string;
  version: number;
  contentHash: string;
  name: string;
  mimeType: string;
  orgId: string;
  ownerId: string;
  expiresAt: Date;
}): Promise<{ id: string; token: string; expiresAt: Date }> {
  if (input.expiresAt.getTime() <= Date.now() || !Number.isFinite(input.expiresAt.getTime())) {
    throw new Error('Invalid share expiration');
  }
  const token = createShareToken();
  const tokenHash = hashShareToken(token);
  if (!tokenHash) throw new Error('Could not generate share token');
  const share = await ArtifactShareModel.create({ ...input, tokenHash });
  return { id: String(share._id), token, expiresAt: share.expiresAt };
}

/** List only the owner's currently active shares; bearer tokens cannot be recovered. */
export async function listActiveShares(input: {
  artifactId: string;
  orgId: string;
  ownerId: string;
}) {
  return ArtifactShareModel.find({
    artifactId: input.artifactId,
    orgId: input.orgId,
    ownerId: input.ownerId,
    revokedAt: null,
    expiresAt: { $gt: new Date() },
  }).select('_id version createdAt expiresAt').sort({ createdAt: -1 }).lean().exec();
}

/** Never cache this result: expiry and revocation must be checked on every request. */
export async function findActiveShare(token: unknown) {
  const tokenHash = hashShareToken(token);
  if (!tokenHash) return null;
  return ArtifactShareModel.findOne({
    tokenHash,
    revokedAt: null,
    expiresAt: { $gt: new Date() },
  }).lean().exec();
}

export async function revokeShare(input: {
  shareId: string;
  artifactId: string;
  orgId: string;
  ownerId: string;
}): Promise<boolean> {
  const result = await ArtifactShareModel.updateOne(
    {
      _id: input.shareId,
      artifactId: input.artifactId,
      orgId: input.orgId,
      ownerId: input.ownerId,
      revokedAt: null,
      expiresAt: { $gt: new Date() },
    },
    { $set: { revokedAt: new Date() } },
  ).exec();
  return result.modifiedCount === 1;
}
