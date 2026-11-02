import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SharedArtifactPage from './page';
import * as api from './api';

vi.mock('./api', () => ({ getShareMetadata: vi.fn(), getShareContent: vi.fn(), downloadShare: vi.fn() }));
vi.mock('@/app/components/file-preview/renderers/html-renderer', () => ({ HtmlRenderer: ({ fileName }: { fileName: string }) => <div>Existing HTML preview: {fileName}</div> }));

afterEach(() => { cleanup(); vi.resetAllMocks(); window.history.replaceState(null, '', '/share/'); });

describe('shared artifact viewer', () => {
  it('shows an unavailable message for a malformed link', async () => {
    window.location.hash = '#bad';
    render(<SharedArtifactPage />);
    expect(await screen.findByText('This artifact is unavailable.')).toBeTruthy();
    expect(api.getShareMetadata).not.toHaveBeenCalled();
  });

  it('loads the fragment token without adding it to a URL and rechecks on download', async () => {
    const token = 'A'.repeat(43);
    window.location.hash = `#${token}`;
    vi.mocked(api.getShareMetadata).mockResolvedValue({ version: 2, name: 'report.txt', mimeType: 'application/octet-stream' });
    vi.mocked(api.downloadShare).mockResolvedValue();
    render(<SharedArtifactPage />);
    expect(await screen.findByText(/Version 2/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await waitFor(() => expect(api.downloadShare).toHaveBeenCalledWith(token, 'report.txt'));
    expect(api.getShareMetadata).toHaveBeenCalledWith(token);
  });

  it('loads a path token without removing it from the URL', async () => {
    const token = 'C'.repeat(43);
    window.history.replaceState(null, '', `/share/${token}`);
    vi.mocked(api.getShareMetadata).mockResolvedValue({ version: 1, name: 'report.txt', mimeType: 'application/octet-stream' });
    render(<SharedArtifactPage />);
    expect(await screen.findByText(/Version 1/)).toBeTruthy();
    expect(api.getShareMetadata).toHaveBeenCalledWith(token);
    expect(window.location.pathname).toBe(`/share/${token}`);
  });

  it('rejects a path token combined with another token', async () => {
    window.history.replaceState(null, '', `/share/${'A'.repeat(43)}?token=${'B'.repeat(43)}`);
    render(<SharedArtifactPage />);
    expect(await screen.findByText('This artifact is unavailable.')).toBeTruthy();
    expect(api.getShareMetadata).not.toHaveBeenCalled();
  });

  it('accepts a gateway-preserved query token and moves it out of the query', async () => {
    const token = 'B'.repeat(43);
    window.history.replaceState(null, '', `/share/?token=${token}`);
    vi.mocked(api.getShareMetadata).mockResolvedValue({ version: 1, name: 'report.txt', mimeType: 'application/octet-stream' });
    render(<SharedArtifactPage />);
    expect(await screen.findByText(/Version 1/)).toBeTruthy();
    expect(api.getShareMetadata).toHaveBeenCalledWith(token);
    expect(window.location.search).toBe('');
    expect(window.location.hash).toBe(`#${token}`);
  });

  it('rejects repeated token parameters rather than selecting one', async () => {
    window.history.replaceState(null, '', `/share/?token=${'A'.repeat(43)}&token=${'B'.repeat(43)}`);
    render(<SharedArtifactPage />);
    expect(await screen.findByText('This artifact is unavailable.')).toBeTruthy();
    expect(api.getShareMetadata).not.toHaveBeenCalled();
    expect(window.location.search).toBe('');
  });

  it('previews HTML inside an isolated sandbox', async () => {
    window.location.hash = `#${'A'.repeat(43)}`;
    vi.mocked(api.getShareMetadata).mockResolvedValue({ version: 1, name: 'report.html', mimeType: 'text/html' });
    vi.mocked(api.getShareContent).mockResolvedValue(new Blob(['<p>hello</p>']));
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:preview'), revokeObjectURL: vi.fn() }));
    render(<SharedArtifactPage />);
    expect(await screen.findByText('Existing HTML preview: report.html')).toBeTruthy();
  });

  it('shows unavailable after a revoked download', async () => {
    window.location.hash = `#${'A'.repeat(43)}`;
    vi.mocked(api.getShareMetadata).mockResolvedValue({ version: 1, name: 'report.txt', mimeType: 'application/octet-stream' });
    vi.mocked(api.downloadShare).mockRejectedValue(new Error('unavailable'));
    render(<SharedArtifactPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Download' }));
    expect(await screen.findByText('This artifact is unavailable.')).toBeTruthy();
  });
});
