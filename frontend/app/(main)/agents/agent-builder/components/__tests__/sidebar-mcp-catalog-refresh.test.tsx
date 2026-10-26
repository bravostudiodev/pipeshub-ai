import React from 'react';
import { Theme } from '@radix-ui/themes';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@/lib/__tests__/test-i18n';
import { MCP_CATALOG_CHANGED_EVENT } from '@/chat/mcp-catalog-refresh';
import { AgentBuilderMcpSection } from '../sidebar-mcp-section';

afterEach(cleanup);

function mount(isServiceAccount: boolean, refreshMcpServers: () => Promise<void>) {
  return render(
    <Theme>
      <AgentBuilderMcpSection
        mcpServers={[]}
        loading={false}
        refreshMcpServers={refreshMcpServers}
        mcpMergeCheckNodes={[]}
        agentKey={isServiceAccount ? 'agent-key' : null}
        isServiceAccount={isServiceAccount}
        onNotify={vi.fn()}
      />
    </Theme>
  );
}

describe('builder MCP catalog synchronization', () => {
  it('refreshes a personal catalog after a verified grant change, not an arbitrary popup message', () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    mount(false, refresh);

    act(() => {
      window.dispatchEvent(new MessageEvent('message', {
        origin: window.location.origin,
        data: { type: 'mcp_oauth_success' },
      }));
    });
    expect(refresh).not.toHaveBeenCalled();

    act(() => { window.dispatchEvent(new Event(MCP_CATALOG_CHANGED_EVENT)); });
    expect(refresh).toHaveBeenCalledOnce();
  });

  it('does not refresh service-account credentials for another user’s personal grant', () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    mount(true, refresh);
    act(() => { window.dispatchEvent(new Event(MCP_CATALOG_CHANGED_EVENT)); });
    expect(refresh).not.toHaveBeenCalled();
  });
});
