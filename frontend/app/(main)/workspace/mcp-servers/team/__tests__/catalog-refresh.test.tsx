import React from 'react';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MCP_CATALOG_CHANGED_EVENT } from '@/chat/mcp-catalog-refresh';
import '@/lib/__tests__/test-i18n';
import TeamMcpServersPage from '../page';

const api = vi.hoisted(() => ({
  getCatalog: vi.fn(async () => ({ templates: [] })),
  getMyMcpServers: vi.fn(async () => ({ instances: [] })),
  getInstanceTools: vi.fn(async () => ({ tools: [] })),
  removeCredentials: vi.fn(async () => ({ success: true })),
}));
const state = vi.hoisted(() => ({
  templates: [], instances: [], isLoading: false, searchQuery: '',
  configPanel: { open: false, mode: 'create', editingInstance: null, prefillTemplate: null },
  deleteTarget: null,
  setLoading: vi.fn(), setTemplates: vi.fn(), setInstances: vi.fn(),
  closeDeleteDialog: vi.fn(), closeConfigPanel: vi.fn(), reset: vi.fn(),
}));
const ui = vi.hoisted(() => ({
  details: null as Record<string, (...args: unknown[]) => unknown> | null,
  config: null as Record<string, (...args: unknown[]) => unknown> | null,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams('typeId=example'),
}));
vi.mock('@/app/components/ui/service-gate', () => ({ ServiceGate: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@/lib/store/user-store', () => ({
  useUserStore: (selector: (value: object) => unknown) => selector({ admin: true, loaded: true }),
  selectIsAdmin: (value: { admin: boolean }) => value.admin,
  selectIsProfileInitialized: (value: { loaded: boolean }) => value.loaded,
}));
vi.mock('@/lib/store/feature-flags-store', () => ({
  useFeatureFlagsStore: (selector: (value: object) => unknown) => selector({ loaded: true, enabled: true }),
  selectMcpEnabled: (value: { enabled: boolean }) => value.enabled,
  selectFeatureFlagsLoaded: (value: { loaded: boolean }) => value.loaded,
}));
vi.mock('../../api', () => ({ McpServersApi: api }));
vi.mock('../store', () => ({ useMcpTeamStore: Object.assign(() => state, { getState: () => state }) }));
vi.mock('../../hooks/use-mcp-oauth-popup', () => ({ useMcpOAuthPopup: () => ({ startOAuthPopup: vi.fn() }) }));
vi.mock('../../components', () => ({ McpAuthDialog: () => null }));
vi.mock('../components', () => ({
  McpServerDetailsLayout: (props: Record<string, (...args: unknown[]) => unknown>) => { ui.details = props; return null; },
  McpInstanceConfigPanel: (props: Record<string, (...args: unknown[]) => unknown>) => { ui.config = props; return null; },
}));
vi.mock('../../../components', () => ({ ConfirmationDialog: () => null }));

afterEach(() => { cleanup(); vi.clearAllMocks(); ui.details = null; ui.config = null; });

describe('workspace MCP catalog updates', () => {
  it('invalidates after a successful disconnect, not on failure', async () => {
    const changed = vi.fn();
    window.addEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    try {
      render(<TeamMcpServersPage />);
      await waitFor(() => expect(api.getMyMcpServers).toHaveBeenCalled());
      api.removeCredentials.mockRejectedValueOnce(new Error('offline'));
      await act(async () => { await ui.details!.onDisconnect({ _id: 'mine' }); });
      expect(changed).not.toHaveBeenCalled();

      await act(async () => { await ui.details!.onDisconnect({ _id: 'mine' }); });
      expect(changed).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    }
  });

  it('discards an in-flight tool discovery after configuration changes', async () => {
    let resolveTools!: (value: { tools: { name: string }[] }) => void;
    api.getInstanceTools.mockImplementationOnce(() => new Promise((resolve) => { resolveTools = resolve; }));
    render(<TeamMcpServersPage />);
    await waitFor(() => expect(api.getMyMcpServers).toHaveBeenCalled());

    act(() => { ui.details!.onDiscoverTools({ _id: 'mine' }); });
    act(() => { ui.config!.onSaved(); });
    await act(async () => { resolveTools({ tools: [{ name: 'stale' }] }); });

    expect(ui.details!.toolsState).toEqual({});
  });
});
