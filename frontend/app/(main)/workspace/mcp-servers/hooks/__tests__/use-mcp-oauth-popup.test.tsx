import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { McpServersApi } from '../../api';
import { useMcpOAuthPopup } from '../use-mcp-oauth-popup';

vi.mock('../../api', () => ({
  McpServersApi: { getOAuthAuthorizationUrl: vi.fn() },
}));

function popup() {
  return {
    closed: false,
    location: { replace: vi.fn() },
    focus: vi.fn(),
    close: vi.fn(function (this: { closed: boolean }) { this.closed = true; }),
  };
}

const getAuthorizationUrl = vi.mocked(McpServersApi.getOAuthAuthorizationUrl);

beforeEach(() => {
  vi.useFakeTimers();
  getAuthorizationUrl.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('useMcpOAuthPopup recovery', () => {
  it('treats a closed provider error page as failed even when old credentials exist', async () => {
    const providerWindow = popup();
    vi.spyOn(window, 'open').mockReturnValue(providerWindow as unknown as Window);
    getAuthorizationUrl.mockResolvedValue({ authorizationUrl: 'https://provider.example/authorize' });
    const verifyAuthenticated = vi.fn().mockResolvedValue(true);
    const onFailed = vi.fn();
    const onVerified = vi.fn();
    const { result } = renderHook(() => useMcpOAuthPopup({ verifyAuthenticated, onFailed, onVerified }));

    await act(async () => { await result.current.startOAuthPopup('instance'); });
    providerWindow.closed = true;
    act(() => { vi.advanceTimersByTime(1000); });

    expect(result.current.status).toBe('failed');
    expect(onFailed).toHaveBeenCalledOnce();
    expect(onVerified).not.toHaveBeenCalled();
    expect(verifyAuthenticated).not.toHaveBeenCalled();
  });

  it('closes the previous popup and ignores its late authorization URL on restart', async () => {
    const first = popup();
    const second = popup();
    vi.spyOn(window, 'open')
      .mockReturnValueOnce(first as unknown as Window)
      .mockReturnValueOnce(second as unknown as Window);
    let resolveFirst!: (value: { authorizationUrl: string }) => void;
    getAuthorizationUrl
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce({ authorizationUrl: 'https://provider.example/fresh' });
    const onFailed = vi.fn();
    const { result } = renderHook(() => useMcpOAuthPopup({ verifyAuthenticated: vi.fn(), onFailed }));

    let firstAttempt!: Promise<void>;
    act(() => { firstAttempt = result.current.startOAuthPopup('instance'); });
    await act(async () => { await result.current.startOAuthPopup('instance'); });
    expect(first.close).toHaveBeenCalledOnce();
    expect(second.location.replace).toHaveBeenCalledWith('https://provider.example/fresh');

    await act(async () => {
      resolveFirst({ authorizationUrl: 'https://provider.example/stale' });
      await firstAttempt;
    });
    expect(second.location.replace).toHaveBeenCalledOnce();
    expect(result.current.status).toBe('authenticating');
    expect(onFailed).not.toHaveBeenCalled();
  });
});
