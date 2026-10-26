import React from 'react';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MCP_CATALOG_CHANGED_EVENT } from '@/chat/mcp-catalog-refresh';
import '@/lib/__tests__/test-i18n';
import PersonalMcpServersPage from '../page';

const api = vi.hoisted(() => ({
  getMyMcpServers: vi.fn(async () => ({ instances: [] })),
  removeCredentials: vi.fn(async () => ({ success: true })),
}));
const state = vi.hoisted(() => ({
  instances: [] as unknown[], isLoading: false, searchQuery: '',
  setLoading: vi.fn(), setInstances: vi.fn(), setSearchQuery: vi.fn(),
  openAuthDialog: vi.fn(), closeAuthDialog: vi.fn(), reset: vi.fn(),
  authDialog: { instance: null, open: false },
}));
const ui = vi.hoisted(() => ({ props: null as Record<string, (...args: unknown[]) => unknown> | null }));
const oauth = vi.hoisted(() => ({ callbacks: null as { onVerified: () => void } | null }));

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock('@/app/components/ui/service-gate', () => ({ ServiceGate: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@/lib/store/feature-flags-store', () => ({
  useFeatureFlagsStore: (selector: (value: object) => unknown) => selector({ loaded: true, enabled: true }),
  selectMcpEnabled: (value: { enabled: boolean }) => value.enabled,
  selectFeatureFlagsLoaded: (value: { loaded: boolean }) => value.loaded,
}));
vi.mock('../../api', () => ({ McpServersApi: api }));
vi.mock('../store', () => ({ useMcpPersonalStore: Object.assign(() => state, { getState: () => state }) }));
vi.mock('../../hooks/use-mcp-oauth-popup', () => ({
  useMcpOAuthPopup: (props: { onVerified: () => void }) => {
    oauth.callbacks = props;
    return { startOAuthPopup: vi.fn() };
  },
}));
vi.mock('../components', () => ({
  McpPersonalLayout: (props: Record<string, (...args: unknown[]) => unknown>) => { ui.props = props; return null; },
  McpAuthDialog: () => null,
}));

afterEach(() => { cleanup(); vi.clearAllMocks(); ui.props = null; oauth.callbacks = null; });

describe('personal workspace MCP catalog updates', () => {
  it('invalidates after disconnect succeeds, not when it fails', async () => {
    const changed = vi.fn();
    window.addEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    try {
      render(<PersonalMcpServersPage />);
      await waitFor(() => expect(api.getMyMcpServers).toHaveBeenCalled());
      api.removeCredentials.mockRejectedValueOnce(new Error('offline'));
      await act(async () => { await ui.props!.onRemoveCredentials({ _id: 'mine' }); });
      expect(changed).not.toHaveBeenCalled();

      await act(async () => { await ui.props!.onRemoveCredentials({ _id: 'mine' }); });
      expect(changed).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    }
  });

  it('invalidates after the OAuth popup verifies a saved grant', async () => {
    const changed = vi.fn();
    window.addEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    try {
      render(<PersonalMcpServersPage />);
      await act(async () => { oauth.callbacks!.onVerified(); });
      expect(changed).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    }
  });
});
