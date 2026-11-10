import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SlidevRenderer } from '../slidev-renderer';

describe('SlidevRenderer', () => {
  it('runs the built deck in a script-enabled opaque-origin iframe', () => {
    render(<SlidevRenderer fileUrl="/decks/id/1/capability/index.html" fileName="slidev-presentation.zip" />);
    const frame = screen.getByTitle('Presentation preview: slidev-presentation.zip');
    expect(frame.getAttribute('src')).toBe('/decks/id/1/capability/index.html');
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    expect(frame.hasAttribute('allowfullscreen')).toBe(true);
    expect(frame.getAttribute('referrerpolicy')).toBe('no-referrer');
    expect(screen.getByRole('button', { name: 'Present' })).toBeTruthy();
    expect(frame.parentElement?.style.aspectRatio).toBe('16 / 9');
  });
});
