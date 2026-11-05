import { findActiveShare } from './share-repository';
import { isShareOwnerActive } from './share-owner';
import { ShareAuthority } from './share-content-client';

/**
 * Resolve authority for one request. The supplied checker must independently
 * revalidate artifact ownership, visibility and the pinned version. It must not
 * trust browser input. Neither the token nor its hash is returned.
 *
 * Callers must repeat this for metadata and every content request. Database or
 * authorization errors propagate and must be converted to a generic failure.
 */
export async function resolveShare(
  token: unknown,
  authorize: (share: ShareAuthority) => Promise<boolean>,
): Promise<ShareAuthority | null> {
  const share = await findActiveShare(token);
  if (!share) return null;
  const authority = {
    artifactId: share.artifactId,
    version: share.version,
    contentHash: share.contentHash,
    name: share.name,
    mimeType: share.mimeType,
    orgId: share.orgId,
    ownerId: share.ownerId,
  };
  if (!await isShareOwnerActive(authority.ownerId, authority.orgId)) return null;
  if (!await authorize(authority)) return null;
  // Re-read after potentially slow authorization, so a revoke or expiry during
  // that check is not missed. This does not retract bytes already being sent.
  const fresh = await findActiveShare(token);
  if (!fresh || String(fresh._id) !== String(share._id) ||
      fresh.artifactId !== authority.artifactId || fresh.version !== authority.version ||
      fresh.orgId !== authority.orgId || fresh.ownerId !== authority.ownerId ||
      fresh.contentHash !== authority.contentHash || fresh.name !== authority.name || fresh.mimeType !== authority.mimeType) return null;
  return authority;
}
