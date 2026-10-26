import React from 'react';
import { Theme } from '@radix-ui/themes';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@/lib/__tests__/test-i18n';
import { MCP_CATALOG_CHANGED_EVENT } from '@/chat/mcp-catalog-refresh';
import type { McpMyServerEntry } from '../../types';
import { McpServersApi } from '../../api';
import { McpAuthDialog } from '../mcp-auth-dialog';

vi.mock('../../api', () => ({ McpServersApi: { authenticate: vi.fn() } }));
const authenticate = vi.mocked(McpServersApi.authenticate);

afterEach(() => {
  cleanup();
  authenticate.mockReset();
});

function mount() {
  const onAuthenticated = vi.fn();
  render(
    <Theme>
      <McpAuthDialog
        instance={{ _id: 'mine', name: 'Source', authMode: 'api_token', requiredEnv: [], optionalEnv: [] } as unknown as McpMyServerEntry}
        open
        onOpenChange={vi.fn()}
        onAuthenticated={onAuthenticated}
      />
    </Theme>
  );
  return onAuthenticated;
}

describe('personal MCP credentials catalog', () => {
  it('invalidates only after a successful credential save', async () => {
    authenticate.mockResolvedValue({ success: true });
    const changed = vi.fn();
    window.addEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    try {
      const onAuthenticated = mount();
      fireEvent.change(screen.getByRole('dialog').querySelector('input[type="password"]')!, { target: { value: 'test-token' } });
      fireEvent.click(screen.getByRole('button', { name: /save/i }));
      await waitFor(() => expect(onAuthenticated).toHaveBeenCalledOnce());
      expect(changed).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    }
  });

  it('does not invalidate on a failed save', async () => {
    authenticate.mockRejectedValue(new Error('offline'));
    const changed = vi.fn();
    window.addEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    try {
      mount();
      fireEvent.change(screen.getByRole('dialog').querySelector('input[type="password"]')!, { target: { value: 'test-token' } });
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /save/i })); });
      expect(authenticate).toHaveBeenCalledOnce();
      expect(changed).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    }
  });
});
