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

function serviceToken(
  scopedJwtSecret: string,
  authority: ShareAuthority,
): string {
  if (!scopedJwtSecret) throw new Error('Share content service unavailable');
  return jwt.sign(
    {
      orgId: authority.orgId,
      userId: authority.ownerId,
      artifactId: authority.artifactId,
      version: authority.version,
      contentHash: authority.contentHash,
      name: authority.name,
      mimeType: authority.mimeType,
      scopes: ['artifact-share:content'],
    },
    scopedJwtSecret,
    { algorithm: 'HS256', expiresIn: '60s' },
  );
}

async function readBoundedBody(
  response: Response,
  maxBytes: number,
): Promise<Buffer> {
  if (!response.body) throw new Error('Share content service unavailable');
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

/** Called only after validation of the bearer share and its owner. */
export async function fetchPinnedShareContent(
  connectorBackend: string,
  scopedJwtSecret: string,
  authority: ShareAuthority,
  previewPdf = false,
): Promise<Response> {
  const token = serviceToken(scopedJwtSecret, authority);
  const url = new URL(
    '/api/v1/internal/artifact-share/content',
    connectorBackend,
  );
  if (previewPdf) url.searchParams.set('preview_pdf', 'true');
  const response = await fetch(url, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
    redirect: 'error',
    signal: AbortSignal.timeout(120_000),
  });
  if (!response.ok || !response.body) {
    await response.body?.cancel().catch(() => undefined);
    throw new Error('Share content service unavailable');
  }
  // The connector verifies the pinned hash before sending headers. Leave the
  // body streaming so large previews do not need another full copy in Node.
  return response;
}

/** Serves one path from the pinned deck after the share was revalidated. */
export async function fetchPinnedShareDeckFile(
  connectorBackend: string,
  scopedJwtSecret: string,
  authority: ShareAuthority,
  path: string,
): Promise<{ bytes: Buffer; contentType: string }> {
  const token = serviceToken(scopedJwtSecret, authority);
  const url = new URL(
    '/api/v1/internal/artifact-share/content',
    connectorBackend,
  );
  url.searchParams.set('deck_path', path);
  const response = await fetch(url, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
    redirect: 'error',
    signal: AbortSignal.timeout(120_000),
  });
  if (!response.ok) throw new Error('Share content service unavailable');
  const bytes = await readBoundedBody(response, 20 * 1024 * 1024);
  return {
    bytes,
    contentType:
      response.headers.get('content-type') || 'application/octet-stream',
  };
}
