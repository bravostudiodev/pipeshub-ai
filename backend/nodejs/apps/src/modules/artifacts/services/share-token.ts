import { createHash, randomBytes } from 'crypto';

// A token is 256 bits, encoded without padding for use in a URL fragment.
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export function createShareToken(): string {
  return randomBytes(32).toString('base64url');
}

/** Return null for malformed or non-canonical tokens; never log the input. */
export function hashShareToken(token: unknown): string | null {
  if (typeof token !== 'string' || !TOKEN_PATTERN.test(token)) return null;
  const bytes = Buffer.from(token, 'base64url');
  if (bytes.length !== 32 || bytes.toString('base64url') !== token) return null;
  return createHash('sha256').update(bytes).digest('hex');
}
