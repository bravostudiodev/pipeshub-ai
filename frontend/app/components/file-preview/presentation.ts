const ZIP_MIME_TYPES = ['application/zip', 'application/x-zip-compressed'];

interface PresentationCandidate {
  fileName: string;
  mimeType?: string;
  artifactType?: string;
}

/**
 * A Slidev deck delivered as a ZIP. New decks are registered as PRESENTATION;
 * older ones were stored as OTHER, and the chat preview already treats every
 * ZIP artifact as a deck, so this matches that.
 */
export function isPresentationArchive({ fileName, mimeType, artifactType }: PresentationCandidate): boolean {
  const isZip =
    ZIP_MIME_TYPES.includes(mimeType ?? '') ||
    (['application/octet-stream', '', undefined].includes(mimeType) && fileName.toLowerCase().endsWith('.zip'));
  if (!isZip) return false;
  return artifactType === undefined || artifactType === 'PRESENTATION' || artifactType === 'OTHER';
}

/** The deck's display title: the file name without `.zip`; older slug names get spaces. */
export function presentationTitle(fileName: string): string {
  const stem = fileName.replace(/\.zip$/i, '').trim();
  const title = /\s/.test(stem) ? stem : stem.replace(/[-_]+/g, ' ').trim();
  return title || 'Presentation';
}

/**
 * Save the deck as one self-contained HTML file that opens in any browser.
 * `indexUrl` is the same-origin preview URL of the deck's `index.html`.
 */
export async function downloadPresentationHtml(indexUrl: string, title: string): Promise<void> {
  const response = await fetch(indexUrl, { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`Presentation download failed (${response.status})`);
  const blob = new Blob([await response.blob()], { type: 'text/html' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${title.replace(/[\\/:*?"<>|]+/g, ' ').trim() || 'Presentation'}.html`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
