import { NextFunction, Request, Response } from 'express';

/** Never send JSON parser exceptions containing raw bearer bodies to logging. */
export function suppressShareBodyParserError(error: unknown, req: Request, res: Response, next: NextFunction): void {
  if (isShareTokenRequest(req.path)) {
    res.set({ 'Cache-Control': 'no-store, private', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff' });
    res.status(404).json({ message: 'This artifact is unavailable.' });
    return;
  }
  next(error);
}

export function isShareTokenRequest(path: string): boolean {
  const normalized = path.toLowerCase();
  return normalized === '/api/v1/artifact-shares' || normalized.startsWith('/api/v1/artifact-shares/');
}
