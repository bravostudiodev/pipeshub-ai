import React from 'react';
import { Theme } from '@radix-ui/themes';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@/lib/__tests__/test-i18n';
import { MCP_CATALOG_CHANGED_EVENT } from '@/chat/mcp-catalog-refresh';
import type { McpMyServerEntry } from '@/app/(main)/workspace/mcp-servers/types';
import { McpCredentialsDialog } from '../agent-mcp-credentials-dialog';

const api = vi.hoisted(() => ({
  authenticate: vi.fn(async () => ({})),
  authenticateAgentInstance: vi.fn(async () => ({})),
}));
vi.mock('@/app/(main)/workspace/mcp-servers/api', () => ({ McpServersApi: api }));
vi.mock('@/app/(main)/workspace/mcp-servers/hooks/use-mcp-oauth-popup', () => ({
  useMcpOAuthPopup: () => ({ startOAuthPopup: vi.fn(), status: 'idle' }),
}));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function mount(agentKey?: string) {
  render(
    <Theme>
      <McpCredentialsDialog
        instance={{ _id: 'mine', name: 'Source', authMode: 'api_token',
          isAuthenticated: false, requiredEnv: [], optionalEnv: [] } as McpMyServerEntry}
        agentKey={agentKey}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    </Theme>
  );
  fireEvent.change(screen.getByRole('dialog').querySelector('input[type="password"]')!, {
    target: { value: 'test-token' },
  });
  fireEvent.click(screen.getByRole('button', { name: /save credentials/i }));
}

describe('builder MCP credential scope', () => {
  it('invalidates personal catalogs only after a successful personal credential save', async () => {
    const changed = vi.fn();
    window.addEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    try {
      mount();
      await waitFor(() => expect(api.authenticate).toHaveBeenCalledOnce());
      await waitFor(() => expect(changed).toHaveBeenCalledOnce());
    } finally {
      window.removeEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    }
  });

  it('does not invalidate personal catalogs when saving agent-owned credentials', async () => {
    const changed = vi.fn();
    window.addEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    try {
      mount('agent-key');
      await waitFor(() => expect(api.authenticateAgentInstance).toHaveBeenCalledOnce());
      expect(changed).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    }
  });

  it('does not invalidate personal catalogs on a failed save', async () => {
    api.authenticate.mockRejectedValueOnce(new Error('offline'));
    const changed = vi.fn();
    window.addEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    try {
      mount();
      await waitFor(() => expect(api.authenticate).toHaveBeenCalledOnce());
      await screen.findByText('offline');
      expect(changed).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    }
  });
});
