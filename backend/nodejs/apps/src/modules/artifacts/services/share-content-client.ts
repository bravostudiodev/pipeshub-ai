import jwt from 'jsonwebtoken';

export interface ShareAuthority {
  artifactId: string;
  version: number;
  contentHash: string;
  name: string;
  mimeType: string;
  orgId: string;
  ownerId: string;
}

/** Called only after validation of the bearer share and its owner. */
export async function fetchPinnedShareContent(
  connectorBackend: string,
  scopedJwtSecret: string,
  authority: ShareAuthority,
): Promise<Buffer> {
  if (!scopedJwtSecret) throw new Error('Share content service unavailable');
  const serviceToken = jwt.sign({
    orgId: authority.orgId,
    userId: authority.ownerId,
    artifactId: authority.artifactId,
    version: authority.version,
    contentHash: authority.contentHash,
    scopes: ['artifact-share:content'],
  }, scopedJwtSecret, { algorithm: 'HS256', expiresIn: '60s' });
  // The URL is configured server-side, never supplied by the viewer.
  const url = new URL('/api/v1/internal/artifact-share/content', connectorBackend);
  const response = await fetch(url, {
    method: 'GET',
    headers: { Authorization: `Bearer ${serviceToken}` },
    redirect: 'error',
    signal: AbortSignal.timeout(120_000),
  });
  if (!response.ok || !response.body) throw new Error('Share content service unavailable');
  const maxBytes = 25 * 1024 * 1024;
  const reader = response.body.getReader();
  const chunks: Buffer[] = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) throw new Error('Share content exceeds size limit');
      chunks.push(Buffer.from(value));
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
  return Buffer.concat(chunks, size);
}
