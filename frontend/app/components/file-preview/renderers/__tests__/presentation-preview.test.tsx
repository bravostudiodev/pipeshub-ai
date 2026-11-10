import { describe, expect, it } from 'vitest';
import { isPresentationPreview, shouldShowPagination } from '../../utils';

describe('presentation preview controls', () => {
  it('uses slide controls instead of the PDF overlay for converted presentations', () => {
    expect(isPresentationPreview('application/vnd.oddjeeves.presentation-preview', 'Jeeves-QA-State-of-Play.pptx')).toBe(true);
    expect(shouldShowPagination('application/vnd.oddjeeves.presentation-preview', 'Jeeves-QA-State-of-Play.pptx', null, false, false).shouldShow).toBe(false);
    expect(shouldShowPagination('application/pdf', 'deck.pptx', null, false, false).shouldShow).toBe(false);
  });

  it('keeps the PDF toolbar for ordinary PDF files', () => {
    expect(shouldShowPagination('application/pdf', 'report.pdf', null, false, false).shouldShow).toBe(true);
  });
});
