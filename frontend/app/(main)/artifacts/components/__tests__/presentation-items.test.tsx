import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { Theme } from '@radix-ui/themes';

import '@/lib/__tests__/test-i18n';
import type { ArtifactListItem } from '../../types';
import { ArtifactsListView } from '../artifacts-list-view';
import { ArtifactsGridView } from '../artifacts-grid-view';
import { artifactDisplayName, isDeckItem } from '../../deck-items';

const fileIcon = vi.fn();
vi.mock('@/app/components/ui', () => ({ FileIcon: (props: Record<string, unknown>) => { fileIcon(props); return null; } }));
vi.mock('@/app/components/ui/MaterialIcon', () => ({ MaterialIcon: () => null }));

const PAGINATION = { page: 1, limit: 50, totalCount: 1, totalPages: 1 };
const deck: ArtifactListItem = {
  artifactId: 'd1', name: 'Q4 OKR Review.zip', artifactType: 'PRESENTATION', mimeType: 'application/zip', version: 2,
};
const handlers = { onPreview: vi.fn(), onDownload: vi.fn(), onOpenChat: vi.fn(), onPageChange: vi.fn() };

afterEach(() => { cleanup(); fileIcon.mockClear(); });

describe('decks in the artifacts gallery', () => {
  it('are recognised and shown by title', () => {
    expect(isDeckItem(deck)).toBe(true);
    expect(artifactDisplayName(deck)).toBe('Q4 OKR Review');
    expect(isDeckItem({ ...deck, name: 'rows.csv', mimeType: 'text/csv', artifactType: 'DATA_FILE' })).toBe(false);
  });

  it.each([
    ['list', (items: ArtifactListItem[]) => (
      <ArtifactsListView items={items} sortBy="name" sortOrder="asc" onSort={vi.fn()} pagination={PAGINATION} {...handlers} />
    )],
    ['grid', (items: ArtifactListItem[]) => <ArtifactsGridView items={items} pagination={PAGINATION} {...handlers} />],
  ])('show a presentation icon and no .zip in the %s view', (_view, renderView) => {
    render(<Theme>{renderView([deck])}</Theme>);
    expect(screen.getByText('Q4 OKR Review')).toBeTruthy();
    expect(screen.queryByText(/\.zip/)).toBeNull();
    expect(fileIcon).toHaveBeenCalledWith(expect.objectContaining({ extension: 'pptx' }));
  });
});
