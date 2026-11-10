import { ArtifactShareModel } from '../schema/artifact-share.schema';
import { createShareToken, hashShareToken } from './share-token';
import { EncryptionService } from '../../../libs/encryptor/encryptor';
import { getHashedSecretKey } from '../../configuration_manager/config/config';

function encryptor(): EncryptionService {
  return EncryptionService.getInstance('aes-256-gcm', getHashedSecretKey());
}

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
  // Keep a protected copy for the owner, bound to this artifact and identity.
  const encryptedToken = encryptor().encrypt(JSON.stringify({ token, artifactId: input.artifactId, orgId: input.orgId, ownerId: input.ownerId }));
  const share = await ArtifactShareModel.create({ ...input, tokenHash, encryptedToken });
  return { id: String(share._id), token, expiresAt: share.expiresAt };
}

/** List only the owner's currently active shares without exposing bearer credentials. */
export async function listActiveShares(input: {
  artifactId: string;
  orgId: string;
  ownerId: string;
}) {
  const shares = await ArtifactShareModel.find({
    artifactId: input.artifactId,
    orgId: input.orgId,
    ownerId: input.ownerId,
    revokedAt: null,
    expiresAt: { $gt: new Date() },
  }).select('_id version createdAt expiresAt +encryptedToken').sort({ createdAt: -1 }).lean().exec();
  return shares.map(({ encryptedToken, ...share }) => ({ ...share, canCopy: Boolean(encryptedToken) }));
}

/** Recover only an active owner's encrypted link; legacy hash-only links return null. */
export async function recoverShareToken(input: {
  shareId: string; artifactId: string; orgId: string; ownerId: string;
}): Promise<string | null> {
  const share = await ArtifactShareModel.findOne({
    _id: input.shareId, artifactId: input.artifactId, orgId: input.orgId, ownerId: input.ownerId,
    revokedAt: null, expiresAt: { $gt: new Date() },
  }).select('+encryptedToken +tokenHash').lean().exec();
  if (!share?.encryptedToken) return null;
  try {
    const value = JSON.parse(encryptor().decrypt(share.encryptedToken));
    if (value.artifactId !== input.artifactId || value.orgId !== input.orgId || value.ownerId !== input.ownerId ||
        !share.tokenHash || hashShareToken(value.token) !== share.tokenHash) return null;
    return value.token;
  } catch {
    return null;
  }
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
