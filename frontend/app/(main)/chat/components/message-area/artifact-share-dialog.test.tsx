import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ArtifactShareDialog } from './artifact-share-dialog';
import { apiClient } from '@/lib/api';

vi.mock('@/lib/api', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe('artifact sharing dialog', () => {
  it('requires explicit creation and defaults to seven days', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { shares: [] } });
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: 'share', token: 'secret', expiresAt: '2030-01-01T00:00:00Z' } });
    render(<ArtifactShareDialog artifactId="artifact" version={2} />);
    fireEvent.click(screen.getByRole('button', { name: 'Share artifact' }));
    expect(await screen.findByText(/Anyone who can access this link/)).toBeTruthy();
    expect(apiClient.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Create link' }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/api/v1/artifacts/artifact/shares', { version: 2, expiresInDays: 7 }));
    const link = (await screen.findByLabelText('Share link') as HTMLInputElement).value;
    expect(link).toContain('/share/#secret');
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    fireEvent.click(screen.getByRole('button', { name: 'Copy link' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(link));
    expect(await screen.findByText('Link copied.')).toBeTruthy();
  });

  it('lists active links and can stop sharing', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { shares: [{ _id: 'id', version: 1, expiresAt: '2030-01-01T00:00:00Z' }] } });
    vi.mocked(apiClient.delete).mockResolvedValue({});
    render(<ArtifactShareDialog artifactId="artifact" version={1} />);
    fireEvent.click(screen.getByRole('button', { name: 'Share artifact' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop sharing' }));
    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith('/api/v1/artifacts/artifact/shares/id'));
    expect(screen.getByText(/cannot remove copies already downloaded/)).toBeTruthy();
  });
});
