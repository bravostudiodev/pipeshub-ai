import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Theme } from '@radix-ui/themes';
import { ArtifactsPanel } from './artifacts-panel';
import { KnowledgeBaseApi } from '@/app/(main)/knowledge-base/api';
import type { ChatArtifact } from '../../types';

vi.mock('@/app/(main)/knowledge-base/api', () => ({
  KnowledgeBaseApi: { streamDownloadRecord: vi.fn(), streamRecord: vi.fn() },
}));
vi.mock('./artifact-share-dialog', () => ({
  ArtifactShareDialog: () => <button type="button">Share artifact</button>,
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

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
