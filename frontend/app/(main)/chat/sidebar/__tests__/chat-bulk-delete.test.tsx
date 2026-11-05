import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import '@/lib/__tests__/test-i18n';
import { installBrowserShims, renderInTheme } from '@/app/(main)/agents/agent-builder/__tests__/agent-builder-harness';

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }));
const route = vi.hoisted(() => ({ params: new URLSearchParams() }));
vi.mock('next/navigation', () => ({
  useRouter: () => router,
  useSearchParams: () => route.params,
  usePathname: () => '/chat/',
}));

const chatApi = vi.hoisted(() => ({ deleteConversation: vi.fn() }));
vi.mock('@/chat/api', () => ({ ChatApi: chatApi }));
vi.mock('@/app/(main)/agents/api', () => ({ AgentsApi: { deleteAgentConversation: vi.fn() } }));
vi.mock('@/chat/project-api', () => ({ ProjectApi: {} }));
vi.mock('@/app/components/ui/MaterialIcon', () => ({ MaterialIcon: () => null }));

import { ChatSection } from '../chat-section';
import { useChatStore } from '@/chat/store';
import { useSidebarSelectionStore } from '../selection-store';
import type { Conversation } from '@/chat/types';

function conversation(id: string, title: string, isOwner = true): Conversation {
  return { id, title, isOwner } as unknown as Conversation;
}

const today = [conversation('c1', 'Slack channel'), conversation('c2', 'Sales data')];
const yesterday = [conversation('c3', 'Q4 goals')];

function renderSection() {
  return renderInTheme(
    <ChatSection
      isLoading={false}
      hasError={false}
      currentConversationId={null}
      onSelectConversation={() => undefined}
      onNewChat={() => undefined}
      skeletonCount={1}
      timeGroups={[['Today', today], ['Yesterday', yesterday]]}
    />,
  );
}

describe('Bulk chat deletion from the sidebar', () => {
  beforeEach(() => {
    installBrowserShims();
    chatApi.deleteConversation.mockReset().mockResolvedValue(undefined);
    useSidebarSelectionStore.getState().clear();
    useChatStore.setState({ conversations: [...today, ...yesterday] });
  });
  afterEach(() => cleanup());

  it('selects a whole time group and deletes only those chats', async () => {
    renderSection();

    fireEvent.click(screen.getByRole('checkbox', { name: /select all chats in today/i }));
    expect(await screen.findByText('2 selected')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(chatApi.deleteConversation).toHaveBeenCalledTimes(2));
    expect(chatApi.deleteConversation.mock.calls.map(([id]) => id).sort()).toEqual(['c1', 'c2']);
    await waitFor(() => expect(screen.queryByText('2 selected')).toBeNull());
    expect(useChatStore.getState().conversations.map((c) => c.id)).toEqual(['c3']);
  });

  it('keeps chats whose deletion failed selected and says so', async () => {
    chatApi.deleteConversation.mockImplementation(async (id: string) => {
      if (id === 'c2') throw new Error('nope');
    });
    renderSection();

    fireEvent.click(screen.getByRole('checkbox', { name: /select all chats in today/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('1 selected')).toBeTruthy();
    expect(useChatStore.getState().conversations.map((c) => c.id)).toEqual(['c2', 'c3']);
  });

  it('cancel clears the selection without deleting', async () => {
    renderSection();

    fireEvent.click(screen.getByRole('checkbox', { name: /select all chats in yesterday/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));

    expect(screen.queryByText('1 selected')).toBeNull();
    expect(chatApi.deleteConversation).not.toHaveBeenCalled();
  });
});
