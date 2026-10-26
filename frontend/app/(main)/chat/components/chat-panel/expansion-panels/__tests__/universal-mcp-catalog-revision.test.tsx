import React from 'react';
import { Theme } from '@radix-ui/themes';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import '@/lib/__tests__/test-i18n';
import { notifyMcpCatalogChanged } from '@/chat/mcp-catalog-refresh';
import { useChatStore } from '@/chat/store';
import type { McpMyServerEntry } from '@/app/(main)/workspace/mcp-servers/types';
import { McpServersApi } from '@/app/(main)/workspace/mcp-servers/api';
import { UniversalAgentResourcesPanel } from '../universal-agent-resources-panel';

const auth = vi.hoisted(() => ({
  accessToken: `header.${Buffer.from('{"userId":"user","orgId":"org"}').toString('base64url')}.signature`,
}));
vi.mock('@/lib/store/auth-store', () => ({
  useAuthStore: Object.assign(
    (selector: (state: typeof auth) => unknown) => selector(auth),
    { getState: () => auth },
  ),
}));
vi.mock('@/lib/store/feature-flags-store', () => ({
  useFeatureFlagsStore: (selector: (state: object) => unknown) => selector({ mcp: true, actions: false }),
  selectMcpEnabled: (state: { mcp: boolean }) => state.mcp,
  selectActionsEnabled: (state: { actions: boolean }) => state.actions,
}));
vi.mock('@/app/components/theme-provider', () => ({ useThemeAppearance: () => ({ appearance: 'light' }) }));
vi.mock('../connectors-collections/collections-tab', () => ({ CollectionsTab: () => null }));
vi.mock('@/app/(main)/workspace/mcp-servers/api', () => ({
  McpServersApi: { getMyMcpServers: vi.fn() },
}));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('refetches after a grant changes while the resources panel is closed', async () => {
  const getMyMcpServers = vi.mocked(McpServersApi.getMyMcpServers);
  getMyMcpServers
    .mockResolvedValueOnce({ instances: [{
      _id: 'mine', name: 'Drive', isAuthenticated: true,
      tools: [{ name: 'search', namespacedName: 'mcp_drive_search', inputSchema: {} }],
    } as McpMyServerEntry] })
    .mockResolvedValue({ instances: [] });
  const panel = () => render(<Theme><UniversalAgentResourcesPanel /></Theme>);

  const first = panel();
  await waitFor(() => expect(useChatStore.getState().universalAgentMcpGroups).toHaveLength(1));
  expect(getMyMcpServers).toHaveBeenCalledTimes(1);
  first.unmount();

  act(() => notifyMcpCatalogChanged());
  panel();
  await waitFor(() => expect(getMyMcpServers).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(useChatStore.getState().universalAgentMcpGroups).toHaveLength(0));
});
