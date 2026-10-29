const ENDPOINT = '/api/v1/artifact-shares';

async function request(token: string, operation: 'metadata' | 'content'): Promise<Response> {
  const response = await fetch(`${ENDPOINT}/${operation}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
    credentials: 'same-origin', // The external gateway may use a same-origin cookie.
    referrerPolicy: 'no-referrer',
    cache: 'no-store',
  });
  if (!response.ok) throw new Error('Artifact unavailable');
  return response;
}

export interface ShareMetadata { version: number; name: string; mimeType: string }

export async function getShareMetadata(token: string): Promise<ShareMetadata> {
  const response = await request(token, 'metadata');
  const body = await response.json();
  if (!Number.isSafeInteger(body.version) || body.version < 1 || typeof body.name !== 'string' || typeof body.mimeType !== 'string') throw new Error('Artifact unavailable');
  return { version: body.version, name: body.name, mimeType: body.mimeType };
}

export async function getShareContent(token: string): Promise<Blob> {
  return (await request(token, 'content')).blob();
}

export async function downloadShare(token: string, name: string): Promise<void> {
  const data = await getShareContent(token);
  // Force a download; do not navigate to or render untrusted HTML/SVG in this origin.
  const url = URL.createObjectURL(new Blob([data], { type: 'application/octet-stream' }));
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = name.replace(/[\\/\x00-\x1f\x7f]/g, '_').slice(0, 255) || 'artifact-download';
    link.rel = 'noreferrer';
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
