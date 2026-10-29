'use client';

import { useEffect, useState } from 'react';

/** Only allow known passive raster formats after checking their signatures. */
export function rasterMime(bytes: Uint8Array): 'image/png' | 'image/jpeg' | 'image/webp' | null {
  if (bytes.length >= 8 && [137, 80, 78, 71, 13, 10, 26, 10].every((n, i) => bytes[i] === n)) return 'image/png';
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'image/jpeg';
  if (bytes.length >= 12 && String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF' && String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP') return 'image/webp';
  return null;
}

export function RasterPreview({ bytes, mime }: { bytes: Uint8Array; mime: string }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    const objectUrl = URL.createObjectURL(new Blob([new Uint8Array(bytes)], { type: mime }));
    setUrl(objectUrl);
    return () => { URL.revokeObjectURL(objectUrl); };
  }, [bytes, mime]);
  if (!url) return null;
  return <img src={url} alt="Artifact preview" style={{ maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain' }} />;
}
