import { describe, expect, it } from 'vitest';
import { rasterMime } from './raster-preview';

describe('shared raster format detection', () => {
  it('accepts only supported raster signatures', () => {
    expect(rasterMime(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]))).toBe('image/png');
    expect(rasterMime(new Uint8Array([255, 216, 255]))).toBe('image/jpeg');
    expect(rasterMime(new TextEncoder().encode('RIFF1234WEBP'))).toBe('image/webp');
    expect(rasterMime(new TextEncoder().encode('<svg onload="alert(1)">'))).toBeNull();
    expect(rasterMime(new Uint8Array([137, 80]))).toBeNull();
  });
});
