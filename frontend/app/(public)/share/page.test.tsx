import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SharedArtifactPage from './page';
import * as api from './api';

vi.mock('./api', () => ({ getShareMetadata: vi.fn(), getShareContent: vi.fn(), downloadShare: vi.fn() }));
vi.mock('@/app/components/file-preview/renderers/file-preview-renderer', () => ({ FilePreviewRenderer: ({ fileName, fileType, fileUrl }: { fileName: string; fileType: string; fileUrl: string }) => fileType === 'application/vnd.oddjeeves.slidev-preview' ? <iframe title={`Presentation preview: ${fileName}`} sandbox="allow-scripts" src={fileUrl} /> : <div>Existing preview: {fileName} ({fileType})</div> }));

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

  it('previews a pinned Slidev ZIP through the isolated deck route', async () => {
    const token = 'D'.repeat(43);
    window.history.replaceState(null, '', `/share/${token}`);
    vi.mocked(api.getShareMetadata).mockResolvedValue({
      version: 4, name: 'jeeves-qa-slidev.zip', mimeType: 'application/zip', isDeck: true,
    });
    render(<SharedArtifactPage />);
    const frame = await screen.findByTitle('Presentation preview: jeeves-qa-slidev.zip');
    expect(frame.getAttribute('src')).toBe(`/decks/shared/${token}/index.html`);
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    expect(api.getShareContent).not.toHaveBeenCalled();
    // The deck's own Present control replaces the page-level full screen button.
    expect(screen.queryByRole('button', { name: 'Full screen' })).toBeNull();
  });

  it('previews HTML inside an isolated sandbox', async () => {
    window.location.hash = `#${'A'.repeat(43)}`;
    vi.mocked(api.getShareMetadata).mockResolvedValue({ version: 1, name: 'report.html', mimeType: 'text/html' });
    vi.mocked(api.getShareContent).mockResolvedValue(new Blob(['<p>hello</p>']));
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:preview'), revokeObjectURL: vi.fn() }));
    render(<SharedArtifactPage />);
    expect(await screen.findByText('Existing preview: report.html (text/html)')).toBeTruthy();
  });

  it('converts the pinned PowerPoint to PDF and uses the chat preview renderer', async () => {
    const token = 'P'.repeat(43);
    window.location.hash = `#${token}`;
    vi.mocked(api.getShareMetadata).mockResolvedValue({ version: 3, name: 'slides.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' });
    vi.mocked(api.getShareContent).mockResolvedValue(new Blob(['%PDF-1.4']));
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:slides'), revokeObjectURL: vi.fn() }));
    render(<SharedArtifactPage />);
    expect(await screen.findByText('Existing preview: slides.pptx (application/vnd.oddjeeves.presentation-preview)')).toBeTruthy();
    expect(api.getShareContent).toHaveBeenCalledWith(token, true);
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
