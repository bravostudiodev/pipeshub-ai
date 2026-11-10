/**
 * The status scheduler must never let an older, dwell-delayed status overwrite
 * a newer one or reappear after the run is parked on a question.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { useChatStore as UseChatStoreType } from '../store';

// Node 22's experimental global `localStorage` (see the `--localstorage-file`
// warning under vitest) shadows jsdom's own implementation and throws on
// first access in this environment — which crashes `auth-store.ts`'s
// import-time `hydrateAuthStore()` call, pulled in transitively via
// `@/lib/api` from `../store`/`../streaming`. Stub a working Storage before
// dynamically importing any app module below so that side effect is benign.
// (This is an environment quirk, not something Stop Generation introduces —
// the same crash pre-exists for e.g. `lib/store/__tests__/auth-store.test.ts`
// run in isolation.)
if (typeof window !== 'undefined') {
  const backing = new Map<string, string>();
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => (backing.has(key) ? (backing.get(key) as string) : null),
      setItem: (key: string, value: string) => backing.set(key, String(value)),
      removeItem: (key: string) => backing.delete(key),
      clear: () => backing.clear(),
      key: (index: number) => Array.from(backing.keys())[index] ?? null,
      get length() {
        return backing.size;
      },
    },
  });
}

vi.mock('@/lib/api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  streamSSERequest: vi.fn(),
}));

// Dynamic imports so the localStorage stub above runs first.
const { useChatStore } = (await import('../store')) as unknown as { useChatStore: typeof UseChatStoreType };
const { createStatusDwellScheduler } = await import('../streaming');

const status = (message: string, kind: 'executing' | 'calling_llm' = 'executing') => ({
  id: `status-${message}`, status: kind, message, timestamp: '2026-11-04T00:00:00.000Z',
});

describe('createStatusDwellScheduler', () => {
  let slotId: string;
  const shown = () => useChatStore.getState().slots[slotId].currentStatusMessage?.message ?? null;

  beforeEach(() => {
    vi.useFakeTimers();
    slotId = useChatStore.getState().createSlot(null);
  });
  afterEach(() => vi.useRealTimers());

  it('does not let a delayed tool status overwrite a newer one', () => {
    const scheduler = createStatusDwellScheduler(slotId, () => true);
    scheduler.scheduleStatus(status('Using Slack Search...'));
    scheduler.scheduleStatus(status('Loading skill...'));
    scheduler.applyStatus(status('Thinking...', 'calling_llm'));
    vi.advanceTimersByTime(2000);
    expect(shown()).toBe('Thinking...');
  });

  it('does not resurface a delayed status after the run parks on a question', () => {
    const scheduler = createStatusDwellScheduler(slotId, () => true);
    scheduler.scheduleStatus(status('Using Slack Search...'));
    scheduler.scheduleStatus(status('Loading skill...'));
    scheduler.stopIdleStatus();
    vi.advanceTimersByTime(2000);
    expect(shown()).toBeNull();
  });

  it('still shows a scheduled status after the dwell window', () => {
    const scheduler = createStatusDwellScheduler(slotId, () => true);
    scheduler.scheduleStatus(status('Using Slack Search...'));
    scheduler.scheduleStatus(status('Loading skill...'));
    vi.advanceTimersByTime(2000);
    expect(shown()).toBe('Loading skill...');
  });
});
