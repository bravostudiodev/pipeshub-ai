import { decodeJwtPayload } from '@/lib/api/token-refresh';
import { useAuthStore } from '@/lib/store/auth-store';

/** Identity is a cache partition, never an authority check (the API enforces auth). */
export function catalogIdentityFromToken(token: string | null): string | null {
  const claims = decodeJwtPayload(token);
  const userId = claims?.userId;
  const orgId = claims?.orgId;
  return typeof userId === 'string' && userId && typeof orgId === 'string' && orgId
    ? `${orgId.length}:${orgId}${userId.length}:${userId}`
    : null;
}

export function currentCatalogIdentity(): string | null {
  return catalogIdentityFromToken(useAuthStore.getState().accessToken);
}

export const MCP_CATALOG_CHANGED_EVENT = 'oddjeeves:mcp-catalog-changed';
let revision = 0;

export function mcpCatalogRevision(): number { return revision; }

/** Only after a successful user-bound grant/revoke, not after a failed popup. */
export function notifyMcpCatalogChanged(): void {
  revision += 1;
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(MCP_CATALOG_CHANGED_EVENT));
}
