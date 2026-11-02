import { NextFunction, Request, Response } from 'express';
import path from 'path';

/** Never send JSON parser exceptions containing raw bearer bodies to logging. */
export function suppressShareBodyParserError(error: unknown, req: Request, res: Response, next: NextFunction): void {
  if (isShareTokenRequest(req.path)) {
    res.set({ 'Cache-Control': 'no-store, private', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff' });
    res.status(404).json({ message: 'This artifact is unavailable.' });
    return;
  }
  next(error);
}

export function isShareViewerRequest(path: string): boolean {
  return /^\/share(?:\/[^/]+)?\/?$/i.test(path);
}

export function sendShareViewerShell(req: Request, res: Response, publicDir: string): boolean {
  if (!/^\/share\/[^/]+\/?$/i.test(req.path)) return false;
  res.set({ 'Cache-Control': 'no-store, private', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff' });
  res.sendFile(path.join(publicDir, 'share', 'index.html'));
  return true;
}

export function isShareTokenRequest(path: string): boolean {
  const normalized = path.toLowerCase();
  return normalized === '/api/v1/artifact-shares' || normalized.startsWith('/api/v1/artifact-shares/');
}
