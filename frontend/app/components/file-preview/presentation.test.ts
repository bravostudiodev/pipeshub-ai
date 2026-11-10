import { describe, expect, it } from 'vitest';
import { isPresentationArchive, presentationTitle } from './presentation';

describe('presentation helpers', () => {
  it('recognises deck archives, including older OTHER-typed ones', () => {
    expect(isPresentationArchive({ fileName: 'Q4.zip', mimeType: 'application/zip', artifactType: 'PRESENTATION' })).toBe(true);
    expect(isPresentationArchive({ fileName: 'q4.zip', mimeType: 'application/zip', artifactType: 'OTHER' })).toBe(true);
    expect(isPresentationArchive({ fileName: 'q4.zip', mimeType: 'application/octet-stream' })).toBe(true);
    expect(isPresentationArchive({ fileName: 'data.zip', mimeType: 'application/zip', artifactType: 'DATA_FILE' })).toBe(false);
    expect(isPresentationArchive({ fileName: 'deck.pptx', mimeType: 'application/vnd.ms-powerpoint' })).toBe(false);
  });

  it('turns file names into display titles', () => {
    expect(presentationTitle('Q4 OKR Review.zip')).toBe('Q4 OKR Review');
    expect(presentationTitle('oddbytes-q4-okrs.zip')).toBe('oddbytes q4 okrs');
    expect(presentationTitle('.zip')).toBe('Presentation');
  });
});
