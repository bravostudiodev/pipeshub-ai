import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  isAdmin: true,
  flagsLoaded: true,
  mcpEnabled: true,
  traceEnabled: true,
  replace: vi.fn(),
  list: vi.fn(),
  compare: vi.fn(),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: mocks.replace }) }));
vi.mock('@/lib/store/user-store', () => ({
  useUserStore: (selector: (state: { profile: { isAdmin: boolean }; isInitialized: boolean }) => unknown) =>
    selector({ profile: { isAdmin: mocks.isAdmin }, isInitialized: true }),
  selectIsAdmin: (state: { profile: { isAdmin: boolean } }) => state.profile.isAdmin,
  selectIsProfileInitialized: (state: { isInitialized: boolean }) => state.isInitialized,
}));
vi.mock('@/lib/store/feature-flags-store', () => ({
  useFeatureFlagsStore: (selector: (state: { flags: Record<string, boolean> }) => unknown) =>
    selector({ flags: { ENABLE_MCP: mocks.mcpEnabled, ENABLE_MCP_RETRIEVAL_TRACE: mocks.traceEnabled } }),
  selectFeatureFlagsLoaded: () => mocks.flagsLoaded,
  selectMcpEnabled: () => mocks.mcpEnabled,
  selectMcpRetrievalTraceEnabled: () => mocks.traceEnabled,
}));
vi.mock('../../api', () => ({
  McpServersApi: {
    getMcpRetrievalTraces: (runIds?: string[]) => runIds ? mocks.compare(runIds) : mocks.list(),
  },
}));

import McpDiagnosticsPage from '../page';

const runA = {
  runId: 'run-a', traceId: 'trace-a', userId: 'user-a', effectiveUserId: 'user-a', orgId: 'org-1',
  startedAt: '2026-10-06T10:00:00Z', expiresAt: '2026-10-13T10:00:00Z',
};
const runB = {
  runId: 'run-b', traceId: 'trace-b', userId: 'user-b', effectiveUserId: 'user-b', orgId: 'org-1',
  startedAt: '2026-10-06T10:01:00Z', expiresAt: '2026-10-13T10:01:00Z',
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  mocks.isAdmin = true;
  mocks.flagsLoaded = true;
  mocks.mcpEnabled = true;
  mocks.traceEnabled = true;
});

describe('MCP diagnostics page', () => {
  it('lets an administrator compare two runs and renders only safe metadata', async () => {
    mocks.list.mockResolvedValue({ runs: [runA, runB], truncated: false });
    mocks.compare.mockResolvedValue({
      truncated: false,
      runs: [
        { ...runA, events: [{
          ...runA, eventId: 'e1', eventType: 'invocation', recordedAt: runA.startedAt,
          instanceId: 'mcp-1', serverName: 'Slack', toolName: 'search_messages', outcome: 'success', durationMs: 18,
          arguments: { channel_id: 'C123', limit: 5 },
          response: { resultCount: 5, oldestTimestamp: '2026-10-06T09:00:00Z', newestTimestamp: '2026-10-06T10:00:00Z' },
          rawResponse: 'CONFIDENTIAL MESSAGE BODY', query: 'CONFIDENTIAL SEARCH PHRASE',
        }] },
        { ...runB, events: [{
          ...runB, eventId: 'e2', eventType: 'discovery', recordedAt: runB.startedAt,
          instanceId: 'mcp-1', serverName: 'Slack', authMode: 'oauth', transport: 'streamable_http',
          credentialOwnerId: 'user-b', credentialExists: true, credentialScopes: ['channels:history'],
          tools: [{ name: 'search_messages', schemaFingerprint: 'sha256-fingerprint' }],
        }] },
      ],
    });

    render(<McpDiagnosticsPage />);
    await screen.findByText('run-a');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select run run-a' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select run run-b' }));
    fireEvent.click(screen.getByRole('button', { name: 'Compare selected runs' }));

    await screen.findByText('search_messages');
    expect(mocks.compare).toHaveBeenCalledWith(['run-a', 'run-b']);
    expect(screen.getByText(/OAuth scopes:.*channels:history/)).toBeTruthy();
    expect(screen.getByText(/sha256-fingerprint/)).toBeTruthy();
    expect(screen.getByText(/Result count: 5/)).toBeTruthy();
    expect(screen.queryByText(/CONFIDENTIAL/)).toBeNull();
  });

  it('does not load trace data for a non-admin and redirects them out of diagnostics', async () => {
    mocks.isAdmin = false;
    mocks.list.mockResolvedValue({ runs: [], truncated: false });
    render(<McpDiagnosticsPage />);
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith('/workspace/general/'));
    expect(mocks.list).not.toHaveBeenCalled();
    expect(screen.queryByText('MCP Diagnostics')).toBeNull();
  });
});
