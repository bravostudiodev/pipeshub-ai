import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Theme } from '@radix-ui/themes';
import { ArtifactsPanel } from './artifacts-panel';
import { KnowledgeBaseApi } from '@/app/(main)/knowledge-base/api';
import type { ChatArtifact } from '../../types';

vi.mock('@/app/(main)/knowledge-base/api', () => ({
  KnowledgeBaseApi: { streamDownloadRecord: vi.fn(), streamRecord: vi.fn(), createDeckPreview: vi.fn() },
}));
vi.mock('./artifact-share-dialog', () => ({
  ArtifactShareDialog: () => <button type="button">Share artifact</button>,
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

const artifact: ChatArtifact = {
  id: 'a', fileName: 'report.html', mimeType: 'text/html', sizeBytes: 100,
  artifactType: 'DOCUMENT', downloadUrl: '', recordId: 'record', version: 1,
  derivedFromCodeArtifactId: 'source',
};

describe('artifact card', () => {
  it('opens preview from the card and keeps action buttons independent', async () => {
    const preview = vi.fn();
    const viewSource = vi.fn();
    vi.mocked(KnowledgeBaseApi.streamDownloadRecord).mockResolvedValue(undefined);
    render(<Theme><ArtifactsPanel artifacts={[artifact]} onPreview={preview} onViewSource={viewSource} /></Theme>);
    const card = screen.getByRole('button', { name: 'Preview report.html' });
    expect(card.style.cursor).toBe('pointer');
    fireEvent.click(card);
    await waitFor(() => expect(preview).toHaveBeenCalledWith(artifact));
    preview.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Share artifact' }));
    fireEvent.click(screen.getByRole('button', { name: 'View source code' }));
    fireEvent.click(screen.getByRole('button', { name: 'Download artifact' }));
    await waitFor(() => expect(KnowledgeBaseApi.streamDownloadRecord).toHaveBeenCalled());
    expect(viewSource).toHaveBeenCalledWith('source');
    expect(preview).not.toHaveBeenCalled();
  });

  it('does not offer a clickable card when preview is unavailable', () => {
    render(<Theme><ArtifactsPanel artifacts={[artifact]} /></Theme>);
    expect(screen.queryByRole('button', { name: 'Preview report.html' })).toBeNull();
  });
});

describe('presentation card', () => {
  const deck: ChatArtifact = {
    id: 'd', fileName: 'Q4 OKR Review.zip', mimeType: 'application/zip', sizeBytes: 2048,
    artifactType: 'PRESENTATION', downloadUrl: '', recordId: 'deck-record', version: 3,
  };

  it('shows the deck as a titled presentation, not a ZIP', () => {
    render(<Theme><ArtifactsPanel artifacts={[deck]} onPreview={vi.fn()} /></Theme>);
    expect(screen.getByText('Q4 OKR Review')).toBeTruthy();
    expect(screen.queryByText(/\.zip/)).toBeNull();
    expect(screen.getByText(/Presentation/)).toBeTruthy();
    expect(screen.getByText('slideshow')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Preview Q4 OKR Review' })).toBeTruthy();
  });

  it('downloads a self-contained HTML file named after the deck', async () => {
    vi.mocked(KnowledgeBaseApi.createDeckPreview).mockResolvedValue('/decks/cap/index.html');
    const fetchMock = vi.fn().mockResolvedValue(new Response('<html></html>', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const createUrl = vi.fn(() => 'blob:deck');
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: vi.fn() }));
    const clicked: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    });

    render(<Theme><ArtifactsPanel artifacts={[deck]} /></Theme>);
    fireEvent.click(screen.getByRole('button', { name: 'Download presentation' }));

    await waitFor(() => expect(clicked).toEqual(['Q4 OKR Review.html']));
    expect(KnowledgeBaseApi.createDeckPreview).toHaveBeenCalledWith('deck-record', 3);
    expect(fetchMock).toHaveBeenCalledWith('/decks/cap/index.html', { credentials: 'same-origin' });
    expect(KnowledgeBaseApi.streamDownloadRecord).not.toHaveBeenCalled();
    click.mockRestore();
  });

  it('falls back to the ZIP when the HTML cannot be fetched', async () => {
    vi.mocked(KnowledgeBaseApi.createDeckPreview).mockRejectedValue(new Error('unavailable'));
    vi.mocked(KnowledgeBaseApi.streamDownloadRecord).mockResolvedValue(undefined);
    render(<Theme><ArtifactsPanel artifacts={[deck]} /></Theme>);
    fireEvent.click(screen.getByRole('button', { name: 'Download presentation' }));
    await waitFor(() =>
      expect(KnowledgeBaseApi.streamDownloadRecord).toHaveBeenCalledWith('deck-record', 'Q4 OKR Review.zip', { version: 3 }),
    );
  });
});
